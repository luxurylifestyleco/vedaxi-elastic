"""Thin A2A transport boundary over Elastic compilation and runtime."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

# The repository runs package tests as source modules.  Add the sibling
# assurance source directory exactly as the gateway bootstrap does, without
# creating a second assurance implementation.
_ASSURANCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assurance-protocol",
)
if _ASSURANCE_DIR not in sys.path:
    sys.path.insert(0, _ASSURANCE_DIR)

from recipe import Recipe, RecipeStep
from evaluator import evaluate_outcome
from outcome import EvidenceRecord, OutcomeEnvelope, OutcomeStatus, transition_outcome
from verification import VerificationContext, VerificationEngine

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class A2AContentTypeNotSupportedError(ValueError):
    """Raised when a message part cannot be handled by this agent."""


def _task_state(task: Dict[str, Any]) -> str:
    return str(task.get("status", {}).get("state", "")).lower().replace("task_state_", "").replace("cancelled", "canceled").replace("_", "-")


def _terminal_task(task: Dict[str, Any]) -> bool:
    return _task_state(task) in {"completed", "failed", "canceled", "rejected"}


def _interrupted_task(task: Dict[str, Any], state: str, reason: str) -> Dict[str, Any]:
    task = json.loads(json.dumps(task))
    task["status"] = {"state": "TASK_STATE_" + state.upper().replace("-", "_")}
    metadata = task.setdefault("metadata", {})
    metadata.update(completionAuthoritative=False, resultRejected=True, interruptionReason=reason)
    for key in ("outcomeStatus", "verificationStatus", "verificationId", "evidenceId"):
        metadata.pop(key, None)
    task["artifacts"] = [{"parts": [{"text": reason}, {"data": {"error": reason}, "mediaType": "application/json"}]}]
    return task


class A2ATaskStore:
    """Small process-local task store for the A2A polling lifecycle.

    This is deliberately not presented as durable task persistence. Replace it
    with the existing runtime persistence boundary before external deployment.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    def _guard_update(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Check updates under the store lock, retaining the host's ownership."""
        task = json.loads(json.dumps(task))
        metadata = task.setdefault("metadata", {})
        tenant_id = metadata.get("tenantId")
        previous = self.get(task["id"], tenant_id=tenant_id)
        if previous is None and metadata.get("messageId"):
            duplicate = self.get_by_message(metadata["messageId"], metadata.get("sessionId") or "", tenant_id=tenant_id)
            if duplicate is not None and duplicate["id"] != task["id"]:
                raise ValueError("messageId is already submitted")
        if previous is not None:
            if task.get("contextId") != previous.get("contextId"):
                raise ValueError("A2A task context is immutable")
            prior = previous.get("metadata", {})
            for key in ("tenantId", "principalId", "sessionId", "contextId", "messageId", "traceId", "intentId", "intentRevision", "revisionBound"):
                if key in prior:
                    if key in metadata and metadata[key] != prior[key]:
                        raise ValueError("A2A task identity and revision are immutable")
                    metadata[key] = prior[key]
            if _terminal_task(previous):
                return previous
            if prior.get("cancellationRequested") or prior.get("cancelState") == "requested":
                metadata.update(cancellationRequested=True, cancelState="requested", executionMayHaveOccurred=True)
                return _interrupted_task(task, "canceled", "Cancellation requested; late result discarded. Provider effects may need reconciliation.")
            if _task_state(previous) in {"auth-required", "input-required"}:
                if metadata.get("cancellationRequested") or metadata.get("cancelState") == "requested":
                    metadata["cancelState"] = "canceled"
                    return _interrupted_task(task, "canceled", "Paused task canceled; no completion claimed.")
                return previous
        if metadata.get("revisionBound"):
            scope = ("tenantId", "principalId", "sessionId", "contextId", "intentId")
            for other in self.all(tenant_id=tenant_id):
                other_meta = other.get("metadata", {})
                if other["id"] == task["id"] or not other_meta.get("revisionAccepted"):
                    continue
                if all(metadata.get(key) == other_meta.get(key) for key in scope):
                    if other_meta["intentRevision"] >= metadata["intentRevision"]:
                        return _interrupted_task(task, "failed", "Stale or already submitted intent revision; result discarded.")
            metadata["revisionAccepted"] = True
        return task

    def put(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("A2A task requires a string id")
        with self._lock:
            task = self._guard_update(task)
            self._tasks[task_id] = json.loads(json.dumps(task))
            metadata = task.get("metadata", {})
            message_id = metadata.get("messageId")
            if isinstance(message_id, str) and message_id:
                session_id = metadata.get("sessionId") or ""
                self._messages[(session_id, message_id)] = task_id
            return json.loads(json.dumps(self._tasks[task_id]))

    def get_by_message(
        self, message_id: str, session_id: str = "", *, tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            task_id = self._messages.get((session_id, message_id))
            task = self._tasks.get(task_id) if task_id is not None else None
            return json.loads(json.dumps(task)) if task is not None else None

    def get(self, task_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return json.loads(json.dumps(task)) if task is not None else None

    def cancel(self, task_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            state = task.get("status", {}).get("state")
            if _task_state(task) in {"submitted", "auth-required", "input-required"}:
                task = _interrupted_task(task, "canceled", "Task canceled before further execution; no completion claimed.")
                task.setdefault("metadata", {})["cancelled"] = True
                self._tasks[task_id] = task
            elif not _terminal_task(task):
                task.setdefault("metadata", {})["cancellationRequested"] = True
            return json.loads(json.dumps(task))

    def all(self, *, tenant_id: Optional[str] = None) -> list[Dict[str, Any]]:
        with self._lock:
            return [json.loads(json.dumps(task)) for task in self._tasks.values()]


class SQLiteA2ATaskStore(A2ATaskStore):
    """Restart-safe local task store using the existing task-store contract.

    This is an opt-in local persistence boundary. Remote PostgreSQL/Supabase
    still requires the named migration target and explicit application gate.
    """

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path:
            raise ValueError("SQLite task store requires a database path")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS a2a_tasks_local (
                    task_id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    session_id TEXT,
                    message_id TEXT,
                    context_id TEXT,
                    state TEXT NOT NULL,
                    cancel_state TEXT NOT NULL DEFAULT 'not_requested',
                    payload TEXT NOT NULL,
                    UNIQUE (tenant_id, session_id, message_id)
                )
                """
            )

    @staticmethod
    def _copy(task: Dict[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(task))

    @staticmethod
    def _fields(task: Dict[str, Any]) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str], str, str, str]:
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        status = task.get("status") if isinstance(task.get("status"), dict) else {}
        return (
            str(task["id"]),
            metadata.get("tenantId"),
            metadata.get("sessionId"),
            metadata.get("messageId"),
            task.get("contextId") or metadata.get("contextId"),
            str(status.get("state", "submitted")),
            str(metadata.get("cancelState", "not_requested")),
            json.dumps(task),
        )

    def put(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("A2A task requires a string id")
        with self._lock, self._conn:
            if not self._conn.in_transaction:
                self._conn.execute("BEGIN IMMEDIATE")
            task = self._guard_update(task)
            fields = self._fields(task)
            self._conn.execute(
                """
                INSERT INTO a2a_tasks_local
                    (task_id, tenant_id, session_id, message_id, context_id, state, cancel_state, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state = excluded.state,
                    cancel_state = excluded.cancel_state,
                    payload = excluded.payload
                """,
                fields,
            )
        return self._copy(task)

    def _get(self, query: str, params: tuple[Any, ...]) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(query, params).fetchone()
        return self._copy(json.loads(row["payload"])) if row else None

    def get_by_message(
        self, message_id: str, session_id: str = "", *, tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._get(
                "SELECT payload FROM a2a_tasks_local WHERE message_id = ? AND session_id = ?",
                (message_id, session_id),
            )

    def get(self, task_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._get("SELECT payload FROM a2a_tasks_local WHERE task_id = ?", (task_id,))

    def cancel(self, task_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            task = self.get(task_id)
            if task is None:
                return None
            state = task.get("status", {}).get("state")
            metadata = task.setdefault("metadata", {})
            if _task_state(task) == "submitted":
                task.setdefault("status", {})["state"] = "TASK_STATE_CANCELED"
                metadata["cancelled"] = True
                metadata["cancelState"] = "canceled"
            elif not _terminal_task(task):
                metadata["cancellationRequested"] = True
                metadata["cancelState"] = "requested"
            return self.put(task)

    def all(self, *, tenant_id: Optional[str] = None) -> list[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM a2a_tasks_local ORDER BY rowid").fetchall()
            return [self._copy(json.loads(row["payload"])) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class PostgresA2ATaskStore(A2ATaskStore):
    """DSN-gated store for the existing ``public.a2a_tasks`` contract."""

    def __init__(self, dsn: str, connection_factory: Optional[Callable[[str], Any]] = None) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("Postgres task store requires ELASTIC_CHAT_POSTGRES_DSN")
        self._dsn = dsn
        self._connect = connection_factory or self._default_connect
        self._lock = threading.RLock()

    @staticmethod
    def _default_connect(dsn: str) -> Any:
        import psycopg2
        return psycopg2.connect(dsn)

    @staticmethod
    def _fields(task: Dict[str, Any]) -> tuple[Any, ...]:
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        status = task.get("status") if isinstance(task.get("status"), dict) else {}
        state = str(status.get("state", "submitted")).lower().replace("task_state_", "")
        if state == "cancelled":
            state = "canceled"
        if state == "auth_required":
            state = "input-required"
        return (
            task["id"], metadata.get("tenantId"), metadata.get("principalId"),
            metadata.get("sessionId"), task.get("contextId") or metadata.get("contextId"),
            metadata.get("messageId"), metadata.get("intentId"), metadata.get("traceId"),
            metadata.get("outcomeId"), metadata.get("evidenceId"), metadata.get("verificationId"),
            state, metadata.get("cancelState", "not_requested"),
        )

    @staticmethod
    def _require_tenant_id(tenant_id: Optional[str]) -> str:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Postgres A2A task access requires tenant_id")
        return tenant_id

    def _query(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        tenant_id: Optional[str],
        fetchone: bool = False,
        fetchall: bool = False,
    ) -> Any:
        tenant_id = self._require_tenant_id(tenant_id)
        conn = self._connect(self._dsn)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cursor.execute(sql, params)
                result = cursor.fetchone() if fetchone else cursor.fetchall() if fetchall else None
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def put(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task.get("id"), str) or not task["id"]:
            raise ValueError("A2A task requires a string id")
        if task.get("metadata", {}).get("revisionBound"):
            raise ValueError("Revision-bound tasks require the local or SQLite task store; PostgreSQL revision persistence is not supported")
        fields = self._fields(task)
        if any(value is None for value in fields[1:5]):
            raise ValueError("Postgres A2A tasks require tenant, principal, session, and context")
        with self._lock:
            task = self._guard_update(task)
            fields = self._fields(task)
            self._query(
                """INSERT INTO public.a2a_tasks
                (task_id, tenant_id, principal_id, session_id, context_id, message_id,
                 intent_id, trace_id, outcome_id, evidence_id, verification_id, state, cancel_state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (task_id) DO UPDATE SET state = EXCLUDED.state,
                    cancel_state = EXCLUDED.cancel_state, cancellation_requested_at =
                    CASE WHEN EXCLUDED.cancel_state IN ('requested', 'canceled') THEN now()
                         ELSE public.a2a_tasks.cancellation_requested_at END,
                    canceled_at = CASE WHEN EXCLUDED.cancel_state = 'canceled' THEN now()
                         ELSE public.a2a_tasks.canceled_at END,
                    intent_id = EXCLUDED.intent_id, trace_id = EXCLUDED.trace_id,
                    outcome_id = EXCLUDED.outcome_id, evidence_id = EXCLUDED.evidence_id,
                    verification_id = EXCLUDED.verification_id""",
                fields,
                tenant_id=fields[1],
            )
        return json.loads(json.dumps(task))

    @staticmethod
    def _row_payload(row: Any) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        if isinstance(row, dict):
            values = row
        else:
            values = dict(zip(("task_id", "tenant_id", "principal_id", "session_id", "context_id",
                               "message_id", "intent_id", "trace_id", "outcome_id", "evidence_id",
                               "verification_id", "state", "cancel_state"), row))
        metadata = {"taskId": values["task_id"], "tenantId": values["tenant_id"],
                    "principalId": values["principal_id"], "sessionId": values["session_id"],
                    "contextId": values["context_id"], "messageId": values["message_id"],
                    "intentId": values["intent_id"], "traceId": values["trace_id"],
                    "outcomeId": values["outcome_id"], "evidenceId": values["evidence_id"],
                    "verificationId": values["verification_id"], "cancelState": values["cancel_state"]}
        metadata = {key: value for key, value in metadata.items() if value is not None}
        return {"id": values["task_id"], "contextId": values["context_id"],
                "status": {"state": values["state"]}, "metadata": metadata}

    def get_by_message(
        self, message_id: str, session_id: str = "", *, tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._query("SELECT task_id, tenant_id, principal_id, session_id, context_id, message_id, intent_id, trace_id, outcome_id, evidence_id, verification_id, state, cancel_state FROM public.a2a_tasks WHERE message_id = %s AND session_id = %s AND tenant_id = %s ORDER BY created_at LIMIT 1", (message_id, session_id, tenant_id), tenant_id=tenant_id, fetchone=True)
            return self._row_payload(row)

    def get(self, task_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._query("SELECT task_id, tenant_id, principal_id, session_id, context_id, message_id, intent_id, trace_id, outcome_id, evidence_id, verification_id, state, cancel_state FROM public.a2a_tasks WHERE task_id = %s AND tenant_id = %s", (task_id, tenant_id), tenant_id=tenant_id, fetchone=True)
            return self._row_payload(row)

    def cancel(self, task_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self.get(task_id, tenant_id=tenant_id)
            if task is None:
                return None
            state = task["status"]["state"]
            metadata = task.setdefault("metadata", {})
            if state == "submitted":
                task["status"]["state"] = "canceled"
                metadata["cancelState"] = "canceled"
            elif state not in {"completed", "failed", "canceled"}:
                metadata["cancelState"] = "requested"
            return self.put(task)

    def all(self, *, tenant_id: Optional[str] = None) -> list[Dict[str, Any]]:
        with self._lock:
            rows = self._query("SELECT task_id, tenant_id, principal_id, session_id, context_id, message_id, intent_id, trace_id, outcome_id, evidence_id, verification_id, state, cancel_state FROM public.a2a_tasks WHERE tenant_id = %s ORDER BY created_at", (tenant_id,), tenant_id=tenant_id, fetchall=True)
            return [self._row_payload(row) for row in rows]


def _canonical_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the legacy local shape to the current A2A task vocabulary."""
    states = {
        "TASK_STATE_SUBMITTED": "submitted",
        "TASK_STATE_WORKING": "working",
        "TASK_STATE_INPUT_REQUIRED": "input-required",
        "TASK_STATE_AUTH_REQUIRED": "auth-required",
        "TASK_STATE_COMPLETED": "completed",
        "TASK_STATE_CANCELED": "canceled",
        "TASK_STATE_FAILED": "failed",
        "TASK_STATE_REJECTED": "rejected",
    }
    canonical = json.loads(json.dumps(task))
    state = canonical.get("status", {}).get("state")
    canonical.setdefault("status", {})["state"] = states.get(state, state)
    return canonical


class A2AInboundAdapter:
    """Normalize one A2A message through Intent IR, retrieval, and runtime."""

    def __init__(
        self,
        *,
        compiler: Any,
        retriever: Any,
        capability_by_id: Callable[[str], Any],
        runner: Any,
        executor: Callable[[str, Dict[str, Any]], Any],
        bus: Any,
        source_endpoint: str,
        verification_engine: Optional[VerificationEngine] = None,
        task_store: Optional[A2ATaskStore] = None,
        authorization_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.compiler = compiler
        self.retriever = retriever
        self.capability_by_id = capability_by_id
        self.runner = runner
        self.executor = executor
        self.bus = bus
        self.source_endpoint = source_endpoint
        self.verification_engine = verification_engine or VerificationEngine()
        self.task_store = task_store
        self.authorization_check = authorization_check

    def _remember(self, response: Dict[str, Any]) -> Dict[str, Any]:
        if self.task_store is not None:
            response["task"] = self.task_store.put(response["task"])
        return response

    def handle(
        self,
        request: Dict[str, Any],
        *,
        _on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        message = request.get("message")
        if not isinstance(message, dict) or message.get("role") not in {
            "ROLE_USER",
            "user",
        }:
            raise ValueError("A2A request requires a user message")
        parts = message.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("A2A message requires at least one part")
        if any(
            isinstance(part, dict)
            and any(key in part for key in ("raw", "url"))
            and not isinstance(part.get("text"), str)
            for part in parts
        ):
            raise A2AContentTypeNotSupportedError("Unsupported media type")
        text = "\n".join(
            part["text"].strip()
            for part in parts
            if isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        )
        if not text:
            raise ValueError("A2A message requires a text part")

        metadata = message.get("metadata")
        message_metadata = metadata if isinstance(metadata, dict) else {}
        message_id = message.get("messageId")
        session_id = message_metadata.get("sessionId")
        tenant_id = message_metadata.get("tenantId")
        if "intentId" in message_metadata or "intentRevision" in message_metadata:
            if (not isinstance(message_metadata.get("intentId"), str) or not message_metadata["intentId"].strip()
                    or type(message_metadata.get("intentRevision")) is not int or message_metadata["intentRevision"] < 1):
                raise ValueError("intentId and positive integer intentRevision are required")
        if self.task_store is not None and isinstance(message_id, str) and message_id:
            existing = self.task_store.get_by_message(
                message_id, session_id or "", tenant_id=tenant_id
            )
            if existing is not None:
                if message.get("contextId") not in {None, existing.get("contextId")}:
                    raise ValueError("messageId is already bound to another context")
                for key in ("intentId", "intentRevision"):
                    if key in message_metadata and existing.get("metadata", {}).get(key) != message_metadata[key]:
                        raise ValueError("messageId is already bound to another intent revision")
                return {"task": existing}

        task_id = uuid.uuid4().hex
        context_id = message.get("contextId") or uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        binding = {key: message_metadata[key] for key in ("tenantId", "principalId") if key in message_metadata}
        revision_bound = "intentId" in message_metadata or "intentRevision" in message_metadata
        if revision_bound:
            revision = message_metadata.get("intentRevision")
            identity = message_metadata.get("intentId")
            if (not isinstance(identity, str) or not identity.strip() or type(revision) is not int
                    or revision < 1 or not isinstance(session_id, str) or not session_id.strip()
                    or not isinstance(message.get("contextId"), str) or not message["contextId"].strip()):
                raise ValueError("intentId and positive integer intentRevision require a session and context")
            if self.task_store is None or isinstance(self.task_store, PostgresA2ATaskStore):
                raise ValueError("Revision-bound tasks require the local or SQLite task store")
            binding.update(intentId=identity, intentRevision=revision, revisionBound=True)

        def remember(response):
            response["task"].setdefault("metadata", {}).update(binding)
            return self._remember(response)

        def checkpoint():
            task = self.task_store.get(task_id, tenant_id=tenant_id) if self.task_store else None
            if task is not None:
                task = self.task_store.put(task)
                if task.get("metadata", {}).get("resultRejected") or _terminal_task(task):
                    return {"task": task}
            if self.authorization_check is not None:
                try:
                    authorized = self.authorization_check()
                except (PermissionError, ValueError):
                    authorized = False
                if not authorized:
                    task = task or self._response(task_id, context_id, "TASK_STATE_AUTH_REQUIRED", trace_id, {}, message_id=message_id, session_id=session_id)["task"]
                    return remember({"task": _interrupted_task(task, "auth-required", "Current authorization or approval is required; no completion claimed.")})
            return None

        protocol = {
            "source_protocol": "a2a",
            "source_endpoint": self.source_endpoint,
            "provider": "external-a2a",
        }
        try:
            intent = self.compiler.compile(text)
            if revision_bound:
                intent = intent.model_copy(update={"intent_id": binding["intentId"], "intent_revision": binding["intentRevision"]}, deep=True)
            binding.update(intentId=intent.intent_id, intentRevision=intent.intent_revision)
            submitted = remember(self._response(task_id, context_id, "TASK_STATE_SUBMITTED", trace_id, {}, message_id=message_id, session_id=session_id))
            if _on_event is not None:
                _on_event({"type": "task.status", "terminal": _terminal_task(submitted["task"]), "task": submitted["task"]})
            stopped = checkpoint()
            if stopped:
                return stopped
            self.bus.emit(
                "intent.received",
                trace_id=trace_id,
                intent_id=intent.intent_id,
                payload={"protocol": protocol},
            )
            self.bus.emit(
                "intent.compiled", trace_id=trace_id, intent_id=intent.intent_id
            )
            candidates = self.retriever.retrieve(intent, k=1)
            if not candidates:
                raise LookupError("no Elastic capability matched the A2A request")
            capability_id = candidates[0].capability_id
            capability = self.capability_by_id(capability_id)
            if capability is None:
                raise LookupError(f"selected capability is not registered: {capability_id}")
            protocol["selected_capability"] = capability_id
            protocol["provider"] = capability.provider
            self.bus.emit(
                "capability.selected",
                trace_id=trace_id,
                intent_id=intent.intent_id,
                payload={"capability_id": capability_id, "protocol": protocol},
            )
            args: Dict[str, Any] = dict(intent.constraints)
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("data"), dict):
                    args.update(part["data"])
            metadata = message.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("arguments"), dict):
                args.update(metadata["arguments"])
            recipe = Recipe(
                recipe_id=f"a2a-{task_id}",
                intent_family=intent.goal,
                version="1.0.0",
                steps=[
                    RecipeStep(
                        step_id="execute",
                        action=intent.action,
                        capability_id=capability_id,
                        args=args,
                    )
                ],
                success_conditions=intent.success_conditions,
            )
            stopped = checkpoint()
            if stopped:
                return stopped
            working = remember(self._response(task_id, context_id, "TASK_STATE_WORKING", trace_id, {}, message_id=message_id, session_id=session_id))
            if working["task"].get("metadata", {}).get("resultRejected") or _terminal_task(working["task"]):
                return working
            interruption = {}

            def guarded_executor(capability_id, arguments):
                stopped = checkpoint()
                if stopped:
                    interruption["response"] = stopped
                    raise PermissionError("Execution interrupted before dispatch")
                try:
                    return self.executor(capability_id, arguments)
                except PermissionError:
                    interruption["response"] = remember({"task": _interrupted_task(working["task"], "auth-required", "Current authorization or approval is required; no completion claimed.")})
                    raise
                except (ConnectionError, TimeoutError):
                    uncertain = _interrupted_task(working["task"], "failed", "Provider connection interrupted; execution outcome is unknown. Reconcile before retrying.")
                    uncertain["metadata"]["executionMayHaveOccurred"] = True
                    interruption["response"] = remember({"task": uncertain})
                    raise

            execution = self.runner.run(
                recipe,
                executor=guarded_executor,
                trace_id=trace_id,
                intent_id=intent.intent_id,
                raise_on_error=False,
            )
            if interruption:
                return interruption["response"]
            stopped = checkpoint()
            if stopped:
                return stopped
            if not execution.success:
                return remember(self._response(
                    task_id,
                    context_id,
                    "TASK_STATE_FAILED",
                    trace_id,
                    {"error": execution.error},
                    message_id=message_id,
                    session_id=session_id,
                ))
            assurance = self._assess_execution(
                outcome_id=uuid.uuid4().hex,
                execution_id=trace_id,
                capability_id=capability.id,
                protocol=protocol,
                intent=intent,
                recipe=recipe,
            )
            stopped = checkpoint()
            if stopped:
                return stopped
            response = remember(self._response(
                task_id,
                context_id,
                "TASK_STATE_COMPLETED"
                if assurance["outcome_status"] == OutcomeStatus.COMPLETED.value
                else "TASK_STATE_WORKING",
                trace_id,
                execution.results,
                intent_id=intent.intent_id,
                outcome_id=assurance["outcome_id"],
                evidence_id=assurance["evidence_id"],
                verification_id=assurance["verification_id"],
                outcome_status=assurance["outcome_status"],
                verification_status=assurance["verification_status"],
                completion_authoritative=assurance["completion_authoritative"],
                message_id=message_id,
                session_id=session_id,
            ))

            if response["task"].get("metadata", {}).get("resultRejected"):
                return response
            self.bus.emit(
                "evaluation.completed",
                trace_id=trace_id,
                intent_id=intent.intent_id,
                task_id=task_id,
                context_id=context_id,
                outcome_id=assurance["outcome_id"],
                evidence_id=assurance["evidence_id"],
                verification_id=assurance["verification_id"],
                payload={
                    "protocol": {**protocol, "execution_outcome": "executed_not_verified"},
                    **assurance,
                },
            )
            return response

        except Exception as exc:
            self.bus.emit(
                "execution.failed",
                trace_id=trace_id,
                payload={
                    "error": f"{type(exc).__name__}: {exc}",
                    "protocol": {**protocol, "execution_outcome": "failed"},
                    "evidence_id": trace_id,
                },
            )
            return remember(self._response(
                task_id,
                context_id,
                "TASK_STATE_FAILED",
                trace_id,
                {"error": str(exc)},
                message_id=message_id,
                session_id=session_id,
            ))

    def stream(
        self,
        request: Dict[str, Any],
        *,
        push_config: Optional[Dict[str, Any]] = None,
    ) -> list[Dict[str, Any]]:
        """Return ordered local task events; remote push callbacks are unsupported."""
        if push_config is not None:
            raise NotImplementedError("A2A push notification configuration is unsupported")
        events: list[Dict[str, Any]] = []
        response = self.handle(request, _on_event=events.append)
        events.append({"type": "task.status", "terminal": _terminal_task(response["task"]), "task": response["task"]})
        return events

    def _assess_execution(
        self,
        *,
        outcome_id: str,
        execution_id: str,
        capability_id: str,
        protocol: Dict[str, Any],
        intent: Any,
        recipe: Recipe,
    ) -> Dict[str, Any]:
        """Assess local execution without treating it as provider proof."""

        now = datetime.now(timezone.utc)
        outcome = OutcomeEnvelope(
            outcome_id=outcome_id,
            principal_id="a2a-request",
            originating_agent_id="elastic-a2a-inbound",
            intent={"goal": intent.goal, "action": intent.action, "protocol": "a2a"},
            desired_state={"execution": "successful"},
            required_capabilities=[capability_id],
            execution_plan_reference=recipe.recipe_id,
            verification_policy={"required": True, "policy_reference": "a2a-local-execution-v1"},
            completion_criteria=["capability execution completed"],
            evidence_collection_policy={"accepted_types": ["provider_receipt", "attestation"]},
            recovery_policy={"allow_recovery": False},
            created_at=now,
            updated_at=now,
        )
        for next_status in (
            OutcomeStatus.VALIDATING,
            OutcomeStatus.AUTHORIZED,
            OutcomeStatus.PLANNING,
            OutcomeStatus.EXECUTING,
            OutcomeStatus.VERIFYING,
        ):
            outcome = transition_outcome(outcome, next_status)

        evidence_id = f"execution-event-{execution_id}"
        evidence = EvidenceRecord(
            evidence_id=evidence_id,
            tenant_id="unresolved",
            outcome_id=outcome_id,
            execution_id=execution_id,
            evidence_type="execution_event",
            claim=f"Local A2A recipe runner returned successfully for capability {capability_id}",
            subject=capability_id,
            issuer="elastic-a2a-inbound",
            source="local-recipe-runner",
            producer="elastic-a2a-inbound",
            observed_at=now,
            received_at=now,
            artifact_reference=f"trace:{execution_id}",
            protocol_origin=str(protocol["source_protocol"]),
            verification_status="PENDING",
            privacy_classification="internal",
            retention_policy="runtime-default",
        )
        verification = self.verification_engine.verify(
            [evidence],
            VerificationContext(
                outcome_id=outcome_id,
                execution_id=execution_id,
                policy_reference="a2a-local-execution-v1",
                verifier_id="elastic-a2a-inbound",
                required_evidence_ids=[evidence_id],
            ),
            verification_id=f"verification-{execution_id}",
        )
        outcome_status = evaluate_outcome(outcome, [verification])
        if outcome_status is OutcomeStatus.COMPLETED:
            outcome = transition_outcome(outcome, outcome_status, sufficient_evidence=True)
        else:
            outcome = transition_outcome(outcome, outcome_status)
        return {
            "outcome_id": outcome.outcome_id,
            "intent_id": intent.intent_id,
            "trace_id": execution_id,
            "evidence_id": evidence.evidence_id,
            "verification_id": verification.verification_id,
            "outcome_status": outcome.current_status.value,
            "verification_status": verification.status.value,
            "completion_authoritative": outcome.current_status is OutcomeStatus.COMPLETED,
        }

    @staticmethod
    def _response(
        task_id: str,
        context_id: str,
        state: str,
        trace_id: str,
        result: Any,
        *,
        intent_id: Optional[str] = None,
        outcome_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
        verification_id: Optional[str] = None,
        outcome_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        completion_authoritative: Optional[bool] = None,
        message_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata = {
            "taskId": task_id,
            "contextId": context_id,
            "traceId": trace_id,
            "evidenceId": evidence_id or trace_id,
            "completionAuthoritative": False,
        }
        if message_id is not None:
            metadata["messageId"] = message_id
        if session_id is not None:
            metadata["sessionId"] = session_id
        if intent_id is not None:
            metadata["intentId"] = intent_id
        if outcome_id is not None:
            metadata.update(
                {
                    "outcomeId": outcome_id,
                    "verificationId": verification_id,
                    "outcomeStatus": outcome_status,
                    "verificationStatus": verification_status,
                    "completionAuthoritative": completion_authoritative,
                }
            )
        if state == "TASK_STATE_FAILED":
            text = "The request could not be completed."
        elif state == "TASK_STATE_COMPLETED" and completion_authoritative:
            text = "Your request completed successfully."
        elif state == "TASK_STATE_COMPLETED":
            text = "The request executed, but verification is incomplete."
        elif outcome_status == OutcomeStatus.PARTIALLY_COMPLETED.value:
            text = "The request executed, but verification is incomplete."
        else:
            text = "Your request is being processed."
        return {
            "task": {
                "id": task_id,
                "contextId": context_id,
                "status": {"state": state},
                "artifacts": [
                    {
                        "artifactId": f"result-{task_id}",
                        "name": "Elastic result",
                        "parts": [
                            {"text": text},
                            {"data": result, "mediaType": "application/json"},
                        ],
                    }
                ],
                "metadata": metadata,
            }
        }


class A2AClient:
    """Isolated outbound adapter for delegating to an A2A HTTP+JSON agent."""

    def __init__(
        self,
        endpoint: str,
        *,
        trusted: bool = False,
        headers: Optional[Dict[str, str]] = None,
        transport: Optional[Callable[[str, Dict[str, Any], Dict[str, str]], Dict[str, Any]]] = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("A2A endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("A2A endpoint cannot contain credentials or a fragment")
        if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
            raise ValueError("A2A endpoint must use HTTPS (localhost may use HTTP)")
        self.endpoint = endpoint.rstrip("/")
        self.trusted = trusted
        self.headers = dict(headers or {})
        self._transport = transport or self._http_transport

    def send(self, text: str, *, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.trusted:
            raise PermissionError("A2A server is not trusted")
        parts = [{"text": text}]
        if data:
            parts.append({"data": data, "mediaType": "application/json"})
        return self._transport(
            self.endpoint,
            {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": uuid.uuid4().hex,
                        "role": "user",
                        "parts": parts,
                    }
                },
            },
            self.headers,
        )

    def stream(
        self,
        text: str,
        *,
        data: Optional[Dict[str, Any]] = None,
        push_config: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Request a local stream; unauthenticated or callback push is rejected."""
        if not self.trusted:
            raise PermissionError("A2A server is not trusted")
        if push_config is not None:
            raise NotImplementedError("A2A push notification configuration is unsupported")
        parts = [{"text": text}]
        if data:
            parts.append({"data": data, "mediaType": "application/json"})
        result = self._transport(
            self.endpoint,
            {
                "jsonrpc": "2.0",
                "id": uuid.uuid4().hex,
                "method": "message/stream",
                "params": {
                    "message": {
                        "messageId": uuid.uuid4().hex,
                        "role": "user",
                        "parts": parts,
                    }
                },
            },
            self.headers,
        )
        if not isinstance(result, list):
            raise RuntimeError("A2A stream transport must return an event list")
        return iter(result)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        if not self.trusted:
            raise PermissionError("A2A server is not trusted")
        return self._transport(
            self.endpoint,
            {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tasks/get", "params": {"id": task_id}},
            self.headers,
        )

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        if not self.trusted:
            raise PermissionError("A2A server is not trusted")
        return self._transport(
            self.endpoint,
            {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tasks/cancel", "params": {"id": task_id}},
            self.headers,
        )

    @staticmethod
    def _http_transport(
        url: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "A2A-Version": "1.0",
                **headers,
            },
            method="POST",
        )
        started = time.perf_counter()
        with urllib.request.build_opener(_NoRedirects()).open(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        result.setdefault("_elastic", {})["latencyMs"] = (
            time.perf_counter() - started
        ) * 1000.0
        return result


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"A2A redirect refused: {newurl}")
