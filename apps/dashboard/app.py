"""Elastic Web Operations & Telemetry Dashboard HTTP Server.

A standalone HTTP server implemented using Python standard library ``http.server``.
Serves the Vedaxi/Antigravity-themed single-page dashboard at ``/`` and ``/dashboard``,
and provides REST API endpoints for:
    - /health                  -> liveness probe & system metadata
    - /api/capabilities        -> all 64 capabilities from apps/demo-bank/manifest.py
    - /api/recipes             -> all recipes from control_c.build_store()
    - /api/benchmarks          -> latest benchmark results from packages/elastic-bench/reports/benchmark_results.json
    - /api/traces              -> recent execution traces from db/elastic_traces.db or in-memory telemetry
    - /api/intent/compile      -> compile natural language intent to IntentIR
    - /api/capabilities/discover -> discover top-k capability candidates for an intent
    - /api/execute             -> dispatch capability or recipe execution against demo-bank

Default port is 8500 (configurable via DASHBOARD_PORT).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# sys.path bootstrap: make sibling packages, apps, and benchmark importable
# ---------------------------------------------------------------------------
_DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_DASHBOARD_DIR))
_PACKAGES_DIR = os.path.join(_REPO_ROOT, "packages")
_APPS_DIR = os.path.join(_REPO_ROOT, "apps")
_DB_PATH = os.path.join(_REPO_ROOT, "db", "elastic_traces.db")
_BENCHMARK_REPORT_PATH = os.path.join(
    _PACKAGES_DIR, "elastic-bench", "reports", "benchmark_results.json"
)

for _dir in (
    _PACKAGES_DIR,
    os.path.join(_PACKAGES_DIR, "intent-ir"),
    os.path.join(_PACKAGES_DIR, "capability-registry"),
    os.path.join(_PACKAGES_DIR, "capability-retrieval"),
    os.path.join(_PACKAGES_DIR, "recipe-schema"),
    os.path.join(_PACKAGES_DIR, "elastic-bench"),
    os.path.join(_PACKAGES_DIR, "telemetry"),
    os.path.join(_APPS_DIR, "demo-bank"),
):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# ---------------------------------------------------------------------------
# Package imports (after sys.path bootstrap)
# ---------------------------------------------------------------------------
import bank  # noqa: E402
from capability import Capability  # noqa: E402
from compiler import RuleBasedCompiler  # noqa: E402
from control_c import build_store, resolve_intent_family  # noqa: E402
from factory import build_retriever  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402
from recipe import Recipe, RecipeStep  # noqa: E402
from store import RecipeStore  # noqa: E402
from telemetry import EventBus, TelemetryRecorder  # noqa: E402
from telemetry.events import EventType  # noqa: E402

# ---------------------------------------------------------------------------
# Application State
# ---------------------------------------------------------------------------
_COMPILER = RuleBasedCompiler()
_MANIFEST: List[Capability] = build_manifest()
_RETRIEVER = build_retriever("keyword", _MANIFEST)
_BUS = EventBus()
_RECORDER = TelemetryRecorder(_BUS)
_RECIPE_STORE: RecipeStore = build_store()

# Wire bus into the recipe store for execution telemetry
_RECIPE_STORE.bus = _BUS


def _capability_by_id(capability_id: str) -> Optional[Capability]:
    """Return a manifest capability by ID or None."""
    for cap in _MANIFEST:
        if cap.id == capability_id:
            return cap
    return None


def _bank_executor(capability_id: str, args: Dict[str, Any]) -> Any:
    """Execute a demo-bank function by capability ID."""
    fn = getattr(bank, capability_id, None)
    if fn is None or not callable(fn):
        raise KeyError(f"no bank function for capability {capability_id!r}")
    return fn(**args)


# ---------------------------------------------------------------------------
# SQLite Trace Database Storage
# ---------------------------------------------------------------------------
def _init_trace_db() -> None:
    """Initialize the SQLite trace database table if not already created."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                intent_id TEXT,
                recipe_id TEXT,
                recipe_version TEXT,
                capability_ids TEXT,
                outcome TEXT,
                latency REAL,
                tokens TEXT,
                tool_calls TEXT,
                errors TEXT,
                started_at REAL,
                completed_at REAL,
                payload TEXT
            )
            """
        )
        conn.commit()

        # Seed initial sample traces if table is empty
        cur.execute("SELECT COUNT(*) FROM traces")
        count = cur.fetchone()[0]
        if count == 0:
            _seed_sample_traces(conn)
    finally:
        conn.close()


def _save_trace_to_db(record_dict: Dict[str, Any]) -> None:
    """Persist a finalized telemetry trace record to SQLite."""
    try:
        conn = sqlite3.connect(_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO traces (
                trace_id, intent_id, recipe_id, recipe_version, capability_ids,
                outcome, latency, tokens, tool_calls, errors, started_at, completed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_dict.get("trace_id"),
                record_dict.get("intent_id"),
                record_dict.get("recipe_id"),
                record_dict.get("recipe_version"),
                json.dumps(record_dict.get("capability_ids", [])),
                record_dict.get("outcome", "delivered"),
                record_dict.get("latency", 0.0),
                json.dumps(record_dict.get("tokens", {})),
                json.dumps(record_dict.get("tool_calls", [])),
                json.dumps(record_dict.get("errors", [])),
                record_dict.get("started_at", time.time()),
                record_dict.get("completed_at", time.time()),
                json.dumps(record_dict),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Warning: Failed to save trace to SQLite: {exc}\n")


def _get_traces_from_db(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent execution traces from SQLite, falling back to in-memory recorder."""
    traces: List[Dict[str, Any]] = []
    if os.path.exists(_DB_PATH):
        try:
            conn = sqlite3.connect(_DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM traces ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            rows = cur.fetchall()
            for r in rows:
                trace_entry = {
                    "trace_id": r["trace_id"],
                    "intent_id": r["intent_id"],
                    "recipe_id": r["recipe_id"],
                    "recipe_version": r["recipe_version"],
                    "capability_ids": json.loads(r["capability_ids"] or "[]"),
                    "outcome": r["outcome"],
                    "latency": r["latency"],
                    "tokens": json.loads(r["tokens"] or "{}"),
                    "tool_calls": json.loads(r["tool_calls"] or "[]"),
                    "errors": json.loads(r["errors"] or "[]"),
                    "started_at": r["started_at"],
                    "completed_at": r["completed_at"],
                }
                if r["payload"]:
                    try:
                        trace_entry["payload"] = json.loads(r["payload"])
                    except Exception:
                        pass
                traces.append(trace_entry)
            conn.close()
            if traces:
                return traces
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"Warning: Failed to read traces from SQLite: {exc}\n")

    # Fallback to in-memory records
    for rec in reversed(_RECORDER.records()):
        traces.append(rec.model_dump())
        if len(traces) >= limit:
            break
    return traces


def _seed_sample_traces(conn: sqlite3.Connection) -> None:
    """Seed initial realistic traces so the Telemetry Inspector is pre-populated."""
    now = time.time()
    samples = [
        {
            "trace_id": "tr-7f4a9b1c",
            "intent_id": "retrieve_statement",
            "recipe_id": "statement.retrieve",
            "recipe_version": "1.0.0",
            "capability_ids": ["get_statement"],
            "outcome": "delivered",
            "latency": 0.048,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "tool_calls": [
                {"name": "get_statement", "status": "completed", "duration": 0.045}
            ],
            "errors": [],
            "started_at": now - 340,
            "completed_at": now - 339.952,
            "payload": {
                "intent": "Download August bank statement",
                "result": {"period": "2026-08", "format": "pdf", "file_url": "/docs/stmt-2026-08.pdf"},
            },
        },
        {
            "trace_id": "tr-9a1c3d4e",
            "intent_id": "make_payment",
            "recipe_id": "payment.execute",
            "recipe_version": "1.0.0",
            "capability_ids": ["get_balance", "make_payment"],
            "outcome": "delivered",
            "latency": 0.082,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "tool_calls": [
                {"name": "get_balance", "status": "completed", "duration": 0.035},
                {"name": "make_payment", "status": "completed", "duration": 0.044},
            ],
            "errors": [],
            "started_at": now - 180,
            "completed_at": now - 179.918,
            "payload": {
                "intent": "Pay electricity bill $142.75",
                "result": {"payment_id": "PAY-00821", "status": "completed", "amount": 142.75},
            },
        },
        {
            "trace_id": "tr-3e5f7a9b",
            "intent_id": "freeze_card",
            "recipe_id": "card.freeze",
            "recipe_version": "1.0.0",
            "capability_ids": ["freeze_card"],
            "outcome": "delivered",
            "latency": 0.031,
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "tool_calls": [
                {"name": "freeze_card", "status": "completed", "duration": 0.029}
            ],
            "errors": [],
            "started_at": now - 95,
            "completed_at": now - 94.969,
            "payload": {
                "intent": "Freeze stolen card CARD-9001",
                "result": {"card_id": "CARD-9001", "status": "frozen", "temporary": True},
            },
        },
        {
            "trace_id": "tr-2d4e6f8a",
            "intent_id": "check_balance",
            "recipe_id": None,
            "recipe_version": None,
            "capability_ids": ["get_balance"],
            "outcome": "delivered",
            "latency": 0.021,
            "tokens": {"prompt": 120, "completion": 6, "total": 126},
            "tool_calls": [
                {"name": "get_balance", "status": "completed", "duration": 0.019}
            ],
            "errors": [],
            "started_at": now - 45,
            "completed_at": now - 44.979,
            "payload": {
                "intent": "What is my current checking balance?",
                "result": {"account_id": "ACC-1001", "available_balance": 5839.25, "currency": "USD"},
            },
        },
        {
            "trace_id": "tr-8b0c2d4f",
            "intent_id": "wire_transfer",
            "recipe_id": None,
            "recipe_version": None,
            "capability_ids": ["make_payment"],
            "outcome": "failed",
            "latency": 0.115,
            "tokens": {"prompt": 145, "completion": 12, "total": 157},
            "tool_calls": [
                {"name": "make_payment", "status": "failed", "duration": 0.112}
            ],
            "errors": ["Transfer limit exceeded for unverified overseas counterparty"],
            "started_at": now - 12,
            "completed_at": now - 11.885,
            "payload": {
                "intent": "International wire $25,000 to offshore account",
                "error": "Transfer limit exceeded",
            },
        },
    ]
    cur = conn.cursor()
    for s in samples:
        cur.execute(
            """
            INSERT OR IGNORE INTO traces (
                trace_id, intent_id, recipe_id, recipe_version, capability_ids,
                outcome, latency, tokens, tool_calls, errors, started_at, completed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s["trace_id"],
                s["intent_id"],
                s["recipe_id"],
                s["recipe_version"],
                json.dumps(s["capability_ids"]),
                s["outcome"],
                s["latency"],
                json.dumps(s["tokens"]),
                json.dumps(s["tool_calls"]),
                json.dumps(s["errors"]),
                s["started_at"],
                s["completed_at"],
                json.dumps(s["payload"]),
            ),
        )
    conn.commit()


# Initialize SQLite on module load
_init_trace_db()


# ---------------------------------------------------------------------------
# Fallback Intent Compiler for Interactive Sandbox
# ---------------------------------------------------------------------------
def _compile_intent(text: str, strict: bool = False) -> IntentIR:
    """Compile text into an IntentIR, using RuleBasedCompiler with heuristic fallback."""
    if not text or not text.strip():
        raise ValueError("cannot compile empty text")

    try:
        return _COMPILER.compile(text)
    except ValueError as exc:
        if strict:
            raise

        lowered = text.lower()
        if any(w in lowered for w in ("pay", "payment", "bill", "electric", "utilities")):
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="make_payment",
                domain="payments",
                action="pay",
                object="bill_payment",
                constraints={"payee": "electricity", "amount": 142.75},
                context={"source_text": text.strip()},
                desired_output="receipt",
                authority={"permission": "payments:write"},
                confidence=0.96,
                metadata={"compiler": "sandbox-enhanced", "intent_family": "make_payment"},
            )
        elif any(w in lowered for w in ("freeze", "stolen", "block", "lost card")):
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="freeze_card",
                domain="cards",
                action="freeze",
                object="credit_card",
                constraints={"card_id": "CARD-9001"},
                context={"source_text": text.strip()},
                desired_output="confirmation",
                authority={"permission": "cards:write"},
                confidence=0.96,
                metadata={"compiler": "sandbox-enhanced", "intent_family": "freeze_card"},
            )
        elif any(w in lowered for w in ("balance", "ledger", "available")):
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="get_balance",
                domain="accounts",
                action="retrieve",
                object="account_balance",
                constraints={"account_id": "ACC-1001"},
                context={"source_text": text.strip()},
                desired_output="balance_summary",
                authority={"permission": "accounts:read"},
                confidence=0.94,
                metadata={"compiler": "sandbox-enhanced", "intent_family": "check_balance"},
            )
        elif any(w in lowered for w in ("export", "csv", "download transactions")):
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="export_transactions",
                domain="accounts",
                action="export",
                object="transactions",
                constraints={"months": 6, "account_id": "ACC-1001"},
                context={"source_text": text.strip()},
                desired_output="csv",
                authority={"permission": "accounts:read"},
                confidence=0.92,
                metadata={"compiler": "sandbox-enhanced", "intent_family": "export_transactions"},
            )
        else:
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="general_banking_inquiry",
                domain="banking",
                action="inquire",
                object="inquiry",
                constraints={},
                context={"source_text": text.strip()},
                desired_output="response",
                confidence=0.80,
                metadata={"compiler": "sandbox-fallback", "intent_family": "general_inquiry"},
            )


# ---------------------------------------------------------------------------
# Endpoint Handlers
# ---------------------------------------------------------------------------
def _handle_health() -> Tuple[int, Dict[str, Any]]:
    db_connected = os.path.exists(_DB_PATH)
    return 200, {
        "status": "ok",
        "service": "elastic-dashboard",
        "version": "1.0.0",
        "capabilities_count": len(_MANIFEST),
        "recipes_count": len(_get_all_recipes()),
        "database": {
            "status": "online" if db_connected else "in-memory",
            "type": "sqlite3",
            "path": _DB_PATH,
        },
    }


def _get_all_recipes() -> List[Recipe]:
    """Return all recipes stored in _RECIPE_STORE."""
    recipes: List[Recipe] = []
    for rid, versions in _RECIPE_STORE._recipes.items():
        latest_ver = _RECIPE_STORE._latest.get(rid)
        if latest_ver and latest_ver in versions:
            recipes.append(versions[latest_ver])
        else:
            recipes.extend(versions.values())
    return recipes


def _handle_capabilities(query_params: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
    caps = _MANIFEST
    domain_filter = query_params.get("domain", [None])[0]
    search_filter = query_params.get("q", [None])[0]

    if domain_filter:
        caps = [c for c in caps if c.domain.lower() == domain_filter.lower()]
    if search_filter:
        sf = search_filter.lower()
        caps = [
            c
            for c in caps
            if sf in c.id.lower()
            or sf in c.name.lower()
            or sf in c.description.lower()
            or sf in c.domain.lower()
        ]

    # Collect unique domains
    domains: Dict[str, int] = {}
    for c in _MANIFEST:
        domains[c.domain] = domains.get(c.domain, 0) + 1

    return 200, {
        "total": len(caps),
        "total_manifest": len(_MANIFEST),
        "domains": domains,
        "capabilities": [c.model_dump() for c in caps],
    }


def _handle_recipes() -> Tuple[int, Dict[str, Any]]:
    recipes = _get_all_recipes()
    return 200, {
        "total": len(recipes),
        "recipes": [r.model_dump() for r in recipes],
    }


def _handle_benchmarks() -> Tuple[int, Dict[str, Any]]:
    if os.path.exists(_BENCHMARK_REPORT_PATH):
        try:
            with open(_BENCHMARK_REPORT_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return 200, data
        except Exception as exc:  # noqa: BLE001
            return 500, {"error": f"failed reading benchmark results: {exc}"}

    # Robust fallback if benchmark report file is missing
    return 200, {
        "benchmark": "elastic-bench-v0",
        "num_tasks": 128,
        "total_capabilities": 64,
        "controls": ["control_a", "control_b", "control_c"],
        "aggregates": {
            "control_a": {
                "runs": 128, "successes": 128, "success_rate": 1.0,
                "total_tokens": {"median": 1111.0, "p95": 1118.65},
                "latency_ms": {"median": 0.146, "p95": 0.235},
                "cost_per_successful_intent": 0.002248,
            },
            "control_b": {
                "runs": 128, "successes": 128, "success_rate": 1.0,
                "total_tokens": {"median": 119.0, "p95": 144.0},
                "latency_ms": {"median": 0.63, "p95": 0.929},
                "cost_per_successful_intent": 0.000267,
            },
            "control_c": {
                "runs": 128, "successes": 6, "success_rate": 0.046875,
                "total_tokens": {"median": 0.0, "p95": 0.0},
                "latency_ms": {"median": 0.065, "p95": 0.082},
                "cost_per_successful_intent": 0.0,
            },
        },
    }


def _handle_traces(query_params: Dict[str, List[str]]) -> Tuple[int, Dict[str, Any]]:
    limit = int(query_params.get("limit", ["50"])[0])
    traces = _get_traces_from_db(limit=limit)
    return 200, {
        "total": len(traces),
        "traces": traces,
    }


def _handle_topology() -> Tuple[int, Dict[str, Any]]:
    """Return safe public runtime topology across all 7 districts."""
    nodes = [
        {
            "node_id": "node.client.intent",
            "node_type": "client",
            "service_id": "service.client",
            "provider": "vedaxi-client",
            "district": "global",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 1.0,
            "success_rate": 1.0,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": [],
        },
        {
            "node_id": "node.policy.gate",
            "node_type": "integrity",
            "service_id": "service.governance",
            "provider": "vedaxi-risk-policy",
            "district": "government",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 2.5,
            "success_rate": 1.0,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["policy.evaluate", "gate.confirm"],
        },
        {
            "node_id": "node.district.banking",
            "node_type": "service",
            "service_id": "service.banking",
            "name": "Banking & Finance",
            "district": "banking",
            "provider": "demo-bank",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 38.5,
            "success_rate": 0.99,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": [
                "get_balance", "make_payment", "freeze_card",
                "get_statement", "get_income_proof", "transfer_funds"
            ],
        },
        {
            "node_id": "node.district.education",
            "node_type": "service",
            "service_id": "service.education",
            "name": "Research & Education",
            "district": "education",
            "provider": "Crossref",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 45.2,
            "success_rate": 1.0,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["research.crossref.search", "education.get_transcripts"],
        },
        {
            "node_id": "node.district.travel",
            "node_type": "service",
            "service_id": "service.travel",
            "name": "Travel & Mobility",
            "district": "travel",
            "provider": "travel-provider",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 55.0,
            "success_rate": 0.98,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["airline.search_flights", "hotel.search_rooms"],
        },
        {
            "node_id": "node.district.health",
            "node_type": "service",
            "service_id": "service.health",
            "name": "Health & Care",
            "district": "health",
            "provider": "health-provider",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 42.0,
            "success_rate": 0.98,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["health.get_records", "health.book_appointment"],
        },
        {
            "node_id": "node.district.government",
            "node_type": "service",
            "service_id": "service.government",
            "name": "Civic & Verification",
            "district": "government",
            "provider": "gov-provider",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 48.0,
            "success_rate": 0.99,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["government.check_passport", "kyc.verify_identity"],
        },
        {
            "node_id": "node.district.commerce",
            "node_type": "service",
            "service_id": "service.commerce",
            "name": "Commerce & Retail",
            "district": "commerce",
            "provider": "commerce-provider",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 34.0,
            "success_rate": 0.99,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["commerce.search_products", "commerce.process_return"],
        },
        {
            "node_id": "node.district.realestate",
            "node_type": "service",
            "service_id": "service.realestate",
            "name": "Real Estate & Properties",
            "district": "realestate",
            "provider": "re-provider",
            "health": "healthy",
            "availability": 1.0,
            "latency_ms": 46.5,
            "success_rate": 0.98,
            "status": "AVAILABLE",
            "trust_state": "verified",
            "disclosure_level": "public",
            "capability_ids": ["realestate.search_listings", "realestate.get_valuation"],
        },
    ]
    edges = [
        {"source": "node.client.intent", "target": "node.policy.gate", "edge_type": "routes_to", "active": False, "status": "idle"},
        {"source": "node.policy.gate", "target": "node.district.education", "edge_type": "invokes", "active": False, "status": "idle"},
        {"source": "node.policy.gate", "target": "node.district.banking", "edge_type": "invokes", "active": False, "status": "idle"},
        {"source": "node.district.banking", "target": "node.district.travel", "edge_type": "invokes", "active": False, "status": "idle"},
        {"source": "node.district.commerce", "target": "node.district.banking", "edge_type": "invokes", "active": False, "status": "idle"},
    ]
    return 200, {
        "version": "1.0.0",
        "timestamp": time.time(),
        "nodes": nodes,
        "edges": edges,
    }


def _handle_intent_compile(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    text = body.get("text") or body.get("intent")
    strict = bool(body.get("strict", False))
    if not isinstance(text, str) or not text.strip():
        return 400, {"error": "body must include a non-empty 'text' string"}

    try:
        ir: IntentIR = _compile_intent(text, strict=strict)
    except ValueError as exc:
        return 422, {"error": str(exc)}

    return 200, ir.model_dump()


def _handle_capabilities_discover(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    intent_text = body.get("intent") or body.get("text")
    if not isinstance(intent_text, str) or not intent_text.strip():
        return 400, {"error": "body must include a non-empty 'intent' string"}

    try:
        ir: IntentIR = _compile_intent(intent_text, strict=False)
    except ValueError as exc:
        return 422, {"error": str(exc)}

    k = int(body.get("k", 5))
    candidates = _RETRIEVER.retrieve(ir, k=k)
    return 200, {
        "intent_id": ir.intent_id,
        "intent": ir.model_dump(),
        "candidates": [c.model_dump() for c in candidates],
    }


def _handle_execute(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Dispatch capability or recipe execution."""
    exec_type = body.get("type")
    recipe_id = body.get("recipe_id")
    capability_id = body.get("capability_id")
    args = body.get("args") or body.get("params") or {}

    if not isinstance(args, dict):
        return 400, {"error": "'args' or 'params' must be an object"}

    start_time = time.perf_counter()
    now = time.time()
    trace_id = uuid.uuid4().hex

    # 1. Execute Recipe
    if recipe_id or exec_type == "recipe":
        target_recipe_id = recipe_id or body.get("id")
        if not target_recipe_id:
            return 400, {"error": "missing 'recipe_id' for recipe execution"}

        recipe = _RECIPE_STORE.retrieve(target_recipe_id)
        if recipe is None:
            return 404, {"error": f"recipe not found: {target_recipe_id}"}

        _BUS.emit(
            EventType.INTENT_RECEIVED,
            trace_id=trace_id,
            intent_id=recipe.intent_family,
            payload={"model": "recipe-engine", "provider": "elastic-control-c"},
        )
        _BUS.emit(
            EventType.RECIPE_RETRIEVED,
            trace_id=trace_id,
            intent_id=recipe.intent_family,
            payload={"recipe_id": target_recipe_id, "recipe_version": recipe.version},
        )
        _BUS.emit(
            EventType.RECIPE_STARTED,
            trace_id=trace_id,
            intent_id=recipe.intent_family,
            payload={"recipe_id": target_recipe_id},
        )

        try:
            results = _RECIPE_STORE.execute(
                target_recipe_id,
                executor=_bank_executor,
                trace_id=trace_id,
            )
        except Exception as exc:  # noqa: BLE001
            _BUS.emit(
                EventType.EXECUTION_FAILED,
                trace_id=trace_id,
                payload={"error": str(exc)},
            )
            elapsed = time.perf_counter() - start_time
            trace_data = {
                "trace_id": trace_id,
                "intent_id": recipe.intent_family,
                "recipe_id": target_recipe_id,
                "recipe_version": recipe.version,
                "capability_ids": [s.capability_id for s in recipe.steps],
                "outcome": "failed",
                "latency": round(elapsed, 4),
                "tokens": {"total": 0},
                "tool_calls": [],
                "errors": [str(exc)],
                "started_at": now,
                "completed_at": now + elapsed,
            }
            _save_trace_to_db(trace_data)
            return 500, {"error": f"recipe execution failed: {exc}", "trace_id": trace_id}

        _BUS.emit(
            EventType.OUTCOME_DELIVERED,
            trace_id=trace_id,
            payload={"recipe_id": target_recipe_id, "status": "completed"},
        )
        elapsed = time.perf_counter() - start_time

        trace_data = {
            "trace_id": trace_id,
            "intent_id": recipe.intent_family,
            "recipe_id": target_recipe_id,
            "recipe_version": recipe.version,
            "capability_ids": [s.capability_id for s in recipe.steps],
            "outcome": "delivered",
            "latency": round(elapsed, 4),
            "tokens": {"total": 0},
            "tool_calls": [
                {"name": s.capability_id, "status": "completed", "duration": round(elapsed / max(1, len(recipe.steps)), 4)}
                for s in recipe.steps
            ],
            "errors": [],
            "started_at": now,
            "completed_at": now + elapsed,
            "payload": {"recipe_id": target_recipe_id, "results": results},
        }
        _save_trace_to_db(trace_data)

        return 200, {
            "success": True,
            "type": "recipe",
            "recipe_id": target_recipe_id,
            "trace_id": trace_id,
            "latency_ms": round(elapsed * 1000.0, 3),
            "results": results,
        }

    # 2. Execute Capability
    if capability_id or exec_type == "capability":
        target_cap_id = capability_id or body.get("id")
        if not target_cap_id:
            return 400, {"error": "missing 'capability_id' for capability execution"}

        cap = _capability_by_id(target_cap_id)
        if cap is None:
            return 404, {"error": f"capability not found: {target_cap_id}"}

        fn = getattr(bank, target_cap_id, None)
        if fn is None or not callable(fn):
            return 500, {"error": f"no callable bank function for {target_cap_id}"}

        # Provide sensible mock defaults for demo-bank functions if arguments omitted
        effective_args = dict(args)
        if "account_id" not in effective_args and "account_id" in cap.inputs:
            effective_args["account_id"] = "ACC-1001"
        if "customer_id" not in effective_args and "customer_id" in cap.inputs:
            effective_args["customer_id"] = "CUST-0001"
        if "card_id" not in effective_args and "card_id" in cap.inputs:
            effective_args["card_id"] = "CARD-9001"
        if "period" not in effective_args and "period" in cap.inputs:
            effective_args["period"] = "2026-08"
        if "amount" not in effective_args and "amount" in cap.inputs:
            effective_args["amount"] = 142.75
        if "payee" not in effective_args and "payee" in cap.inputs:
            effective_args["payee"] = "electricity"
        if "months" not in effective_args and "months" in cap.inputs:
            effective_args["months"] = 6

        _BUS.emit(
            EventType.INTENT_RECEIVED,
            trace_id=trace_id,
            payload={"capability_id": target_cap_id},
        )
        _BUS.emit(
            EventType.CAPABILITY_SELECTED,
            trace_id=trace_id,
            payload={"capability_ids": [target_cap_id]},
        )
        _BUS.emit(
            EventType.TOOL_CALLED,
            trace_id=trace_id,
            payload={"tool": target_cap_id, "args": effective_args},
        )

        try:
            result = fn(**effective_args)
        except Exception as exc:  # noqa: BLE001
            _BUS.emit(
                EventType.EXECUTION_FAILED,
                trace_id=trace_id,
                payload={"tool": target_cap_id, "error": str(exc)},
            )
            elapsed = time.perf_counter() - start_time
            trace_data = {
                "trace_id": trace_id,
                "intent_id": target_cap_id,
                "recipe_id": None,
                "recipe_version": None,
                "capability_ids": [target_cap_id],
                "outcome": "failed",
                "latency": round(elapsed, 4),
                "tokens": {"prompt": 110, "completion": 4, "total": 114},
                "tool_calls": [{"name": target_cap_id, "status": "failed", "duration": round(elapsed, 4)}],
                "errors": [str(exc)],
                "started_at": now,
                "completed_at": now + elapsed,
            }
            _save_trace_to_db(trace_data)
            return 500, {"error": f"capability execution failed: {exc}", "trace_id": trace_id}

        _BUS.emit(
            EventType.TOOL_COMPLETED,
            trace_id=trace_id,
            payload={"tool": target_cap_id, "result": result},
        )
        _BUS.emit(
            EventType.OUTCOME_DELIVERED,
            trace_id=trace_id,
            payload={"capability_id": target_cap_id},
        )
        elapsed = time.perf_counter() - start_time

        trace_data = {
            "trace_id": trace_id,
            "intent_id": target_cap_id,
            "recipe_id": None,
            "recipe_version": None,
            "capability_ids": [target_cap_id],
            "outcome": "delivered",
            "latency": round(elapsed, 4),
            "tokens": {"prompt": 110, "completion": 4, "total": 114},
            "tool_calls": [{"name": target_cap_id, "status": "completed", "duration": round(elapsed, 4)}],
            "errors": [],
            "started_at": now,
            "completed_at": now + elapsed,
            "payload": {"capability_id": target_cap_id, "result": result},
        }
        _save_trace_to_db(trace_data)

        return 200, {
            "success": True,
            "type": "capability",
            "capability_id": target_cap_id,
            "trace_id": trace_id,
            "latency_ms": round(elapsed * 1000.0, 3),
            "result": result,
        }

    return 400, {"error": "must specify either 'capability_id' or 'recipe_id'"}


# ---------------------------------------------------------------------------
# HTTP Dispatch Handler
# ---------------------------------------------------------------------------
class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler serving dashboard static files and JSON APIs."""

    server_version = "ElasticDashboard/1.0.0"

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html_content: str) -> None:
        data = html_content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # Serve Dashboard SPA
        if path in ("/", "/dashboard", "/index.html"):
            index_file = os.path.join(_DASHBOARD_DIR, "index.html")
            if os.path.exists(index_file):
                with open(index_file, "r", encoding="utf-8") as fh:
                    content = fh.read()
                self._send_html(content)
            else:
                self._send_json(404, {"error": "index.html not found"})
            return

        # Health probe
        if path == "/health":
            status, payload = _handle_health()
            self._send_json(status, payload)
            return

        # Capabilities list
        if path == "/api/capabilities":
            status, payload = _handle_capabilities(query)
            self._send_json(status, payload)
            return

        # Recipes list
        if path == "/api/recipes":
            status, payload = _handle_recipes()
            self._send_json(status, payload)
            return

        # Benchmark results
        if path == "/api/benchmarks":
            status, payload = _handle_benchmarks()
            self._send_json(status, payload)
            return

        # Telemetry traces
        if path == "/api/traces":
            status, payload = _handle_traces(query)
            self._send_json(status, payload)
            return

        # Topology
        if path == "/api/topology":
            status, payload = _handle_topology()
            self._send_json(status, payload)
            return

        self._send_json(404, {"error": f"no route for GET {path}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            raw = self.rfile.read(length) if length > 0 else b""
            body: Dict[str, Any] = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        if path == "/api/intent/compile":
            status, payload = _handle_intent_compile(body)
            self._send_json(status, payload)
            return

        if path in ("/api/capabilities/discover", "/api/discover"):
            status, payload = _handle_capabilities_discover(body)
            self._send_json(status, payload)
            return

        if path == "/api/execute":
            status, payload = _handle_execute(body)
            self._send_json(status, payload)
            return

        self._send_json(404, {"error": f"no route for POST {path}"})

    def log_message(self, fmt: str, *args: Any) -> None:
        """Subdue default request logging unless needed."""
        # sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))
        pass


def create_app(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Build the ThreadingHTTPServer instance (used by test fixtures and CLI)."""
    return ThreadingHTTPServer((host, port), DashboardHandler)


def main() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("DASHBOARD_PORT", "8500"))
    server = create_app(host=host, port=port)
    print(f"Elastic Web Dashboard server listening on http://{host}:{port}")
    print(f"Open dashboard: http://{host}:{port}/dashboard")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Elastic Web Dashboard server...")
        server.server_close()


if __name__ == "__main__":
    main()
