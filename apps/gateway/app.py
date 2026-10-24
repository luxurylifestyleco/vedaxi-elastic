"""Elastic Web HTTP API gateway.

A thin HTTP layer over the Elastic Web foundation packages and multi-protocol adapters.
All business logic lives in the packages under ``packages/``, ``adapters/``, and the ``demo-bank`` app;
this module wires HTTP requests and recipes to capability execution and enforces authorization.

Supported Protocols & Integrations:
- Intent IR (V1 conversational + compiled)
- Capability Registry & Retrieval (L0-L2 progressive disclosure)
- Recipe DAG execution (topological order)
- Demo Bank (in-process local tools)
- Remote MCP (stdio, and HTTP JSON request-response; not Streamable HTTP or SSE)
- A2A (in-process handler, or A2A v1 JSON-RPC SendMessage/GetTask)
- Custom HTTP capability API (not the WebMCP spec)
- Declarative WebMCP forms (toolname/tooldescription). Imperative modelContext is not executed here.
- Invocation-time AuthorizationGuard & security boundaries
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# sys.path bootstrap: make sibling packages, adapters, and demo-bank importable.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES_DIR = os.path.join(_REPO_ROOT, "packages")
_APPS_DIR = os.path.join(_REPO_ROOT, "apps")
_ADAPTERS_DIR = os.path.join(_REPO_ROOT, "adapters")

for _dir in (
    _REPO_ROOT,
    _PACKAGES_DIR,
    _ADAPTERS_DIR,
    os.path.join(_PACKAGES_DIR, "intent-ir"),
    os.path.join(_PACKAGES_DIR, "capability-registry"),
    os.path.join(_PACKAGES_DIR, "capability-retrieval"),
    os.path.join(_PACKAGES_DIR, "recipe-schema"),
    os.path.join(_APPS_DIR, "demo-bank"),
):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

# ---------------------------------------------------------------------------
# Package imports (after sys.path bootstrap).
# ---------------------------------------------------------------------------
import bank  # noqa: E402
from capability import Capability  # noqa: E402
from compiler import RuleBasedCompiler  # noqa: E402
from factory import build_retriever  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from intent_ir_v1 import try_validate_v1  # noqa: E402
from manifest import build_manifest  # noqa: E402
from recipe import Recipe, RecipeStep  # noqa: E402
from store import RecipeStore  # noqa: E402
from telemetry import EventBus, TelemetryRecorder  # noqa: E402

from adapters.mcp.remote_mcp import RemoteMCPAdapter  # noqa: E402
from adapters.a2a.a2a_adapter import A2AAdapter  # noqa: E402
from adapters.webmcp.webmcp_adapter import WebMCPAdapter  # noqa: E402
from adapters.webmcp.declarative import DeclarativeWebMCPClient  # noqa: E402
from adapters.webmcp.browser_client import BrowserWebMCPClient  # noqa: E402
from adapters.security.auth_guard import (  # noqa: E402
    AuthorizationGuard,
    SecurityPrincipal,
    SecurityError,
    UnauthorizedError,
    CredentialsExpiredError,
    PermissionDeniedError,
    SensitiveActionDeniedError,
    UnverifiedCredentialError,
)

# ---------------------------------------------------------------------------
# Maximum allowed payload size (1 MB) to prevent unbounded memory exhaustion
# ---------------------------------------------------------------------------
MAX_BODY_BYTES = 1_048_576

# ---------------------------------------------------------------------------
# Shared application state
# ---------------------------------------------------------------------------
_COMPILER = RuleBasedCompiler()
_MANIFEST: List[Capability] = build_manifest()
_RETRIEVER = build_retriever("keyword", _MANIFEST)
_BUS = EventBus()
_RECORDER = TelemetryRecorder(_BUS)
_RECIPE_STORE = RecipeStore(bus=_BUS)

# Multi-protocol adapter registries
_DYNAMIC_CAPABILITIES: Dict[str, Capability] = {}
_REMOTE_MCP_ADAPTERS: Dict[str, RemoteMCPAdapter] = {}
_A2A_ADAPTERS: Dict[str, A2AAdapter] = {}
_WEBMCP_ADAPTERS: Dict[str, WebMCPAdapter] = {}
_DECLARATIVE_WEBMCP: Dict[str, DeclarativeWebMCPClient] = {}
_BROWSER_WEBMCP: Dict[str, BrowserWebMCPClient] = {}
_LOCAL_CALLABLES: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

# Registered workloads only. A request header cannot create one of these.
_WORKLOADS: Dict[str, SecurityPrincipal] = {}

# No anonymous bypass. A missing credential is unauthenticated.
_AUTH_GUARD = AuthorizationGuard()


def register_remote_mcp_adapter(adapter: RemoteMCPAdapter) -> List[Capability]:
    """Register a remote MCP server adapter in the gateway."""
    caps = adapter.discover()
    for cap in caps:
        _DYNAMIC_CAPABILITIES[cap.id] = cap
        _REMOTE_MCP_ADAPTERS[cap.id] = adapter
    return caps


def register_a2a_adapter(adapter: A2AAdapter) -> List[Capability]:
    """Register an A2A delegation adapter in the gateway."""
    caps = adapter.list_capabilities()
    for cap in caps:
        _DYNAMIC_CAPABILITIES[cap.id] = cap
        _A2A_ADAPTERS[cap.id] = adapter
    return caps


def register_webmcp_adapter(adapter: WebMCPAdapter, capability_ids: List[str]) -> List[Capability]:
    """Register WebMCP capabilities in the gateway."""
    discovered = []
    for cap_id in capability_ids:
        cap = adapter.discover_capability(cap_id)
        if cap:
            _DYNAMIC_CAPABILITIES[cap.id] = cap
            _WEBMCP_ADAPTERS[cap.id] = adapter
            discovered.append(cap)
    return discovered


def register_declarative_webmcp(adapter: DeclarativeWebMCPClient) -> List[Capability]:
    """Register declarative WebMCP form tools. Not the custom HTTP capability API."""
    caps = adapter.discover()
    for cap in caps:
        _DYNAMIC_CAPABILITIES[cap.id] = cap
        _DECLARATIVE_WEBMCP[cap.id] = adapter
    return caps


def register_browser_webmcp(adapter: BrowserWebMCPClient) -> List[Capability]:
    """Register document tools discovered over Chrome WebMCP CDP."""
    caps = adapter.discover()
    for cap in caps:
        _DYNAMIC_CAPABILITIES[cap.id] = cap
        _BROWSER_WEBMCP[cap.id] = adapter
    return caps


def register_local_capability(
    cap: Capability, fn: Callable[[Dict[str, Any]], Any]
) -> Capability:
    """Register an in-process capability the book can select."""
    _DYNAMIC_CAPABILITIES[cap.id] = cap
    _LOCAL_CALLABLES[cap.id] = fn
    return cap


def _capability_by_id(capability_id: str) -> Optional[Capability]:
    """Return a capability by id from dynamic adapters or manifest."""
    if capability_id in _DYNAMIC_CAPABILITIES:
        return _DYNAMIC_CAPABILITIES[capability_id]
    for cap in _MANIFEST:
        if cap.id == capability_id:
            return cap
    return None


def _unified_executor(
    capability_id: str,
    args: Dict[str, Any],
    principal: Optional[SecurityPrincipal] = None,
    explicit_approval: bool = False,
) -> Any:
    """Unified multi-protocol capability executor with authorization checks."""
    cap = _capability_by_id(capability_id)
    if cap is None:
        raise KeyError(f"Capability not found: {capability_id}")

    # Enforce authorization
    _AUTH_GUARD.check(cap, principal=principal, explicit_approval=explicit_approval)

    # Dispatch to Remote MCP
    if capability_id in _REMOTE_MCP_ADAPTERS:
        adapter = _REMOTE_MCP_ADAPTERS[capability_id]
        res = adapter.invoke(capability_id, args)
        if not res.success:
            raise RuntimeError(res.error or "Remote MCP tool failed")
        return res.result

    # Dispatch to A2A
    if capability_id in _A2A_ADAPTERS:
        a2a_adapter = _A2A_ADAPTERS[capability_id]
        res = a2a_adapter.delegate_and_wait(capability_id, args)
        if not res.success:
            raise RuntimeError(res.error or "A2A delegation failed")
        return res.result

    # Dispatch to the custom HTTP capability API (not the WebMCP spec).
    if capability_id in _WEBMCP_ADAPTERS:
        webmcp_adapter = _WEBMCP_ADAPTERS[capability_id]
        res = webmcp_adapter.invoke(capability_id, args)
        if not res.success:
            raise RuntimeError(res.error or "WebMCP execution failed")
        return res.result

    # Dispatch to a declarative WebMCP form submit.
    if capability_id in _DECLARATIVE_WEBMCP:
        res = _DECLARATIVE_WEBMCP[capability_id].invoke(capability_id, args)
        if not res.success:
            raise RuntimeError(res.error or "Declarative WebMCP form failed")
        return res.result

    # Dispatch to browser-document WebMCP (Chrome CDP). Auth already checked above.
    if capability_id in _BROWSER_WEBMCP:
        res = _BROWSER_WEBMCP[capability_id].invoke(capability_id, args)
        if not res.success:
            raise RuntimeError(res.error or "Browser WebMCP execution failed")
        return res.result

    if capability_id in _LOCAL_CALLABLES:
        return _LOCAL_CALLABLES[capability_id](args)

    # Default dispatch to local demo-bank
    fn = getattr(bank, capability_id, None)
    if fn is None or not callable(fn):
        raise KeyError(f"No executable function for capability {capability_id!r}")
    return fn(**args)


def register_workload(token: str, principal: SecurityPrincipal) -> None:
    """Bind a bearer token to a principal. Only this process may call it."""
    if not token or not token.strip():
        raise ValueError("workload token must not be blank")
    _WORKLOADS[token] = principal


def _bank_executor(capability_id: str, args: Dict[str, Any]) -> Any:
    """In-process executor. HTTP routes pass an explicit principal instead."""
    return _unified_executor(capability_id, args)


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


def _handle_intent_compile(body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return 400, {"error": "body must include a non-empty 'text' string"}
    try:
        ir: IntentIR = _COMPILER.compile(text)
    except ValueError as exc:
        return 422, {"error": str(exc)}
    return 200, ir.model_dump()


def _handle_intent_v1(body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    """Validate a conversational Intent IR V1 document. Not a compiler."""
    document: Any
    if isinstance(body.get("intent"), dict):
        document = body["intent"]
    else:
        document = body
    ok, doc, err = try_validate_v1(document)
    if not ok:
        return 400, {"error": err or "invalid Intent IR V1"}
    return 200, doc  # type: ignore[return-value]


def _handle_capabilities_discover(body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
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


def _handle_capability_get(capability_id: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    cap = _capability_by_id(capability_id)
    if cap is None:
        return 404, {"error": f"capability not found: {capability_id}"}
    return 200, cap.model_dump()


def _handle_capability_execute(
    capability_id: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Tuple[int, Dict[str, Any]]:
    cap = _capability_by_id(capability_id)
    if cap is None:
        return 404, {"error": f"capability not found: {capability_id}"}
    args = body.get("args", {})
    if not isinstance(args, dict):
        return 400, {"error": "'args' must be an object"}
    # Caller-supplied tenant or subject is ignored. Identity comes from a registered workload.
    body.pop("tenant_id", None)
    body.pop("subject", None)

    try:
        principal = _extract_principal(headers)
    except UnverifiedCredentialError as exc:
        return 401, {"error": str(exc), "type": "unverified_credential"}
    # body["approval"] is caller text. It is not approval evidence.

    try:
        result = _unified_executor(
            capability_id,
            args,
            principal=principal,
            explicit_approval=False,
        )
    except UnauthorizedError as exc:
        return 401, {"error": str(exc), "type": "unauthorized"}
    except CredentialsExpiredError as exc:
        return 401, {"error": str(exc), "type": "credentials_expired"}
    except (PermissionDeniedError, SensitiveActionDeniedError) as exc:
        return 403, {"error": str(exc), "type": "permission_denied"}
    except TypeError as exc:
        return 400, {"error": f"invalid arguments: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return 200, {
        "capability_id": capability_id,
        "result": result,
        "authorization": {
            "tenant_id": principal.tenant_id if principal else None,
            "caller_agent_id": principal.subject if principal else None,
            "action": capability_id,
            "policy_version": "phase1-local",
        },
    }


def _handle_recipes_resolve(body: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    family = body.get("intent_family")
    if not isinstance(family, str) or not family.strip():
        return 400, {"error": "body must include a non-empty 'intent_family' string"}
    recipe = _RECIPE_STORE.resolve(family)
    if recipe is None:
        return 404, {"error": f"no recipe for intent family: {family}"}
    return 200, recipe.model_dump()


def _handle_recipe_execute(
    recipe_id: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Tuple[int, Dict[str, Any]]:
    args = body.get("args", {})
    if not isinstance(args, dict):
        return 400, {"error": "'args' must be an object"}
    try:
        principal = _extract_principal(headers)
    except UnverifiedCredentialError as exc:
        return 401, {"error": str(exc), "type": "unverified_credential"}
    # body["approval"] is caller text. It is not approval evidence.
    trace_id = uuid.uuid4().hex
    _BUS.emit(
        "recipe.retrieved",
        trace_id=trace_id,
        payload={"recipe_id": recipe_id},
    )

    def executor(capability_id: str, step_args: Dict[str, Any]) -> Any:
        return _unified_executor(
            capability_id,
            step_args,
            principal=principal,
            explicit_approval=False,
        )

    try:
        results = _RECIPE_STORE.execute(
            recipe_id,
            executor=executor,
            trace_id=trace_id,
        )
    except UnauthorizedError as exc:
        return 401, {"error": str(exc), "type": "unauthorized"}
    except CredentialsExpiredError as exc:
        return 401, {"error": str(exc), "type": "credentials_expired"}
    except (PermissionDeniedError, SensitiveActionDeniedError) as exc:
        return 403, {"error": str(exc), "type": "permission_denied"}
    except KeyError as exc:
        return 404, {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    _BUS.emit("outcome.delivered", trace_id=trace_id, payload={"recipe_id": recipe_id})
    return 200, {"recipe_id": recipe_id, "trace_id": trace_id, "results": results}


def _handle_trace_get(trace_id: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    record = _RECORDER.get(trace_id)
    if record is None:
        return 404, {"error": f"trace not found: {trace_id}"}
    return 200, record.model_dump()


def _handle_health(headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    return 200, {"status": "ok"}


def _extract_principal(headers: Optional[Dict[str, str]]) -> Optional[SecurityPrincipal]:
    """Resolve a principal from a workload token this process registered.

    X-Principal and any other client-written identity document are rejected.
    A bearer token is accepted only when register_workload stored it.
    """
    if not headers:
        return None
    lowered = {str(key).lower(): value for key, value in headers.items()}
    if lowered.get("x-principal"):
        raise UnverifiedCredentialError("X-Principal is not a credential")
    auth = lowered.get("authorization")
    if not auth:
        return None
    if not auth.startswith("Bearer "):
        raise UnverifiedCredentialError("unsupported authorization scheme")
    token = auth[7:].strip()
    principal = _WORKLOADS.get(token)
    if principal is None:
        raise UnverifiedCredentialError("unknown workload token")
    return principal


# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------
_ROUTES: List[Tuple[str, str, Callable[..., Tuple[int, Dict[str, Any]]]]] = [
    ("POST", r"^/intent/compile$", _handle_intent_compile),
    ("POST", r"^/intent/v1$", _handle_intent_v1),
    ("POST", r"^/capabilities/discover$", _handle_capabilities_discover),
    ("GET", r"^/capabilities/([^/]+)$", _handle_capability_get),
    ("POST", r"^/capabilities/([^/]+)/execute$", _handle_capability_execute),
    ("POST", r"^/recipes/resolve$", _handle_recipes_resolve),
    ("POST", r"^/recipes/([^/]+)/execute$", _handle_recipe_execute),
    ("GET", r"^/traces/([^/]+)$", _handle_trace_get),
    ("GET", r"^/health$", _handle_health),
]


class GatewayHandler(BaseHTTPRequestHandler):
    """HTTP handler that dispatches to endpoint handlers with size & error limits."""

    server_version = "ElasticWebGateway/0.2.0"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        headers_dict = {k: v for k, v in self.headers.items()}

        for method, pattern, handler in _ROUTES:
            if method != self.command:
                continue
            match = re.match(pattern, path)
            if match is None:
                continue
            groups = match.groups()
            if self.command in ("POST", "PUT", "PATCH"):
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length > MAX_BODY_BYTES:
                    self._send_json(413, {"error": "Payload exceeds maximum allowed size (1 MB)"})
                    return
                try:
                    raw = self.rfile.read(length) if length else b""
                    body: Dict[str, Any] = json.loads(raw) if raw else {}
                except (json.JSONDecodeError, ValueError):
                    self._send_json(400, {"error": "invalid JSON body"})
                    return
                status, payload = handler(*groups, body=body, headers=headers_dict)
            else:
                status, payload = handler(*groups, headers=headers_dict)
            self._send_json(status, payload)
            return
        self._send_json(404, {"error": f"no route for {self.command} {path}"})

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def log_message(self, fmt: str, *args: Any) -> None:
        # Suppress routine log output during tests
        pass


def create_app() -> ThreadingHTTPServer:
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
