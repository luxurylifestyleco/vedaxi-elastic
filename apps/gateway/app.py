"""Elastic Web HTTP API gateway.

A thin HTTP layer over the Elastic Web foundation packages. All business
logic lives in the packages under ``packages/`` and the ``demo-bank`` app;
this module only wires HTTP requests to package functions.

The gateway uses only the Python standard library (``http.server``) so it
runs without any third-party web framework. It exposes eight endpoints:

    POST /intent/compile            compile text -> IntentIR
    POST /capabilities/discover     retrieve capability candidates
    GET  /capabilities/{id}         fetch a capability by id
    POST /capabilities/{id}/execute  invoke a demo-bank function
    POST /recipes/resolve           resolve a recipe by intent family
    POST /recipes/{id}/execute      execute a recipe
    GET  /traces/{id}               fetch a telemetry trace by id
    GET  /health                    liveness probe

Run with::

    python app.py            # serves on 127.0.0.1:8000
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import sqlite3
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# sys.path bootstrap: make sibling packages and the demo-bank app importable.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES_DIR = os.path.join(_REPO_ROOT, "packages")
_APPS_DIR = os.path.join(_REPO_ROOT, "apps")

for _dir in (
    _PACKAGES_DIR,
    os.path.join(_PACKAGES_DIR, "intent-ir"),
    os.path.join(_PACKAGES_DIR, "capability-registry"),
    os.path.join(_PACKAGES_DIR, "capability-projection"),
    os.path.join(_PACKAGES_DIR, "capability-retrieval"),
    os.path.join(_PACKAGES_DIR, "recipe-schema"),
    os.path.join(_PACKAGES_DIR, "recipe-runtime"),
    os.path.join(_PACKAGES_DIR, "assurance-protocol"),
    os.path.join(_APPS_DIR, "demo-bank"),
):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# ---------------------------------------------------------------------------
# Package imports (after sys.path bootstrap).
# ---------------------------------------------------------------------------
import bank  # noqa: E402
from a2a import (  # noqa: E402
    A2AContentTypeNotSupportedError,
    A2AInboundAdapter,
    _terminal_task,
    A2ATaskStore,
    PostgresA2ATaskStore,
    SQLiteA2ATaskStore,
    _canonical_task,
)
from capability import Capability  # noqa: E402
from compiler import RuleBasedCompiler  # noqa: E402
from discovery import (  # noqa: E402
    agent_card,
    agents_json,
    agents_txt,
    ucp_profile,
)
from factory import build_retriever  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402
from recipe import Recipe, RecipeStep  # noqa: E402
from projection import to_mcp_tool, to_ucp_capability  # noqa: E402
from runner import RecipeDAGRunner  # noqa: E402
from store import RecipeStore  # noqa: E402
from telemetry import EventBus, TelemetryRecorder  # noqa: E402
from evaluator import evaluate_outcome  # noqa: E402
from outcome import (  # noqa: E402
    EvidenceRecord,
    OutcomeEnvelope,
    OutcomeStatus,
    transition_outcome,
)
from provider import ProviderExecutorRegistry, UnsupportedProviderError  # noqa: E402
from verification import VerificationContext, VerificationEngine  # noqa: E402
from authorization import authorize_chat_session  # noqa: E402
from execution_context import ChatSession, PrincipalKind  # noqa: E402
from auth import AuthenticatedPrincipal, SupabaseAuthAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Shared application state (wired to the real packages).
# ---------------------------------------------------------------------------
_COMPILER = RuleBasedCompiler()
_MANIFEST: List[Capability] = build_manifest()
_RETRIEVER = build_retriever("keyword", _MANIFEST)
_BUS = EventBus()
_RECORDER = TelemetryRecorder(_BUS)
_RECIPE_STORE = RecipeStore(bus=_BUS)
_RUNNER = RecipeDAGRunner(bus=_BUS)
_VERIFICATION_ENGINE = VerificationEngine()
_CHAT_DB_PATH = os.environ.get("ELASTIC_CHAT_DB_PATH")
_CHAT_POSTGRES_DSN = os.environ.get("ELASTIC_CHAT_POSTGRES_DSN")
_REQUEST_PRINCIPAL: ContextVar[AuthenticatedPrincipal | None] = ContextVar(
    "elastic_request_principal", default=None
)
_A2A_TCK_FIXTURE_ENV = "ELASTIC_A2A_TCK_FIXTURE"
_A2A_TASKS = (
    PostgresA2ATaskStore(_CHAT_POSTGRES_DSN)
    if _CHAT_POSTGRES_DSN
    else SQLiteA2ATaskStore(_CHAT_DB_PATH) if _CHAT_DB_PATH else A2ATaskStore()
)


class ChatSessionStore:
    """Process-local chat sessions; persistence is a later gated boundary."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ChatSession] = {}
        self._contexts: Dict[str, str] = {}
        self._messages: Dict[str, list[Dict[str, str]]] = {}
        self._lock = RLock()

    def put(self, session: ChatSession, context_id: str) -> None:
        with self._lock:
            self._sessions[session.session_id] = session
            self._contexts[context_id] = session.session_id
            self._messages.setdefault(session.session_id, [])

    def get(self, session_id: str, *, tenant_id: Optional[str] = None) -> Optional[ChatSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def context_owner(self, context_id: str, *, tenant_id: Optional[str] = None) -> Optional[str]:
        with self._lock:
            return self._contexts.get(context_id)

    def revoke(self, session_id: str, when: datetime, *, tenant_id: Optional[str] = None) -> Optional[ChatSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            revoked = session.model_copy(update={"revoked_at": when})
            self._sessions[session_id] = revoked
            return revoked

    def add_message(self, session_id: str, message_id: str, task_id: str, *, tenant_id: Optional[str] = None) -> None:
        with self._lock:
            self._messages.setdefault(session_id, []).append(
                {"messageId": message_id, "taskId": task_id}
            )

    def link_task(self, message_id: str, task_id: str, *, tenant_id: Optional[str] = None) -> None:
        return None


class SQLiteChatSessionStore(ChatSessionStore):
    """Opt-in restart-safe session store sharing the durable chat database."""

    def __init__(self, path: str) -> None:
        self._lock = RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions_local (
                    session_id TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]'
                )
                """
            )

    def put(self, session: ChatSession, context_id: str) -> None:
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT messages FROM chat_sessions_local WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
            messages = existing["messages"] if existing else "[]"
            self._conn.execute(
                """
                INSERT INTO chat_sessions_local(session_id, context_id, payload, messages)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    context_id = excluded.context_id,
                    payload = excluded.payload
                """,
                (session.session_id, context_id, json.dumps(session.model_dump(mode="json")), messages),
            )

    def get(self, session_id: str, *, tenant_id: Optional[str] = None) -> Optional[ChatSession]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM chat_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return ChatSession.model_validate(json.loads(row["payload"])) if row else None

    def context_owner(self, context_id: str, *, tenant_id: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id FROM chat_sessions_local WHERE context_id = ?",
                (context_id,),
            ).fetchone()
            return str(row["session_id"]) if row else None

    def revoke(self, session_id: str, when: datetime, *, tenant_id: Optional[str] = None) -> Optional[ChatSession]:
        session = self.get(session_id)
        if session is None:
            return None
        revoked = session.model_copy(update={"revoked_at": when})
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE chat_sessions_local SET payload = ? WHERE session_id = ?",
                (json.dumps(revoked.model_dump(mode="json")), session_id),
            )
        return revoked

    def add_message(self, session_id: str, message_id: str, task_id: str, *, tenant_id: Optional[str] = None) -> None:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT messages FROM chat_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return
            messages = json.loads(row["messages"])
            messages.append({"messageId": message_id, "taskId": task_id})
            self._conn.execute(
                "UPDATE chat_sessions_local SET messages = ? WHERE session_id = ?",
                (json.dumps(messages), session_id),
            )

    def link_task(self, message_id: str, task_id: str, *, tenant_id: Optional[str] = None) -> None:
        return None


class PostgresChatSessionStore(ChatSessionStore):
    """DSN-gated store for ``chat_sessions`` and ``conversation_messages``."""

    def __init__(self, dsn: str, connection_factory: Optional[Callable[[str], Any]] = None) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("Postgres session store requires ELASTIC_CHAT_POSTGRES_DSN")
        self._dsn = dsn
        self._connect = connection_factory or self._default_connect
        self._lock = RLock()

    @staticmethod
    def _default_connect(dsn: str) -> Any:
        import psycopg2
        return psycopg2.connect(dsn)

    @staticmethod
    def _require_tenant_id(tenant_id: Optional[str]) -> str:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Postgres chat access requires tenant_id")
        return tenant_id

    def _query(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        *,
        tenant_id: Optional[str],
        fetchone: bool = False,
    ) -> Any:
        tenant_id = self._require_tenant_id(tenant_id)
        conn = self._connect(self._dsn)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cursor.execute(sql, params)
                result = cursor.fetchone() if fetchone else None
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def put(self, session: ChatSession, context_id: str) -> None:
        with self._lock:
            self._query(
                """INSERT INTO public.chat_sessions
                (session_id, tenant_id, principal_id, principal_kind, consent_id, scopes,
                 authenticated_at, consented_scopes, policy_epoch, authorization_decision_id,
                 context_id, issued_at, expires_at, revoked_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO NOTHING""",
                (session.session_id, session.tenant_id, session.principal_id,
                 session.principal_kind.value, session.consent_id,
                 json.dumps(list(session.scopes)), session.authenticated_at,
                 json.dumps(list(session.consented_scopes)), session.policy_epoch,
                 session.authorization_decision_id, context_id, session.issued_at,
                 session.expires_at, session.revoked_at),
                tenant_id=session.tenant_id,
            )

    @staticmethod
    def _session(row: Any) -> Optional[ChatSession]:
        if row is None:
            return None
        values = dict(zip(("session_id", "tenant_id", "principal_id", "principal_kind", "consent_id",
                           "scopes", "authenticated_at", "consented_scopes", "policy_epoch",
                           "authorization_decision_id", "context_id", "issued_at", "expires_at", "revoked_at"), row))
        return ChatSession(
            session_id=values["session_id"], tenant_id=values["tenant_id"],
            principal_id=values["principal_id"], principal_kind=PrincipalKind(values["principal_kind"]),
            consent_id=values["consent_id"], scopes=tuple(values["scopes"] or []),
            authenticated_at=values["authenticated_at"], consented_scopes=tuple(values["consented_scopes"] or []),
            policy_epoch=values["policy_epoch"], authorization_decision_id=values["authorization_decision_id"],
            issued_at=values["issued_at"], expires_at=values["expires_at"], revoked_at=values["revoked_at"],
        )

    def get(self, session_id: str, *, tenant_id: Optional[str] = None) -> Optional[ChatSession]:
        with self._lock:
            row = self._query("SELECT session_id, tenant_id, principal_id, principal_kind, consent_id, scopes, authenticated_at, consented_scopes, policy_epoch, authorization_decision_id, context_id, issued_at, expires_at, revoked_at FROM public.chat_sessions WHERE session_id = %s AND tenant_id = %s", (session_id, tenant_id), tenant_id=tenant_id, fetchone=True)
            return self._session(row)

    def context_owner(self, context_id: str, *, tenant_id: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._query("SELECT session_id FROM public.chat_sessions WHERE context_id = %s AND tenant_id = %s", (context_id, tenant_id), tenant_id=tenant_id, fetchone=True)
            return str(row[0]) if row else None

    def revoke(self, session_id: str, when: datetime, *, tenant_id: Optional[str] = None) -> Optional[ChatSession]:
        with self._lock:
            self._query("UPDATE public.chat_sessions SET revoked_at = %s WHERE session_id = %s AND tenant_id = %s AND revoked_at IS NULL", (when, session_id, tenant_id), tenant_id=tenant_id)
            return self.get(session_id, tenant_id=tenant_id)

    def add_message(
        self,
        session_id: str,
        message_id: str,
        task_id: str,
        *,
        tenant_id: Optional[str] = None,
        parts: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        if not message_id:
            return
        with self._lock:
            session = self.get(session_id, tenant_id=tenant_id)
            if session is None:
                return
            row = self._query("SELECT context_id FROM public.chat_sessions WHERE session_id = %s AND tenant_id = %s", (session_id, tenant_id), tenant_id=tenant_id, fetchone=True)
            self._query(
                """INSERT INTO public.conversation_messages
                (message_id, tenant_id, session_id, context_id, principal_id, role, parts, task_id)
                VALUES (%s, %s, %s, %s, %s, 'user', %s::jsonb, %s)
                ON CONFLICT (message_id) DO NOTHING""",
                (message_id, session.tenant_id, session.session_id, row[0], session.principal_id,
                 json.dumps(parts or [{"text": "chat message"}]), None),
                tenant_id=session.tenant_id,
            )

    def link_task(self, message_id: str, task_id: str, *, tenant_id: Optional[str] = None) -> None:
        if not message_id:
            return
        with self._lock:
            self._query(
                "UPDATE public.conversation_messages SET task_id = %s WHERE message_id = %s AND tenant_id = %s AND task_id IS NULL",
                (task_id, message_id, tenant_id),
                tenant_id=tenant_id,
            )


_CHAT_SESSIONS = (
    PostgresChatSessionStore(_CHAT_POSTGRES_DSN)
    if _CHAT_POSTGRES_DSN
    else SQLiteChatSessionStore(_CHAT_DB_PATH) if _CHAT_DB_PATH else ChatSessionStore()
)
_CHAT_DEV_TENANT = os.environ.get("ELASTIC_CHAT_DEV_TENANT", "dev-tenant")
_CHAT_DEV_PRINCIPAL = os.environ.get("ELASTIC_CHAT_DEV_PRINCIPAL", "dev-client")
_CHAT_DEV_PRINCIPAL_KIND = PrincipalKind.HUMAN


def _active_manifest() -> List[Capability]:
    """Return the manifest for the current feature flags.

    Tests and local operators may enable the synthetic UCP catalog after this
    module has been imported. Rebuilding here keeps discovery and execution on
    the same explicitly enabled surface without changing the default manifest.
    """
    if os.environ.get("ENABLE_SYNTHETIC_UCP_CATALOG") == "1":
        return build_manifest()
    return _MANIFEST


def _capability_by_id(capability_id: str) -> Optional[Capability]:
    """Return a manifest capability by id, or ``None``."""
    for cap in _active_manifest():
        if cap.id == capability_id:
            return cap
    return None


def _bank_executor(capability_id: str, args: Dict[str, Any]) -> Any:
    """Execute a demo-bank function by capability id (used by recipes)."""
    fn = getattr(bank, capability_id, None)
    if fn is None or not callable(fn):
        raise KeyError(f"no bank function for capability {capability_id!r}")
    return fn(**args)


_PROVIDER_REGISTRY = ProviderExecutorRegistry()

# The registry is the metadata trust boundary for capability execution.  The
# existing runner remains the demo-bank side-effect boundary; this registration
# makes its supported provider/protocol surface explicit without duplicating a
# bank call or pretending the local runner is provider attestation.
for _capability in _MANIFEST:
    _PROVIDER_REGISTRY.register(
        provider_id=_capability.provider,
        protocol=_capability.protocol,
        capability_id=_capability.id,
        executor=_bank_executor,
    )


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _register_active_capabilities() -> None:
    """Keep the existing registry aligned with the flag-enabled manifest.

    The registry is built once at import. Tests and operators may enable the
    synthetic catalog after import. Register only capabilities the active
    manifest already declares, on the same executor. Do not add a second registry.
    """
    for capability in _active_manifest():
        try:
            _PROVIDER_REGISTRY.select(
                provider_id=capability.provider,
                protocol=capability.protocol,
                capability_id=capability.id,
            )
        except UnsupportedProviderError:
            _PROVIDER_REGISTRY.register(
                provider_id=capability.provider,
                protocol=capability.protocol,
                capability_id=capability.id,
                executor=_bank_executor,
            )


def _execute_through_runtime(
    capability_id: str,
    args: Dict[str, Any],
    *,
    source_protocol: str,
    source_endpoint: str,
    outcome_id: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    capability = _capability_by_id(capability_id)
    if capability is None:
        return 404, {"error": f"capability not found: {capability_id}"}
    _register_active_capabilities()
    try:
        _PROVIDER_REGISTRY.select(
            provider_id=capability.provider,
            protocol=capability.protocol,
            capability_id=capability.id,
        )
    except UnsupportedProviderError:
        return 501, {
            "error": "unsupported provider metadata",
            "capability_id": capability.id,
            "provider": capability.provider,
            "protocol": capability.protocol,
        }
    trace_id = uuid.uuid4().hex
    outcome_id = outcome_id or uuid.uuid4().hex
    protocol = {
        "source_protocol": source_protocol,
        "source_endpoint": source_endpoint,
        "provider": capability.provider,
        "selected_capability": capability.id,
        "outcome_id": outcome_id,
    }
    _BUS.emit(
        "capability.selected",
        trace_id=trace_id,
        payload={"capability_id": capability.id, "protocol": protocol},
    )
    recipe = Recipe(
        recipe_id=f"{source_protocol}-{trace_id}",
        intent_family="direct_capability_execution",
        version="1.0.0",
        steps=[
            RecipeStep(
                step_id="execute",
                action="execute",
                capability_id=capability.id,
                args=args,
            )
        ],
        success_conditions=["capability execution completed"],
    )
    execution = _RUNNER.run(
        recipe,
        executor=_bank_executor,
        trace_id=trace_id,
        raise_on_error=False,
    )
    if not execution.success:
        status = 400 if (execution.error or "").startswith("TypeError:") else 500
        return status, {"error": execution.error, "trace_id": trace_id}

    # A local runner result is an execution event, not provider proof.  Route
    # it through the assurance contracts so this gateway cannot claim
    # COMPLETED merely because its own function returned successfully.
    now = datetime.now(timezone.utc)
    outcome = OutcomeEnvelope(
        outcome_id=outcome_id,
        principal_id="gateway-request",
        originating_agent_id="elastic-web-gateway",
        intent={"capability_id": capability.id, "source_protocol": source_protocol},
        desired_state={"execution": "successful"},
        required_capabilities=[capability.id],
        execution_plan_reference=recipe.recipe_id,
        verification_policy={"required": True, "policy_reference": "gateway-local-execution-v1"},
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

    evidence = EvidenceRecord(
        evidence_id=f"execution-event-{trace_id}",
        tenant_id="unresolved",
        outcome_id=outcome_id,
        execution_id=trace_id,
        evidence_type="execution_event",
        claim=f"Local recipe runner returned successfully for capability {capability.id}",
        subject=capability.id,
        issuer="elastic-web-gateway",
        source="local-recipe-runner",
        producer="elastic-web-gateway",
        observed_at=now,
        received_at=now,
        artifact_reference=f"trace:{trace_id}",
        content_digest=None,
        protocol_origin=source_protocol,
        related_event_ids=[trace_id],
        verification_status="PENDING",
        privacy_classification="internal",
        retention_policy="runtime-default",
    )
    verification = _VERIFICATION_ENGINE.verify(
        [evidence],
        VerificationContext(
            outcome_id=outcome_id,
            execution_id=trace_id,
            policy_reference="gateway-local-execution-v1",
            verifier_id="elastic-web-gateway",
            required_evidence_ids=[evidence.evidence_id],
            known_event_ids={trace_id},
        ),
        verification_id=f"verification-{trace_id}",
    )
    outcome_status = evaluate_outcome(outcome, [verification])
    outcome = transition_outcome(outcome, outcome_status)
    _BUS.emit(
        "evaluation.completed",
        trace_id=trace_id,
        payload={
            "protocol": {**protocol, "execution_outcome": "succeeded"},
            "evidence_id": evidence.evidence_id,
            "outcome_id": outcome_id,
            "outcome_status": outcome.current_status.value,
            "verification_status": verification.status.value,
        },
    )
    # Keep the existing trace index event for protocol clients, but make its
    # meaning explicit: transport delivery is not assurance completion.
    _BUS.emit(
        "outcome.delivered",
        trace_id=trace_id,
        payload={
            "protocol": {**protocol, "execution_outcome": "executed_not_verified"},
            "evidence_id": evidence.evidence_id,
            "outcome_id": outcome_id,
            "outcome_status": outcome.current_status.value,
            "verification_status": verification.status.value,
        },
    )
    return 200, {
        "capability_id": capability.id,
        "trace_id": trace_id,
        "outcome_id": outcome_id,
        "result": execution.results["execute"],
        "outcome_status": outcome.current_status.value,
        "verification_status": verification.status.value,
        "completion_authoritative": outcome.current_status is OutcomeStatus.COMPLETED,
        "evidence_id": evidence.evidence_id,
    }


# ---------------------------------------------------------------------------
# Endpoint handlers. Each handler is a thin adapter: it parses the request,
# calls a package function, and serializes the result. No business logic.
# ---------------------------------------------------------------------------


def _handle_intent_compile(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return 400, {"error": "body must include a non-empty 'text' string"}
    try:
        ir: IntentIR = _COMPILER.compile(text)
    except ValueError as exc:
        return 422, {"error": str(exc)}
    return 200, ir.model_dump()


def _handle_capabilities_discover(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    intent_text = body.get("intent")
    if not isinstance(intent_text, str) or not intent_text.strip():
        return 400, {"error": "body must include a non-empty 'intent' string"}
    try:
        ir: IntentIR = _COMPILER.compile(intent_text)
    except ValueError as exc:
        return 422, {"error": str(exc)}
    candidates = _RETRIEVER.retrieve(ir)
    return 200, {
        "intent_id": ir.intent_id,
        "candidates": [c.model_dump() for c in candidates],
    }


def _handle_capability_get(capability_id: str) -> Tuple[int, Dict[str, Any]]:
    cap = _capability_by_id(capability_id)
    if cap is None:
        return 404, {"error": f"capability not found: {capability_id}"}
    return 200, cap.model_dump()


def _handle_capability_execute(
    capability_id: str, body: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    cap = _capability_by_id(capability_id)
    if cap is None:
        return 404, {"error": f"capability not found: {capability_id}"}
    args = body.get("args", {})
    if not isinstance(args, dict):
        return 400, {"error": "'args' must be an object"}
    return _execute_through_runtime(
        capability_id,
        args,
        source_protocol="http",
        source_endpoint=f"{_public_base_url()}/capabilities/{capability_id}/execute",
        outcome_id=body.get("outcome_id") if isinstance(body.get("outcome_id"), str) else None,
    )


def _handle_recipes_resolve(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    family = body.get("intent_family")
    if not isinstance(family, str) or not family.strip():
        return 400, {"error": "body must include a non-empty 'intent_family' string"}
    recipe = _RECIPE_STORE.resolve(family)
    if recipe is None:
        return 404, {"error": f"no recipe for intent family: {family}"}
    return 200, recipe.model_dump()


def _handle_recipe_execute(
    recipe_id: str, body: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    args = body.get("args", {})
    if not isinstance(args, dict):
        return 400, {"error": "'args' must be an object"}
    recipe = _RECIPE_STORE.retrieve(recipe_id)
    if recipe is None:
        return 404, {"error": f"recipe not found: {recipe_id}"}

    trace_id = uuid.uuid4().hex
    outcome_id = body.get("outcome_id") if isinstance(body.get("outcome_id"), str) else uuid.uuid4().hex
    # Record that the recipe was retrieved so the telemetry trace carries it.
    _BUS.emit(
        "recipe.retrieved",
        trace_id=trace_id,
        payload={"recipe_id": recipe_id},
    )
    try:
        execution = _RUNNER.run(
            recipe,
            params=args,
            executor=_bank_executor,
            trace_id=trace_id,
        )
        results = execution.results
    except KeyError as exc:
        return 404, {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surface any execution failure
        return 500, {"error": f"{type(exc).__name__}: {exc}"}

    # A local recipe runner result is execution telemetry, not provider proof.
    # Keep the transport response successful for API compatibility, but route
    # the outcome through the same conservative assurance path as capability
    # execution and never claim authoritative completion without verification.
    now = datetime.now(timezone.utc)
    outcome = OutcomeEnvelope(
        outcome_id=outcome_id,
        principal_id="gateway-request",
        originating_agent_id="elastic-web-gateway",
        intent={"recipe_id": recipe.recipe_id, "source_protocol": "REST"},
        desired_state={"execution": "successful"},
        required_capabilities=[step.capability_id for step in recipe.steps],
        execution_plan_reference=recipe.recipe_id,
        verification_policy={"required": True, "policy_reference": "gateway-local-recipe-v1"},
        completion_criteria=recipe.success_conditions or ["recipe execution completed"],
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

    evidence = EvidenceRecord(
        evidence_id=f"execution-event-{trace_id}",
        tenant_id="unresolved",
        outcome_id=outcome_id,
        execution_id=trace_id,
        evidence_type="execution_event",
        claim=f"Local recipe runner returned successfully for recipe {recipe.recipe_id}",
        subject=recipe.recipe_id,
        issuer="elastic-web-gateway",
        source="local-recipe-runner",
        producer="elastic-web-gateway",
        observed_at=now,
        received_at=now,
        artifact_reference=f"trace:{trace_id}",
        content_digest=None,
        protocol_origin="REST",
        related_event_ids=[trace_id],
        verification_status="PENDING",
        privacy_classification="internal",
        retention_policy="runtime-default",
    )
    verification = _VERIFICATION_ENGINE.verify(
        [evidence],
        VerificationContext(
            outcome_id=outcome_id,
            execution_id=trace_id,
            policy_reference="gateway-local-recipe-v1",
            verifier_id="elastic-web-gateway",
            required_evidence_ids=[evidence.evidence_id],
            known_event_ids={trace_id},
        ),
        verification_id=f"verification-{trace_id}",
    )
    outcome_status = evaluate_outcome(outcome, [verification])
    outcome = transition_outcome(outcome, outcome_status)
    _BUS.emit(
        "evaluation.completed",
        trace_id=trace_id,
        payload={
            "recipe_id": recipe_id,
            "outcome_id": outcome_id,
            "outcome_status": outcome.current_status.value,
            "verification_status": verification.status.value,
            "evidence_id": evidence.evidence_id,
        },
    )
    # This event finalizes the transport trace only. Its explicit fields
    # prevent downstream consumers from treating delivery as proof.
    _BUS.emit(
        "outcome.delivered",
        trace_id=trace_id,
        payload={
            "recipe_id": recipe_id,
            "outcome_id": outcome_id,
            "outcome_status": outcome.current_status.value,
            "verification_status": verification.status.value,
            "execution_outcome": "executed_not_verified",
        },
    )
    return 200, {
        "recipe_id": recipe_id,
        "trace_id": trace_id,
        "outcome_id": outcome_id,
        "results": results,
        "outcome_status": outcome.current_status.value,
        "verification_status": verification.status.value,
        "completion_authoritative": outcome.current_status is OutcomeStatus.COMPLETED,
        "evidence_id": evidence.evidence_id,
    }


def _handle_trace_get(trace_id: str) -> Tuple[int, Dict[str, Any]]:
    record = _RECORDER.get(trace_id)
    if record is None:
        return 404, {"error": f"trace not found: {trace_id}"}
    return 200, record.model_dump()


def _handle_health() -> Tuple[int, Dict[str, Any]]:
    return 200, {"status": "ok"}


def _handle_agent_card() -> Tuple[int, Dict[str, Any]]:
    return 200, agent_card(_active_manifest(), _public_base_url())


def _handle_agents_json() -> Tuple[int, Dict[str, Any]]:
    return 200, agents_json(
        _active_manifest(), _public_base_url(), os.environ.get("WEBMCP_URL")
    )


def _handle_agents_txt() -> Tuple[int, str]:
    return 200, agents_txt(
        _active_manifest(), _public_base_url(), os.environ.get("WEBMCP_URL")
    )


def _handle_ucp_profile() -> Tuple[int, Dict[str, Any]]:
    profile = ucp_profile(_active_manifest(), _public_base_url())
    if not profile["ucp"]["capabilities"]:
        return 404, {"error": "UCP commerce is not enabled"}
    return 200, profile


def _ucp_capability(operation: str) -> Optional[Capability]:
    if os.environ.get("ENABLE_SYNTHETIC_UCP_CATALOG") != "1":
        return None
    for capability in _active_manifest():
        if capability.metadata.get("commerce_operation") == operation and capability.metadata.get("ucp_enabled") is True:
            return capability
    return None


def _ucp_response(capability: Capability, result: Dict[str, Any]) -> Dict[str, Any]:
    from projection import UCP_VERSION
    projected = to_ucp_capability(capability)

    payload = {
        "ucp": {
            "version": UCP_VERSION,
            "status": "success",
            "capabilities": {
                projected["name"]: [{"version": projected["version"]}]
            },
        }
    }
    payload.update(result)
    return payload


def _handle_ucp_catalog_search(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    capability = _ucp_capability("catalog.search")
    if capability is None:
        return 404, {"error": "UCP catalog search is not enabled"}
    query = body.get("query")
    if not isinstance(query, str) or len(query) > 256:
        return 400, {"error": "UCP catalog search requires a string query"}
    status, payload = _execute_through_runtime(
        capability.id, {"query": query}, source_protocol="ucp", source_endpoint=f"{_public_base_url()}/ucp/v1/catalog/search"
    )
    if status != 200:
        return status, {"error": payload.get("error"), "trace_id": payload.get("trace_id")}
    return 200, _ucp_response(capability, payload["result"])


def _handle_ucp_catalog_lookup(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    capability = _ucp_capability("catalog.lookup")
    if capability is None:
        return 404, {"error": "UCP catalog lookup is not enabled"}
    ids = body.get("ids")
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) > 50
        or not all(isinstance(item, str) and 0 < len(item) <= 128 for item in ids)
    ):
        return 400, {"error": "UCP catalog lookup requires a non-empty ids array"}
    status, payload = _execute_through_runtime(
        capability.id, {"ids": ids}, source_protocol="ucp", source_endpoint=f"{_public_base_url()}/ucp/v1/catalog/lookup"
    )
    if status != 200:
        return status, {"error": payload.get("error"), "trace_id": payload.get("trace_id")}
    return 200, _ucp_response(capability, payload["result"])


def _handle_a2a_message(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    message = body.get("message")
    metadata = message.get("metadata") if isinstance(message, dict) else None
    if isinstance(metadata, dict) and any(key in metadata for key in ("sessionId", "intentId", "intentRevision", "tenantId", "principalId")):
        _, payload = _handle_a2a_rpc({"jsonrpc": "2.0", "id": None, "method": "message/send", "params": body})
        if "error" in payload:
            return _a2a_rest_error(400, payload["error"]["message"], "INVALID_ARGUMENT")
        return 200, {"task": payload["result"]}
    fixture = _a2a_tck_fixture_response(message)
    if fixture is not None:
        return 200, fixture
    if isinstance(message, dict):
        task_id = message.get("taskId")
        if isinstance(task_id, str) and task_id:
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            try:
                existing = _A2A_TASKS.get(task_id, tenant_id=metadata.get("tenantId"))
            except ValueError as exc:
                return _a2a_rest_error(400, str(exc), "TENANT_CONTEXT_REQUIRED")
            if existing is None:
                return _a2a_rest_error(404, "Task not found", "TASK_NOT_FOUND")
    adapter = A2AInboundAdapter(
        compiler=_COMPILER,
        retriever=_RETRIEVER,
        capability_by_id=_capability_by_id,
        runner=_RUNNER,
        executor=_bank_executor,
        bus=_BUS,
        source_endpoint=f"{_public_base_url()}/message:send",
        task_store=_A2A_TASKS,
    )
    try:
        response = adapter.handle(body)
    except A2AContentTypeNotSupportedError as exc:
        return _a2a_rest_error(415, str(exc), "CONTENT_TYPE_NOT_SUPPORTED")
    except (LookupError, ValueError) as exc:
        return _a2a_rest_error(400, str(exc), "INVALID_ARGUMENT")
    # A2A WORKING is a valid transport response while independent provider
    # evidence is still missing; do not turn that truthful state into HTTP
    # validation failure or imply authoritative completion.
    return 200, response


def _a2a_tck_fixture_response(message: Any) -> Optional[Dict[str, Any]]:
    """Return only the explicitly opted-in, loopback TCK fixture behavior."""
    if os.environ.get(_A2A_TCK_FIXTURE_ENV) != "1" or os.environ.get("GATEWAY_ENV", "development").lower() == "production":
        return None
    if not isinstance(message, dict) or message.get("role") not in {"ROLE_USER", "user"}:
        return None
    message_id = message.get("messageId")
    if not isinstance(message_id, str):
        return None
    task_id = f"tck-{uuid.uuid4().hex}"
    artifact = {
        "artifactId": f"artifact-{task_id}",
        "parts": [],
    }
    if message_id.startswith("tck-artifact-text"):
        artifact["parts"] = [{"text": "Generated text content"}]
    elif message_id.startswith("tck-artifact-file-url"):
        artifact["parts"] = [{"url": "https://example.com/output.txt", "filename": "output.txt", "mediaType": "text/plain"}]
    elif message_id.startswith("tck-artifact-file"):
        artifact["parts"] = [{"raw": "dGNr", "filename": "output.txt", "mediaType": "text/plain"}]
    elif message_id.startswith("tck-artifact-data"):
        artifact["parts"] = [{"data": {"key": "value", "count": 42}, "mediaType": "application/json"}]
    elif message_id.startswith("tck-message-response"):
        return {"message": {"messageId": f"response-{task_id}", "role": "ROLE_AGENT", "parts": [{"text": "Direct message response"}]}}
    else:
        return None
    return {
        "task": {
            "id": task_id,
            "contextId": message.get("contextId") or f"ctx-{uuid.uuid4().hex}",
            "status": {"state": "TASK_STATE_COMPLETED"},
            "artifacts": [artifact],
        }
    }


def _handle_a2a_stream(body: Dict[str, Any]) -> Tuple[int, Any]:
    """Return the adapter's ordered events for the JSON-RPC stream method."""
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or body.get("method") != "message/stream":
        return _a2a_rpc_error(request_id, -32600, "Invalid Request")
    params = body.get("params")
    if not isinstance(params, dict):
        return _a2a_rpc_error(request_id, -32602, "Invalid params")
    message = params.get("message")
    if not isinstance(message, dict):
        return _a2a_rpc_error(request_id, -32602, "message is required")
    try:
        chat_reference = _authorize_chat_message(message)
        if chat_reference is not None and isinstance(chat_reference.get("messageId"), str):
            existing = _A2A_TASKS.get_by_message(
                chat_reference["messageId"],
                chat_reference["sessionId"],
                tenant_id=chat_reference["tenantId"],
            )
            if existing is not None:
                if message.get("contextId") != existing.get("contextId"):
                    return _a2a_rpc_error(request_id, -32602, "messageId is already bound to another context")
                revision_metadata = message.get("metadata", {})
                if any(key in revision_metadata and (type(revision_metadata[key]) is not type(existing.get("metadata", {}).get(key)) or revision_metadata[key] != existing.get("metadata", {}).get(key)) for key in ("intentId", "intentRevision")):
                    return _a2a_rpc_error(request_id, -32602, "messageId is already bound to another intent revision")
                return 200, {"jsonrpc": "2.0", "id": request_id, "events": [
                    {"type": "task.status", "terminal": _terminal_task(existing), "task": _canonical_task(existing)}
                ]}
        adapter = A2AInboundAdapter(
            compiler=_COMPILER,
            retriever=_RETRIEVER,
            capability_by_id=_capability_by_id,
            runner=_RUNNER,
            executor=_bank_executor,
            bus=_BUS,
            source_endpoint=f"{_public_base_url()}/a2a",
            task_store=_A2A_TASKS,
            authorization_check=(lambda: _authorize_chat_message(message) is not None) if chat_reference is not None else None,
        )
        adapter_params = params
        if chat_reference is not None:
            authorized_message = dict(message)
            authorized_message["metadata"] = {
                **(message.get("metadata") if isinstance(message.get("metadata"), dict) else {}),
                **chat_reference,
            }
            adapter_params = {**params, "message": authorized_message}
        if chat_reference is not None and isinstance(_CHAT_SESSIONS, PostgresChatSessionStore):
            _CHAT_SESSIONS.add_message(
                chat_reference["sessionId"],
                chat_reference.get("messageId") or "",
                "",
                tenant_id=chat_reference["tenantId"],
                parts=message.get("parts"),
            )
        events = adapter.stream(adapter_params)
    except A2AContentTypeNotSupportedError as exc:
        return _a2a_rpc_error(request_id, -32005, str(exc))
    except (LookupError, ValueError) as exc:
        return _a2a_rpc_error(request_id, -32602, str(exc))
    if chat_reference is not None:
        task = events[-1]["task"]
        task.setdefault("metadata", {}).update(chat_reference)
        _CHAT_SESSIONS.add_message(
            chat_reference["sessionId"],
            chat_reference.get("messageId") or "",
            task["id"],
            tenant_id=chat_reference["tenantId"],
        )
        for event in events:
            task = event.get("task", {})
            task.setdefault("metadata", {}).update(chat_reference)
        _CHAT_SESSIONS.link_task(
            chat_reference.get("messageId") or "",
            task["id"],
            tenant_id=chat_reference["tenantId"],
        )
    return 200, {"jsonrpc": "2.0", "id": request_id, "events": events}


def _chat_session_request(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    consent_id = body.get("consentId")
    scopes = body.get("scopes")
    if not isinstance(consent_id, str) or not consent_id.strip():
        return 400, {"error": "consentId is required"}
    if not isinstance(scopes, list) or not scopes or not all(isinstance(scope, str) and scope.strip() for scope in scopes):
        return 400, {"error": "scopes must be a non-empty array of strings"}
    if "tenantId" in body or "principalId" in body:
        return 400, {"error": "tenantId and principalId are server-resolved"}
    principal = _REQUEST_PRINCIPAL.get()
    if principal is not None and not set(scopes).issubset(principal.scopes):
        return 403, {"error": "requested scopes exceed authenticated token scopes"}
    now = datetime.now(timezone.utc)
    session_id = f"chat-{uuid.uuid4().hex}"
    context_id = f"ctx-{uuid.uuid4().hex}"
    session = ChatSession(
        session_id=session_id,
        tenant_id=principal.tenant_id if principal else _CHAT_DEV_TENANT,
        principal_id=principal.principal_id if principal else _CHAT_DEV_PRINCIPAL,
        principal_kind=PrincipalKind(principal.principal_kind) if principal else _CHAT_DEV_PRINCIPAL_KIND,
        authenticated_at=now,
        consent_id=consent_id,
        consented_scopes=tuple(scopes),
        scopes=tuple(scopes),
        issued_at=principal.issued_at if principal else now,
        expires_at=principal.expires_at if principal else datetime.fromtimestamp(now.timestamp() + 3600, tz=timezone.utc),
        authorization_decision_id=f"auth-{uuid.uuid4().hex}",
    )
    _CHAT_SESSIONS.put(session, context_id)
    return 201, {
        "sessionId": session_id,
        "contextId": context_id,
        "tenantId": session.tenant_id,
        "principalId": session.principal_id,
        "scopes": list(session.scopes),
        "consentId": session.consent_id,
        "issuedAt": session.issued_at.isoformat(),
        "expiresAt": session.expires_at.isoformat(),
        "status": "active",
    }


def _handle_chat_session_create(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    return _chat_session_request(body)


def _handle_chat_session_revoke(session_id: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    tenant_id = body.get("tenantId") if isinstance(body, dict) else None
    try:
        session = _CHAT_SESSIONS.revoke(
            session_id, datetime.now(timezone.utc), tenant_id=tenant_id
        )
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if session is None:
        return 404, {"error": "chat session not found"}
    return 200, {"sessionId": session_id, "status": "revoked"}


def _authorize_chat_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None
    if "tenantId" in metadata or "principalId" in metadata:
        raise ValueError("tenantId and principalId are server-resolved")
    if "sessionId" not in metadata:
        return None
    if not isinstance(metadata["sessionId"], str) or not metadata["sessionId"].strip():
        raise ValueError("sessionId must be a non-empty string")
    session_id = metadata["sessionId"]
    principal = _REQUEST_PRINCIPAL.get()
    tenant_id = principal.tenant_id if principal else _CHAT_DEV_TENANT
    session = _CHAT_SESSIONS.get(session_id, tenant_id=tenant_id)
    if session is None:
        raise ValueError("chat session not found")
    if "tenantId" in metadata or "principalId" in metadata:
        raise ValueError("tenantId and principalId are server-resolved")
    context_id = message.get("contextId")
    if not isinstance(context_id, str) or _CHAT_SESSIONS.context_owner(context_id, tenant_id=tenant_id) != session_id:
        raise ValueError("contextId is not owned by chat session")
    decision = authorize_chat_session(
        session,
        tenant_id=session.tenant_id,
        principal_id=session.principal_id,
        requested_scopes=session.scopes,
    )
    if not decision.allowed:
        raise ValueError(decision.reason)
    if principal is not None and session.principal_id != principal.principal_id:
        raise ValueError("chat session is not owned by authenticated principal")
    return {
        "sessionId": session_id,
        "contextId": context_id,
        "messageId": message.get("messageId"),
        "tenantId": session.tenant_id,
        "principalId": session.principal_id,
    }


def _authorize_chat_task(task: Dict[str, Any], session_id: Optional[str]) -> bool:
    """Enforce ownership only for tasks created through the chat boundary."""
    task_metadata = task.get("metadata", {})
    task_session_id = task_metadata.get("sessionId")
    if not task_session_id:
        return True  # Preserve the legacy, non-chat A2A lifecycle.
    if session_id != task_session_id:
        return False
    principal = _REQUEST_PRINCIPAL.get()
    tenant_id = task_metadata.get("tenantId") or (principal.tenant_id if principal else _CHAT_DEV_TENANT)
    session = _CHAT_SESSIONS.get(session_id, tenant_id=tenant_id)
    return bool(
        session
        and (principal is None or session.principal_id == principal.principal_id)
        and _CHAT_SESSIONS.context_owner(task.get("contextId", ""), tenant_id=tenant_id) == session_id
        and authorize_chat_session(
            session,
            tenant_id=session.tenant_id,
            principal_id=session.principal_id,
            requested_scopes=session.scopes,
        ).allowed
    )


def _task_tenant_id(session_id: Optional[str], payload: Optional[Dict[str, Any]] = None) -> Optional[str]:
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    if isinstance(metadata, dict) and isinstance(metadata.get("tenantId"), str):
        return metadata["tenantId"]
    if not isinstance(session_id, str) or not session_id:
        return None
    principal = _REQUEST_PRINCIPAL.get()
    tenant_id = principal.tenant_id if principal else _CHAT_DEV_TENANT
    try:
        session = _CHAT_SESSIONS.get(session_id, tenant_id=tenant_id)
    except ValueError:
        return None
    return session.tenant_id if session is not None else None


def _a2a_rpc_error(request_id: Any, code: int, message: str) -> Tuple[int, Dict[str, Any]]:
    return 200, {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _a2a_rest_error(
    code: int,
    message: str,
    reason: str,
    metadata: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, Any]]:
    statuses = {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHENTICATED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        415: "UNSUPPORTED_MEDIA_TYPE",
        501: "UNIMPLEMENTED",
        503: "UNAVAILABLE",
    }
    return code, {
        "error": {
            "code": code,
            "message": message,
            "status": statuses.get(code, "UNKNOWN"),
            "details": [{
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": reason,
                "domain": "a2a-protocol.org",
                "metadata": metadata or {},
            }],
        }
    }


def _handle_a2a_rpc(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Current A2A JSON-RPC endpoint with local polling/cancel support."""
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _a2a_rpc_error(request_id, -32600, "Invalid Request")
    method = body["method"]
    params = body.get("params")
    if not isinstance(params, dict):
        return _a2a_rpc_error(request_id, -32602, "Invalid params")
    if method == "message/send":
        message = params.get("message")
        if not isinstance(message, dict):
            return _a2a_rpc_error(request_id, -32602, "message is required")
        try:
            chat_reference = _authorize_chat_message(message)
        except A2AContentTypeNotSupportedError as exc:
            return _a2a_rpc_error(request_id, -32005, str(exc))
        except (LookupError, ValueError) as exc:
            return _a2a_rpc_error(request_id, -32602, str(exc))
        if chat_reference is not None and isinstance(chat_reference.get("messageId"), str):
            existing = _A2A_TASKS.get_by_message(
                chat_reference["messageId"],
                chat_reference["sessionId"],
                tenant_id=chat_reference["tenantId"],
            )
            if existing is not None:
                if message.get("contextId") != existing.get("contextId"):
                    return _a2a_rpc_error(request_id, -32602, "messageId is already bound to another context")
                revision_metadata = message.get("metadata", {})
                if any(key in revision_metadata and (type(revision_metadata[key]) is not type(existing.get("metadata", {}).get(key)) or revision_metadata[key] != existing.get("metadata", {}).get(key)) for key in ("intentId", "intentRevision")):
                    return _a2a_rpc_error(request_id, -32602, "messageId is already bound to another intent revision")
                return 200, {"jsonrpc": "2.0", "id": request_id, "result": _canonical_task(existing)}
        adapter = A2AInboundAdapter(
            compiler=_COMPILER,
            retriever=_RETRIEVER,
            capability_by_id=_capability_by_id,
            runner=_RUNNER,
            executor=_bank_executor,
            bus=_BUS,
            source_endpoint=f"{_public_base_url()}/a2a",
            task_store=_A2A_TASKS,
            authorization_check=(lambda: _authorize_chat_message(message) is not None) if chat_reference is not None else None,
        )
        try:
            adapter_params = params
            if chat_reference is not None:
                authorized_message = dict(message)
                authorized_message["metadata"] = {
                    **(message.get("metadata") if isinstance(message.get("metadata"), dict) else {}),
                    **chat_reference,
                }
                adapter_params = {**params, "message": authorized_message}
            if chat_reference is not None and isinstance(_CHAT_SESSIONS, PostgresChatSessionStore):
                _CHAT_SESSIONS.add_message(
                    chat_reference["sessionId"],
                    chat_reference.get("messageId") or "",
                    "",
                    tenant_id=chat_reference["tenantId"],
                    parts=message.get("parts"),
                )
            response = adapter.handle(adapter_params)
        except A2AContentTypeNotSupportedError as exc:
            return _a2a_rpc_error(request_id, -32005, str(exc))
        except (LookupError, ValueError) as exc:
            return _a2a_rpc_error(request_id, -32602, str(exc))
        if chat_reference is not None:
            task = response["task"]
            task.setdefault("metadata", {}).update(chat_reference)
            _CHAT_SESSIONS.add_message(
                chat_reference["sessionId"],
                chat_reference.get("messageId") or "",
                task["id"],
                tenant_id=chat_reference["tenantId"],
            )
            _CHAT_SESSIONS.link_task(
                chat_reference.get("messageId") or "",
                task["id"],
                tenant_id=chat_reference["tenantId"],
            )
        return 200, {"jsonrpc": "2.0", "id": request_id, "result": _canonical_task(response["task"])}
    if method in {"tasks/get", "tasks/cancel"}:
        task_id = params.get("id")
        if not isinstance(task_id, str) or not task_id:
            return _a2a_rpc_error(request_id, -32602, "task id is required")
        requested_session = params.get("sessionId")
        if requested_session is None and isinstance(params.get("metadata"), dict):
            requested_session = params["metadata"].get("sessionId")
        tenant_id = _task_tenant_id(
            requested_session if isinstance(requested_session, str) else None,
            params,
        )
        try:
            task = _A2A_TASKS.get(task_id, tenant_id=tenant_id)
        except ValueError as exc:
            return _a2a_rpc_error(request_id, -32602, str(exc))
        if task is None:
            return _a2a_rpc_error(request_id, -32001, "Task not found")
        if not _authorize_chat_task(task, requested_session if isinstance(requested_session, str) else None):
            return _a2a_rpc_error(request_id, -32602, "chat task is not owned by session")
        if method == "tasks/cancel":
            task = _A2A_TASKS.cancel(task_id, tenant_id=tenant_id)
        return 200, {"jsonrpc": "2.0", "id": request_id, "result": _canonical_task(task)}
    return _a2a_rpc_error(request_id, -32601, "Method not found")


def _http_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize the task using the HTTP+JSON enum vocabulary."""
    result = _canonical_task(task)
    state = result.get("status", {}).get("state")
    if isinstance(state, str) and not state.startswith("TASK_STATE_"):
        result["status"]["state"] = "TASK_STATE_" + state.upper().replace("-", "_")
    return result


def _handle_a2a_task_get(task_id: str, session_id: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    try:
        task = _A2A_TASKS.get(task_id, tenant_id=_task_tenant_id(session_id))
    except ValueError as exc:
        return _a2a_rest_error(400, str(exc), "TENANT_CONTEXT_REQUIRED")
    if task is None:
        return _a2a_rest_error(404, "Task not found", "TASK_NOT_FOUND")
    if not _authorize_chat_task(task, session_id):
        return _a2a_rest_error(403, "chat task is not owned by session", "TASK_OWNERSHIP_ERROR")
    return 200, _http_task(task)


def _handle_a2a_task_cancel(
    task_id: str,
    session_id: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    tenant_id = _task_tenant_id(session_id, body)
    try:
        task = _A2A_TASKS.get(task_id, tenant_id=tenant_id)
    except ValueError as exc:
        return _a2a_rest_error(400, str(exc), "TENANT_CONTEXT_REQUIRED")
    if task is None:
        return _a2a_rest_error(404, "Task not found", "TASK_NOT_FOUND")
    if not _authorize_chat_task(task, session_id):
        return _a2a_rest_error(403, "chat task is not owned by session", "TASK_OWNERSHIP_ERROR")
    task = _A2A_TASKS.cancel(task_id, tenant_id=tenant_id)
    return 200, _canonical_task(task)


def _handle_a2a_subscribe(task_id: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    try:
        task = _A2A_TASKS.get(task_id, tenant_id=_task_tenant_id(None, body))
    except ValueError as exc:
        return _a2a_rest_error(400, str(exc), "TENANT_CONTEXT_REQUIRED")
    if task is None:
        return _a2a_rest_error(404, "Task not found", "TASK_NOT_FOUND")
    return _a2a_rest_error(501, "Task subscriptions are not supported", "SUBSCRIBE_NOT_SUPPORTED")


def _handle_a2a_push_notification(task_id: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    return _a2a_rest_error(400, "Push notifications are not supported", "PUSH_NOTIFICATION_NOT_SUPPORTED")


def _handle_a2a_rest_stream(body: Dict[str, Any]) -> Tuple[int, Any]:
    """Adapt the HTTP+JSON message body to the existing ordered stream."""
    message = body.get("message")
    if not isinstance(message, dict):
        return _a2a_rest_error(400, "message is required", "INVALID_ARGUMENT")
    status, payload = _handle_a2a_stream({
        "jsonrpc": "2.0",
        "id": None,
        "method": "message/stream",
        "params": {"message": message},
    })
    if status != 200 or not isinstance(payload, dict) or "events" not in payload:
        return status, payload
    payload["events"] = [
        {
            "statusUpdate": {
                "taskId": (task := _http_task(event["task"]))["id"],
                "contextId": task["contextId"],
                "status": task["status"],
            }
        }
        for event in payload["events"]
        if isinstance(event, dict) and isinstance(event.get("task"), dict)
    ]
    return 200, payload


def _handle_a2a_tasks_list() -> Tuple[int, Dict[str, Any]]:
    try:
        tasks = _A2A_TASKS.all()
    except ValueError as exc:
        return _a2a_rest_error(400, str(exc), "TENANT_CONTEXT_REQUIRED")
    return 200, {"tasks": [_http_task(task) for task in tasks]}


def _handle_mcp(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    request_id = body.get("id")
    method = body.get("method")
    if body.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return 400, {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "vedaxi-elastic", "version": "0.1.0"},
        }
    elif method == "notifications/initialized":
        result = {}
    elif method == "tools/list":
        result = {"tools": [to_mcp_tool(capability) for capability in _active_manifest()]}
    elif method == "tools/call":
        params = body.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return 400, {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "Invalid params"},
            }
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return 400, {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "arguments must be an object"},
            }
        status, payload = _execute_through_runtime(
            params["name"],
            arguments,
            source_protocol="mcp",
            source_endpoint=f"{_public_base_url()}/mcp",
        )
        result = (
            {
                "content": [{"type": "text", "text": json.dumps(payload["result"])}],
                "structuredContent": payload,
                "isError": False,
            }
            if status == 200
            else {
                "content": [{"type": "text", "text": payload["error"]}],
                "isError": True,
            }
        )
    else:
        return 404, {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
    return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}


# ---------------------------------------------------------------------------
# Routing table: (method, regex) -> handler.
# ---------------------------------------------------------------------------
_ROUTES: List[Tuple[str, str, Callable[..., Tuple[int, Dict[str, Any]]]]] = [
    ("POST", r"^/chat/sessions$", _handle_chat_session_create),
    ("POST", r"^/chat/sessions/([^/]+):revoke$", _handle_chat_session_revoke),
    ("GET", r"^/\.well-known/agent-card\.json$", _handle_agent_card),
    ("GET", r"^/\.well-known/ucp$", _handle_ucp_profile),
    ("POST", r"^/ucp/v1/catalog/search$", _handle_ucp_catalog_search),
    ("POST", r"^/ucp/v1/catalog/lookup$", _handle_ucp_catalog_lookup),
    ("GET", r"^/agents\.txt$", _handle_agents_txt),
    ("GET", r"^/agents\.json$", _handle_agents_json),
    ("POST", r"^/message:send$", _handle_a2a_message),
    ("POST", r"^/a2a$", _handle_a2a_rpc),
    ("GET", r"^/tasks$", _handle_a2a_tasks_list),
    ("POST", r"^/tasks/([^/]+):cancel$", _handle_a2a_task_cancel),
    ("POST", r"^/tasks/([^/]+):subscribe$", _handle_a2a_subscribe),
    ("GET", r"^/tasks/([^/]+):subscribe$", _handle_a2a_subscribe),
    ("POST", r"^/tasks/([^/]+):pushNotificationConfig$", _handle_a2a_push_notification),
    ("POST", r"^/tasks/([^/]+):pushNotification$", _handle_a2a_push_notification),
    ("POST", r"^/tasks/([^/]+)/pushNotificationConfigs$", _handle_a2a_push_notification),
    ("GET", r"^/tasks/([^/]+)$", _handle_a2a_task_get),
    ("POST", r"^/mcp$", _handle_mcp),
    ("POST", r"^/intent/compile$", _handle_intent_compile),
    ("POST", r"^/capabilities/discover$", _handle_capabilities_discover),
    ("GET", r"^/capabilities/([^/]+)$", _handle_capability_get),
    ("POST", r"^/capabilities/([^/]+)/execute$", _handle_capability_execute),
    ("POST", r"^/recipes/resolve$", _handle_recipes_resolve),
    ("POST", r"^/recipes/([^/]+)/execute$", _handle_recipe_execute),
    ("GET", r"^/traces/([^/]+)$", _handle_trace_get),
    ("GET", r"^/health$", _handle_health),
]


class GatewayHandler(BaseHTTPRequestHandler):
    """HTTP handler that dispatches to the endpoint handlers above."""

    server_version = "ElasticWebGateway/0.1.0"

    def _send_payload(self, status: int, payload: Any, path: str) -> None:
        is_text = isinstance(payload, str)
        data = (payload if is_text else json.dumps(payload)).encode("utf-8")
        self.send_response(status)
        content_type = "text/plain; charset=utf-8" if is_text else "application/json"
        self.send_header("Content-Type", content_type)
        if path in {"/agents.txt", "/agents.json", "/.well-known/agent-card.json"}:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, status: int, payload: Dict[str, Any]) -> None:
        data = "".join(
            f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
            for event in payload["events"]
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self) -> None:
        _REQUEST_PRINCIPAL.set(None)
        parsed = urlparse(self.path)
        path = parsed.path
        preloaded_body: Optional[Dict[str, Any]] = None
        if _transport_requires_auth(
            self.server.gateway_host, self.server.gateway_production
        ):
            adapter = self.server.gateway_trusted_auth_adapter
            authenticate = getattr(adapter, "authenticate", None)
            if not callable(authenticate):
                self._send_payload(
                    503,
                    _a2a_rest_error(503, "trusted authentication adapter is unavailable", "AUTHENTICATION_ADAPTER_UNAVAILABLE")[1]
                    if path in {"/message:send", "/tasks"} or path.startswith("/tasks/")
                    else {"error": "trusted authentication adapter is unavailable"},
                    path,
                )
                return
            try:
                authenticated = authenticate(self.headers)
                resolver = getattr(adapter, "resolve", None)
                principal = resolver(self.headers) if callable(resolver) else None
                if callable(resolver) and principal is None:
                    authenticated = False
                if isinstance(principal, AuthenticatedPrincipal):
                    _REQUEST_PRINCIPAL.set(principal)
            except Exception:  # noqa: BLE001 - fail closed at the transport boundary.
                authenticated = False
            if not authenticated:
                self._send_payload(
                    401,
                    _a2a_rest_error(401, "authentication required", "AUTHENTICATION_REQUIRED")[1]
                    if path == "/message:send" or path.startswith("/tasks/")
                    else {"error": "authentication required"},
                    path,
                )
                return
        version = self.headers.get("A2A-Version")
        if path == "/message:send" and version not in {None, "", "1.0"}:
            self._send_payload(
                400,
                _a2a_rest_error(
                    400,
                    "A2A-Version is not supported",
                    "VersionNotSupportedError",
                    {"supportedVersions": "1.0"},
                )[1],
                path,
            )
            return
        if path == "/a2a" and version not in {None, "", "1.0"}:
            self._send_payload(
                400,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32005, "message": "Version not supported"}},
                path,
            )
            return
        if self.command == "POST" and path == "/a2a":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body: Dict[str, Any] = json.loads(self.rfile.read(length)) if length else {}
            except (json.JSONDecodeError, ValueError):
                self._send_payload(
                    400,
                    _a2a_rest_error(400, "invalid JSON body", "INVALID_ARGUMENT")[1]
                    if path == "/message:send"
                    else {"error": "invalid JSON body"},
                    path,
                )
                return
            preloaded_body = body
            if body.get("method") == "message/stream":
                status, payload = _handle_a2a_stream(body)
                if status == 200 and isinstance(payload, dict) and "events" in payload:
                    self._send_sse(status, payload)
                else:
                    self._send_payload(status, payload, path)
                return
        if self.command == "POST" and path == "/message:stream":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(length)) if length else {}
            except (json.JSONDecodeError, ValueError):
                self._send_payload(400, _a2a_rest_error(400, "invalid JSON body", "INVALID_ARGUMENT")[1], path)
                return
            status, payload = _handle_a2a_rest_stream(body)
            if status == 200 and isinstance(payload, dict) and "events" in payload:
                self._send_sse(status, payload)
            else:
                self._send_payload(status, payload, path)
            return
        if path.startswith("/ucp/v1/") and not self.headers.get("UCP-Agent"):
            self._send_payload(
                400,
                {"error": "UCP-Agent header is required for UCP requests"},
                path,
            )
            return
        for method, pattern, handler in _ROUTES:
            if method != self.command:
                continue
            match = re.match(pattern, path)
            if match is None:
                continue
            groups = match.groups()
            if self.command in ("POST", "PUT", "PATCH"):
                if preloaded_body is None:
                    try:
                        length = int(self.headers.get("Content-Length", 0) or 0)
                        raw = self.rfile.read(length) if length else b""
                        body = json.loads(raw) if raw else {}
                    except (json.JSONDecodeError, ValueError):
                        self._send_payload(
                            400,
                            _a2a_rest_error(400, "invalid JSON body", "INVALID_ARGUMENT")[1]
                            if path == "/message:send" or path.startswith("/tasks/")
                            else {"error": "invalid JSON body"},
                            path,
                        )
                        return
                status, payload = handler(*groups, body=body)
            else:
                session_id = parse_qs(parsed.query).get("sessionId", [None])[0]
                if handler in {_handle_a2a_task_get, _handle_a2a_task_cancel}:
                    status, payload = handler(*groups, session_id=session_id)
                else:
                    status, payload = handler(*groups)
            self._send_payload(status, payload, path)
            return
        self._send_payload(404, {"error": f"no route for {self.command} {path}"}, path)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def _is_loopback_host(host: str) -> bool:
    """Return whether a bind host is safely local-only."""
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_transport_config(
    host: str, production: bool, trusted_auth_adapter: Any
) -> None:
    """Prevent unauthenticated exposure outside loopback development."""
    if production or not _is_loopback_host(host):
        if trusted_auth_adapter is None or not callable(
            getattr(trusted_auth_adapter, "authenticate", None)
        ):
            raise RuntimeError(
                "gateway refuses non-loopback or production execution without "
                "an explicitly configured trusted authentication adapter"
            )


def _transport_requires_auth(host: str, production: bool) -> bool:
    return production or not _is_loopback_host(host)


def create_app(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    production: bool = False,
    trusted_auth_adapter: Any = None,
) -> ThreadingHTTPServer:
    """Build the HTTP server (used by tests and the CLI).

    The local default is intentionally loopback-only. Embedders must provide
    their already-trusted authentication adapter before binding elsewhere or
    enabling production mode.
    """
    if os.environ.get(_A2A_TCK_FIXTURE_ENV) == "1" and (production or not _is_loopback_host(host)):
        raise RuntimeError("A2A TCK fixture profile is restricted to non-production loopback execution")
    _validate_transport_config(host, production, trusted_auth_adapter)
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    server.gateway_host = host
    server.gateway_production = production
    server.gateway_trusted_auth_adapter = trusted_auth_adapter
    return server


def main() -> None:
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("GATEWAY_PORT", "8000"))
    production = os.environ.get("GATEWAY_ENV", "development").lower() == "production"
    trusted_auth = SupabaseAuthAdapter.from_env() if production or not _is_loopback_host(host) else None
    server = create_app(host, port, production=production, trusted_auth_adapter=trusted_auth)
    print(f"Elastic Web gateway listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()


if __name__ == "__main__":
    main()
