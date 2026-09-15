"""Database telemetry recorder for Elastic Web.

Provides :class:`DatabaseTelemetryRecorder` which subscribes to :class:`EventBus`
and persists execution traces and execution steps into a relational database.

Dual backend support:
- Checks PostgreSQL availability (e.g. localhost:5432 via psycopg2).
- Zero-configuration local SQLite fallback storing at ``db/elastic_traces.db``
  or an in-memory / custom path.
- Database schema mirrors ``db/migrations/001_init.sql`` for ``execution_traces``
  and ``execution_steps``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .event_bus import EventBus
from .events import EventType, ExecutionEvent

logger = logging.getLogger(__name__)

# Try importing psycopg2 for optional PostgreSQL support.
try:
    import psycopg2
    import psycopg2.extras

    _PSYCOPG2_AVAILABLE = True
except ImportError:
    psycopg2 = None  # type: ignore
    _PSYCOPG2_AVAILABLE = False


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_PATH = str(_REPO_ROOT / "db" / "elastic_traces.db")

_TERMINAL_EVENTS = {
    EventType.OUTCOME_DELIVERED,
    EventType.EXECUTION_FAILED,
}


def _format_timestamp(ts: Optional[Union[float, int, str]] = None) -> str:
    """Format an epoch or None into an ISO-8601 UTC string."""
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(ts)


def _to_json(val: Any) -> str:
    """Serialize any value to a valid JSON string."""
    if val is None:
        return "{}"
    if isinstance(val, str):
        try:
            json.loads(val)
            return val
        except Exception:
            return json.dumps(val)
    return json.dumps(val, default=str)


def _from_json(val: Any) -> Any:
    """Deserialize a JSON string to Python structure, or return as-is."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return None
        try:
            return json.loads(val_str)
        except Exception:
            return val_str
    return val


class DatabaseTelemetryRecorder:
    """Subscribe to an EventBus and record execution traces & steps to DB.

    Supports PostgreSQL (if available) with automatic zero-configuration
    fallback to SQLite.
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        db_path: Optional[str] = None,
        pg_url: Optional[str] = None,
        pg_params: Optional[Dict[str, Any]] = None,
        force_sqlite: bool = False,
    ) -> None:
        self._bus: Optional[EventBus] = None
        self._lock = threading.Lock()
        self._trace_start_times: Dict[str, float] = {}
        self._step_start_times: Dict[int, float] = {}
        self._active_tool_steps: Dict[str, List[int]] = {}
        self._active_steps: Dict[str, List[int]] = {}

        # Resolve backend & connect
        self.backend, self._conn = self._init_connection(
            force_sqlite=force_sqlite,
            db_path=db_path,
            pg_url=pg_url,
            pg_params=pg_params,
        )

        # Initialize tables
        self._init_schema()

        # Subscribe to bus if provided
        if bus is not None:
            self.subscribe(bus)

    # -- Initialization & Schema ----------------------------------------

    def _init_connection(
        self,
        force_sqlite: bool,
        db_path: Optional[str],
        pg_url: Optional[str],
        pg_params: Optional[Dict[str, Any]],
    ) -> Tuple[str, Any]:
        """Detect available backend and establish connection."""
        is_memory = db_path == ":memory:"
        force_sql = (
            force_sqlite
            or is_memory
            or os.environ.get("FORCE_SQLITE", "").lower() in ("1", "true", "yes")
        )

        if not force_sql and _PSYCOPG2_AVAILABLE:
            try:
                conn = self._connect_postgres(pg_url=pg_url, pg_params=pg_params)
                if conn is not None:
                    return "postgres", conn
            except Exception as exc:
                logger.info("PostgreSQL unavailable (%s); falling back to SQLite", exc)

        # Fallback to SQLite
        target_path = db_path or os.environ.get("ELASTIC_DB_PATH") or DEFAULT_SQLITE_PATH
        if target_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

        conn = sqlite3.connect(
            target_path,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            if target_path != ":memory:":
                try:
                    conn.execute("PRAGMA journal_mode = WAL;")
                except sqlite3.OperationalError:
                    pass
        return "sqlite", conn

    @staticmethod
    def _connect_postgres(
        pg_url: Optional[str] = None, pg_params: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """Attempt a fast connection to PostgreSQL."""
        if not _PSYCOPG2_AVAILABLE:
            return None

        if pg_url:
            conn = psycopg2.connect(pg_url, connect_timeout=1)
            conn.autocommit = True
            return conn

        params = pg_params or {}
        host = params.get("host") or os.environ.get("PG_HOST") or os.environ.get("PGVECTOR_HOST") or "localhost"
        port = int(params.get("port") or os.environ.get("PG_PORT") or os.environ.get("PGVECTOR_PORT") or 5432)
        user = params.get("user") or os.environ.get("PG_USER") or os.environ.get("PGVECTOR_USER") or "postgres"
        # Password resolution chain: explicit params -> environment.
        # (Never a hardcoded credential.)
        password = (
            params.get("password")
            or os.environ.get("PG_PASSWORD")
            or os.environ.get("PGVECTOR_PASSWORD")
            or ""
        )
        dbname = params.get("dbname") or os.environ.get("PG_DB") or os.environ.get("PGVECTOR_DB") or "elastic_web"

        conn_kwargs = {
            "host": host, "port": port, "user": user,
            "password": password, "dbname": dbname, "connect_timeout": 1,
        }
        conn = psycopg2.connect(**conn_kwargs)
        conn.autocommit = True
        return conn

    def _init_schema(self) -> None:
        """Create execution_traces and execution_steps tables if they do not exist."""
        with self._lock:
            if self.backend == "sqlite":
                self._conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS execution_traces (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id        TEXT NOT NULL UNIQUE,
                        recipe_id       TEXT,
                        recipe_version  INTEGER,
                        status          TEXT NOT NULL DEFAULT 'running',
                        trigger         TEXT,
                        input           TEXT NOT NULL DEFAULT '{}',
                        output          TEXT,
                        error           TEXT,
                        started_at      TEXT NOT NULL,
                        finished_at     TEXT,
                        duration_ms     INTEGER,
                        metadata        TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE TABLE IF NOT EXISTS execution_steps (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id        INTEGER NOT NULL REFERENCES execution_traces(id) ON DELETE CASCADE,
                        step_key        TEXT NOT NULL,
                        parent_step_id  INTEGER REFERENCES execution_steps(id) ON DELETE CASCADE,
                        step_type       TEXT,
                        status          TEXT NOT NULL DEFAULT 'pending',
                        input           TEXT,
                        output          TEXT,
                        error           TEXT,
                        started_at      TEXT,
                        finished_at     TEXT,
                        duration_ms     INTEGER,
                        metadata        TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS idx_execution_traces_trace_id ON execution_traces(trace_id);
                    CREATE INDEX IF NOT EXISTS idx_execution_traces_status ON execution_traces(status);
                    CREATE INDEX IF NOT EXISTS idx_execution_traces_started ON execution_traces(started_at);
                    CREATE INDEX IF NOT EXISTS idx_execution_steps_trace ON execution_steps(trace_id);
                    CREATE INDEX IF NOT EXISTS idx_execution_steps_parent ON execution_steps(parent_step_id);
                    CREATE INDEX IF NOT EXISTS idx_execution_steps_status ON execution_steps(status);
                    """
                )
            else:
                with self._conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS execution_traces (
                            id              BIGSERIAL PRIMARY KEY,
                            trace_id        TEXT NOT NULL UNIQUE,
                            recipe_id       TEXT,
                            recipe_version  INTEGER,
                            status          TEXT NOT NULL DEFAULT 'running',
                            trigger         TEXT,
                            input           JSONB NOT NULL DEFAULT '{}'::jsonb,
                            output          JSONB,
                            error           JSONB,
                            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                            finished_at     TIMESTAMPTZ,
                            duration_ms     BIGINT,
                            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
                        );

                        CREATE TABLE IF NOT EXISTS execution_steps (
                            id              BIGSERIAL PRIMARY KEY,
                            trace_id        BIGINT NOT NULL REFERENCES execution_traces(id) ON DELETE CASCADE,
                            step_key        TEXT NOT NULL,
                            parent_step_id  BIGINT REFERENCES execution_steps(id) ON DELETE CASCADE,
                            step_type       TEXT,
                            status          TEXT NOT NULL DEFAULT 'pending',
                            input           JSONB,
                            output          JSONB,
                            error           JSONB,
                            started_at      TIMESTAMPTZ,
                            finished_at     TIMESTAMPTZ,
                            duration_ms     BIGINT,
                            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
                        );

                        CREATE INDEX IF NOT EXISTS idx_execution_traces_trace_id ON execution_traces(trace_id);
                        CREATE INDEX IF NOT EXISTS idx_execution_traces_status ON execution_traces(status);
                        CREATE INDEX IF NOT EXISTS idx_execution_traces_started ON execution_traces(started_at);
                        CREATE INDEX IF NOT EXISTS idx_execution_steps_trace ON execution_steps(trace_id);
                        CREATE INDEX IF NOT EXISTS idx_execution_steps_parent ON execution_steps(parent_step_id);
                        CREATE INDEX IF NOT EXISTS idx_execution_steps_status ON execution_steps(status);
                        """
                    )

    # -- DB query / execute helpers -------------------------------------

    def _execute(self, query: str, params: Tuple[Any, ...] = ()) -> Any:
        """Execute a query with parameter substitution adapted to the backend."""
        if self.backend == "sqlite":
            sql = query.replace("%s", "?")
            return self._conn.execute(sql, params)
        else:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query, params)
            return cur

    def _fetchall(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        """Fetch all rows returned by query as a list of dicts."""
        with self._lock:
            cur = self._execute(query, params)
            if self.backend == "sqlite":
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            else:
                rows = cur.fetchall()
                cur.close()
                return [dict(r) for r in rows]

    def _fetchone(self, query: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
        """Fetch one row returned by query as a dict or None."""
        with self._lock:
            cur = self._execute(query, params)
            if self.backend == "sqlite":
                row = cur.fetchone()
                return dict(row) if row is not None else None
            else:
                row = cur.fetchone()
                cur.close()
                return dict(row) if row is not None else None

    # -- EventBus Integration -------------------------------------------

    def subscribe(self, bus: EventBus) -> None:
        """Subscribe this recorder to an EventBus."""
        self._bus = bus
        bus.subscribe(self._on_event)

    def unsubscribe(self) -> None:
        """Unsubscribe from the current EventBus."""
        if self._bus is not None:
            self._bus.unsubscribe(self._on_event)
            self._bus = None

    def __call__(self, event: ExecutionEvent) -> None:
        """Allow the recorder itself to be passed directly as a subscriber callable."""
        self._on_event(event)

    # -- Event Processing -----------------------------------------------

    def _on_event(self, event: ExecutionEvent) -> None:
        """Handle incoming ExecutionEvent and persist trace/step updates."""
        trace_id = event.trace_id
        timestamp = event.timestamp
        payload = event.payload or {}

        # Ensure start time recorded
        if trace_id not in self._trace_start_times:
            self._trace_start_times[trace_id] = timestamp

        # Ensure trace row exists
        trace_db_id = self._ensure_trace(event)

        # Dispatch based on event type
        if event.event_type == EventType.INTENT_RECEIVED:
            self._handle_intent_received(trace_id, event)

        elif event.event_type == EventType.RECIPE_RETRIEVED:
            self._handle_recipe_retrieved(trace_id, payload)

        elif event.event_type == EventType.RECIPE_STARTED:
            self._handle_recipe_started(trace_id, payload)

        elif event.event_type == EventType.RECIPE_STEP_STARTED:
            self._handle_recipe_step_started(trace_db_id, trace_id, event)

        elif event.event_type == EventType.TOOL_CALLED:
            self._handle_tool_called(trace_db_id, trace_id, event)

        elif event.event_type == EventType.TOOL_COMPLETED:
            self._handle_tool_completed(trace_id, event)

        elif event.event_type == EventType.RECIPE_COMPLETED:
            self._handle_recipe_completed(trace_db_id, event)

        elif event.event_type == EventType.OUTCOME_DELIVERED:
            self._handle_outcome_delivered(trace_db_id, trace_id, event)

        elif event.event_type == EventType.EXECUTION_FAILED:
            self._handle_execution_failed(trace_db_id, trace_id, event)

        # Also capture any model/tokens info in payload
        self._capture_metadata(trace_id, event)

    def _ensure_trace(self, event: ExecutionEvent) -> int:
        """Return the integer primary key of the trace, inserting if needed."""
        trace_id = event.trace_id
        row = self._fetchone("SELECT id FROM execution_traces WHERE trace_id = %s", (trace_id,))
        if row is not None:
            return int(row["id"])

        started_at = _format_timestamp(event.timestamp)
        trigger = event.payload.get("trigger", "user") if event.payload else "user"
        initial_input = "{}"
        if event.payload and "input" in event.payload:
            initial_input = _to_json(event.payload["input"])
        elif event.payload and event.event_type == EventType.INTENT_RECEIVED:
            initial_input = _to_json(event.payload)

        initial_meta = {}
        if event.intent_id:
            initial_meta["intent_id"] = event.intent_id

        with self._lock:
            if self.backend == "sqlite":
                cur = self._conn.execute(
                    """
                    INSERT INTO execution_traces (trace_id, status, trigger, input, started_at, metadata)
                    VALUES (?, 'running', ?, ?, ?, ?)
                    ON CONFLICT(trace_id) DO NOTHING
                    """,
                    (trace_id, trigger, initial_input, started_at, _to_json(initial_meta)),
                )
                if cur.lastrowid:
                    return int(cur.lastrowid)
            else:
                with self._conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO execution_traces (trace_id, status, trigger, input, started_at, metadata)
                        VALUES (%s, 'running', %s, %s, %s, %s)
                        ON CONFLICT(trace_id) DO NOTHING
                        RETURNING id
                        """,
                        (trace_id, trigger, initial_input, started_at, _to_json(initial_meta)),
                    )
                    inserted = cur.fetchone()
                    if inserted:
                        return int(inserted[0])

        # If already existed, query id
        row = self._fetchone("SELECT id FROM execution_traces WHERE trace_id = %s", (trace_id,))
        return int(row["id"]) if row else 0

    def _handle_intent_received(self, trace_id: str, event: ExecutionEvent) -> None:
        payload = event.payload or {}
        input_data = payload.get("input") or payload
        with self._lock:
            self._execute(
                """
                UPDATE execution_traces
                SET input = %s
                WHERE trace_id = %s
                """,
                (_to_json(input_data), trace_id),
            )

    def _handle_recipe_retrieved(self, trace_id: str, payload: Dict[str, Any]) -> None:
        recipe_id = payload.get("recipe_id") or payload.get("recipe")
        recipe_version_raw = payload.get("recipe_version") or payload.get("version")
        recipe_version = None
        if recipe_version_raw is not None:
            try:
                recipe_version = int(recipe_version_raw)
            except (ValueError, TypeError):
                recipe_version = None

        with self._lock:
            self._execute(
                """
                UPDATE execution_traces
                SET recipe_id = COALESCE(%s, recipe_id),
                    recipe_version = COALESCE(%s, recipe_version)
                WHERE trace_id = %s
                """,
                (str(recipe_id) if recipe_id is not None else None, recipe_version, trace_id),
            )

    def _handle_recipe_started(self, trace_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._execute(
                """
                UPDATE execution_traces
                SET status = 'running'
                WHERE trace_id = %s AND status = 'pending'
                """,
                (trace_id,),
            )

    def _handle_recipe_step_started(
        self, trace_db_id: int, trace_id: str, event: ExecutionEvent
    ) -> None:
        payload = event.payload or {}
        step_key = (
            payload.get("step_key")
            or (f"step-{payload.get('step')}" if "step" in payload else None)
            or payload.get("name")
            or "step"
        )
        step_type = payload.get("step_type") or "step"
        parent_step_id = payload.get("parent_step_id")
        started_at = _format_timestamp(event.timestamp)
        step_input = payload.get("input", payload)

        with self._lock:
            if self.backend == "sqlite":
                cur = self._conn.execute(
                    """
                    INSERT INTO execution_steps
                    (trace_id, step_key, parent_step_id, step_type, status, input, started_at, metadata)
                    VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                    """,
                    (
                        trace_db_id,
                        str(step_key),
                        parent_step_id,
                        step_type,
                        _to_json(step_input),
                        started_at,
                        _to_json(payload),
                    ),
                )
                step_id = int(cur.lastrowid)
            else:
                with self._conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO execution_steps
                        (trace_id, step_key, parent_step_id, step_type, status, input, started_at, metadata)
                        VALUES (%s, %s, %s, %s, 'running', %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            trace_db_id,
                            str(step_key),
                            parent_step_id,
                            step_type,
                            _to_json(step_input),
                            started_at,
                            _to_json(payload),
                        ),
                    )
                    step_id = int(cur.fetchone()[0])

        self._step_start_times[step_id] = event.timestamp
        self._active_steps.setdefault(trace_id, []).append(step_id)

    def _handle_tool_called(
        self, trace_db_id: int, trace_id: str, event: ExecutionEvent
    ) -> None:
        payload = event.payload or {}
        tool_name = (
            payload.get("tool")
            or payload.get("name")
            or payload.get("tool_name")
            or "unknown"
        )
        tool_args = payload.get("args") or payload.get("input") or {}
        started_at = _format_timestamp(event.timestamp)

        with self._lock:
            if self.backend == "sqlite":
                cur = self._conn.execute(
                    """
                    INSERT INTO execution_steps
                    (trace_id, step_key, step_type, status, input, started_at, metadata)
                    VALUES (?, ?, 'tool', 'running', ?, ?, ?)
                    """,
                    (
                        trace_db_id,
                        str(tool_name),
                        _to_json(tool_args),
                        started_at,
                        _to_json(payload),
                    ),
                )
                step_id = int(cur.lastrowid)
            else:
                with self._conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO execution_steps
                        (trace_id, step_key, step_type, status, input, started_at, metadata)
                        VALUES (%s, %s, 'tool', 'running', %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            trace_db_id,
                            str(tool_name),
                            _to_json(tool_args),
                            started_at,
                            _to_json(payload),
                        ),
                    )
                    step_id = int(cur.fetchone()[0])

        self._step_start_times[step_id] = event.timestamp
        self._active_tool_steps.setdefault(trace_id, []).append(step_id)

    def _handle_tool_completed(self, trace_id: str, event: ExecutionEvent) -> None:
        payload = event.payload or {}
        status_val = payload.get("status") or payload.get("result")
        if isinstance(status_val, str) and status_val.lower() in {
            "error",
            "failed",
            "failure",
        }:
            status = "failed"
        else:
            status = "succeeded"

        finished_at = _format_timestamp(event.timestamp)
        output_data = payload.get("output") or payload.get("result") or payload
        error_data = payload.get("error")

        # Find matching open tool step
        step_id: Optional[int] = None
        active_list = self._active_tool_steps.get(trace_id, [])
        if active_list:
            step_id = active_list.pop()
        else:
            # Fallback: find latest running tool step in DB
            row = self._fetchone(
                """
                SELECT s.id FROM execution_steps s
                JOIN execution_traces t ON s.trace_id = t.id
                WHERE t.trace_id = %s AND s.step_type = 'tool' AND s.status = 'running'
                ORDER BY s.id DESC LIMIT 1
                """,
                (trace_id,),
            )
            if row:
                step_id = int(row["id"])

        if step_id is not None:
            start_ts = self._step_start_times.get(step_id, event.timestamp)
            duration_ms: Optional[int] = None
            if "duration" in payload and isinstance(payload["duration"], (int, float)):
                duration_ms = int(round(payload["duration"] * 1000))
            elif "duration_ms" in payload and isinstance(payload["duration_ms"], (int, float)):
                duration_ms = int(payload["duration_ms"])
            else:
                duration_ms = max(0, int(round((event.timestamp - start_ts) * 1000)))

            with self._lock:
                self._execute(
                    """
                    UPDATE execution_steps
                    SET status = %s, output = %s, error = %s, finished_at = %s, duration_ms = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        _to_json(output_data),
                        _to_json(error_data) if error_data else None,
                        finished_at,
                        duration_ms,
                        step_id,
                    ),
                )

    def _handle_recipe_completed(self, trace_db_id: int, event: ExecutionEvent) -> None:
        finished_at = _format_timestamp(event.timestamp)
        with self._lock:
            self._execute(
                """
                UPDATE execution_steps
                SET status = 'succeeded', finished_at = COALESCE(finished_at, %s)
                WHERE trace_id = %s AND status = 'running'
                """,
                (finished_at, trace_db_id),
            )

    def _handle_outcome_delivered(
        self, trace_db_id: int, trace_id: str, event: ExecutionEvent
    ) -> None:
        payload = event.payload or {}
        output_data = payload.get("output") or payload.get("outcome") or payload
        finished_at = _format_timestamp(event.timestamp)
        start_ts = self._trace_start_times.get(trace_id, event.timestamp)
        duration_ms = max(0, int(round((event.timestamp - start_ts) * 1000)))

        with self._lock:
            self._execute(
                """
                UPDATE execution_traces
                SET status = 'succeeded', output = %s, finished_at = %s, duration_ms = %s
                WHERE trace_id = %s
                """,
                (_to_json(output_data), finished_at, duration_ms, trace_id),
            )
            # Mark any still-running steps as succeeded
            self._execute(
                """
                UPDATE execution_steps
                SET status = 'succeeded', finished_at = COALESCE(finished_at, %s)
                WHERE trace_id = %s AND status = 'running'
                """,
                (finished_at, trace_db_id),
            )

    def _handle_execution_failed(
        self, trace_db_id: int, trace_id: str, event: ExecutionEvent
    ) -> None:
        payload = event.payload or {}
        error_data = payload.get("error") or payload.get("message") or payload
        finished_at = _format_timestamp(event.timestamp)
        start_ts = self._trace_start_times.get(trace_id, event.timestamp)
        duration_ms = max(0, int(round((event.timestamp - start_ts) * 1000)))

        with self._lock:
            self._execute(
                """
                UPDATE execution_traces
                SET status = 'failed', error = %s, finished_at = %s, duration_ms = %s
                WHERE trace_id = %s
                """,
                (_to_json(error_data), finished_at, duration_ms, trace_id),
            )
            # Mark any still-running steps as failed
            self._execute(
                """
                UPDATE execution_steps
                SET status = 'failed', error = COALESCE(error, %s), finished_at = COALESCE(finished_at, %s)
                WHERE trace_id = %s AND status = 'running'
                """,
                (_to_json(error_data), finished_at, trace_db_id),
            )

    def _capture_metadata(self, trace_id: str, event: ExecutionEvent) -> None:
        payload = event.payload or {}
        keys_to_capture = ["model", "provider", "tokens", "token_usage", "capability_ids"]
        found = {k: payload[k] for k in keys_to_capture if k in payload and payload[k] is not None}
        if not found and not event.intent_id:
            return

        row = self._fetchone(
            "SELECT metadata FROM execution_traces WHERE trace_id = %s", (trace_id,)
        )
        if row is None:
            return

        current_meta = _from_json(row["metadata"]) or {}
        if not isinstance(current_meta, dict):
            current_meta = {}

        if event.intent_id and "intent_id" not in current_meta:
            current_meta["intent_id"] = event.intent_id
        current_meta.update(found)

        with self._lock:
            self._execute(
                "UPDATE execution_traces SET metadata = %s WHERE trace_id = %s",
                (_to_json(current_meta), trace_id),
            )

    # -- Query API ------------------------------------------------------

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an execution trace by trace_id.

        Returns a dictionary with deserialized JSON columns, or None if not found.
        """
        row = self._fetchone(
            """
            SELECT id, trace_id, recipe_id, recipe_version, status, trigger,
                   input, output, error, started_at, finished_at, duration_ms, metadata
            FROM execution_traces
            WHERE trace_id = %s
            """,
            (trace_id,),
        )
        if row is None:
            return None
        return self._format_trace_row(row)

    def list_traces(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List execution traces ordered newest first."""
        rows = self._fetchall(
            """
            SELECT id, trace_id, recipe_id, recipe_version, status, trigger,
                   input, output, error, started_at, finished_at, duration_ms, metadata
            FROM execution_traces
            ORDER BY id DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return [self._format_trace_row(r) for r in rows]

    def get_trace_steps(self, trace_id: str) -> List[Dict[str, Any]]:
        """Retrieve all execution steps for the specified trace_id."""
        rows = self._fetchall(
            """
            SELECT s.id, s.trace_id, s.step_key, s.parent_step_id, s.step_type,
                   s.status, s.input, s.output, s.error, s.started_at, s.finished_at,
                   s.duration_ms, s.metadata
            FROM execution_steps s
            JOIN execution_traces t ON s.trace_id = t.id
            WHERE t.trace_id = %s OR CAST(s.trace_id AS TEXT) = %s
            ORDER BY s.id ASC
            """,
            (trace_id, trace_id),
        )
        return [self._format_step_row(r) for r in rows]

    # -- Row Formatters -------------------------------------------------

    @staticmethod
    def _format_trace_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "trace_id": row["trace_id"],
            "recipe_id": row["recipe_id"],
            "recipe_version": row["recipe_version"],
            "status": row["status"],
            "trigger": row["trigger"],
            "input": _from_json(row["input"]),
            "output": _from_json(row["output"]),
            "error": _from_json(row["error"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "metadata": _from_json(row["metadata"]) or {},
        }

    @staticmethod
    def _format_step_row(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "trace_id": row["trace_id"],
            "step_key": row["step_key"],
            "parent_step_id": row["parent_step_id"],
            "step_type": row["step_type"],
            "status": row["status"],
            "input": _from_json(row["input"]),
            "output": _from_json(row["output"]),
            "error": _from_json(row["error"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "metadata": _from_json(row["metadata"]) or {},
        }

    # -- Cleanup & Management -------------------------------------------

    def clear(self) -> None:
        """Drop all traces and steps from the database."""
        with self._lock:
            self._execute("DELETE FROM execution_steps")
            self._execute("DELETE FROM execution_traces")
        self._trace_start_times.clear()
        self._step_start_times.clear()
        self._active_tool_steps.clear()
        self._active_steps.clear()

    def close(self) -> None:
        """Unsubscribe from event bus and close database connection."""
        self.unsubscribe()
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __enter__(self) -> "DatabaseTelemetryRecorder":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
