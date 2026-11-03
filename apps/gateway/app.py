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
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

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
from a2a import A2AInboundAdapter  # noqa: E402
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
        results = _RECIPE_STORE.execute(
            recipe_id,
            executor=_bank_executor,
            trace_id=trace_id,
        )
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
    adapter = A2AInboundAdapter(
        compiler=_COMPILER,
        retriever=_RETRIEVER,
        capability_by_id=_capability_by_id,
        runner=_RUNNER,
        executor=_bank_executor,
        bus=_BUS,
        source_endpoint=f"{_public_base_url()}/message:send",
    )
    response = adapter.handle(body)
    # A2A WORKING is a valid transport response while independent provider
    # evidence is still missing; do not turn that truthful state into HTTP
    # validation failure or imply authoritative completion.
    return 200, response


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
    ("GET", r"^/\.well-known/agent-card\.json$", _handle_agent_card),
    ("GET", r"^/\.well-known/ucp$", _handle_ucp_profile),
    ("POST", r"^/ucp/v1/catalog/search$", _handle_ucp_catalog_search),
    ("POST", r"^/ucp/v1/catalog/lookup$", _handle_ucp_catalog_lookup),
    ("GET", r"^/agents\.txt$", _handle_agents_txt),
    ("GET", r"^/agents\.json$", _handle_agents_json),
    ("POST", r"^/message:send$", _handle_a2a_message),
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
        if path == "/message:send" and not is_text:
            content_type = "application/a2a+json"
        self.send_header("Content-Type", content_type)
        if path in {"/agents.txt", "/agents.json", "/.well-known/agent-card.json"}:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
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
                try:
                    length = int(self.headers.get("Content-Length", 0) or 0)
                    raw = self.rfile.read(length) if length else b""
                    body: Dict[str, Any] = json.loads(raw) if raw else {}
                except (json.JSONDecodeError, ValueError):
                    self._send_payload(400, {"error": "invalid JSON body"}, path)
                    return
                status, payload = handler(*groups, body=body)
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


def create_app() -> ThreadingHTTPServer:
    """Build the HTTP server (used by tests and the CLI)."""
    return ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)


def main() -> None:
    host, port = "127.0.0.1", int(os.environ.get("GATEWAY_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"Elastic Web gateway listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()


if __name__ == "__main__":
    main()
