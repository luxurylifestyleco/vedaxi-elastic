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
from projection import to_mcp_tool  # noqa: E402
from runner import RecipeDAGRunner  # noqa: E402
from store import RecipeStore  # noqa: E402
from telemetry import EventBus, TelemetryRecorder  # noqa: E402

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


def _capability_by_id(capability_id: str) -> Optional[Capability]:
    """Return a manifest capability by id, or ``None``."""
    for cap in _MANIFEST:
        if cap.id == capability_id:
            return cap
    return None


def _bank_executor(capability_id: str, args: Dict[str, Any]) -> Any:
    """Execute a demo-bank function by capability id (used by recipes)."""
    fn = getattr(bank, capability_id, None)
    if fn is None or not callable(fn):
        raise KeyError(f"no bank function for capability {capability_id!r}")
    return fn(**args)


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _execute_through_runtime(
    capability_id: str,
    args: Dict[str, Any],
    *,
    source_protocol: str,
    source_endpoint: str,
) -> Tuple[int, Dict[str, Any]]:
    capability = _capability_by_id(capability_id)
    if capability is None:
        return 404, {"error": f"capability not found: {capability_id}"}
    trace_id = uuid.uuid4().hex
    protocol = {
        "source_protocol": source_protocol,
        "source_endpoint": source_endpoint,
        "provider": capability.provider,
        "selected_capability": capability.id,
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
    _BUS.emit(
        "outcome.delivered",
        trace_id=trace_id,
        payload={
            "protocol": {**protocol, "execution_outcome": "succeeded"},
            "evidence_id": trace_id,
        },
    )
    return 200, {
        "capability_id": capability.id,
        "trace_id": trace_id,
        "result": execution.results["execute"],
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
    trace_id = uuid.uuid4().hex
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
    # Emit the terminal outcome event so the telemetry record finalizes.
    _BUS.emit("outcome.delivered", trace_id=trace_id, payload={"recipe_id": recipe_id})
    return 200, {"recipe_id": recipe_id, "trace_id": trace_id, "results": results}


def _handle_trace_get(trace_id: str) -> Tuple[int, Dict[str, Any]]:
    record = _RECORDER.get(trace_id)
    if record is None:
        return 404, {"error": f"trace not found: {trace_id}"}
    return 200, record.model_dump()


def _handle_health() -> Tuple[int, Dict[str, Any]]:
    return 200, {"status": "ok"}


def _handle_agent_card() -> Tuple[int, Dict[str, Any]]:
    return 200, agent_card(_MANIFEST, _public_base_url())


def _handle_agents_json() -> Tuple[int, Dict[str, Any]]:
    return 200, agents_json(
        _MANIFEST, _public_base_url(), os.environ.get("WEBMCP_URL")
    )


def _handle_agents_txt() -> Tuple[int, str]:
    return 200, agents_txt(
        _MANIFEST, _public_base_url(), os.environ.get("WEBMCP_URL")
    )


def _handle_ucp_profile() -> Tuple[int, Dict[str, Any]]:
    profile = ucp_profile(_MANIFEST, _public_base_url())
    if not profile["capabilities"]:
        return 404, {"error": "UCP commerce is not enabled"}
    return 200, profile


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
    state = response["task"]["status"]["state"]
    return (200 if state == "TASK_STATE_COMPLETED" else 422), response


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
        result = {"tools": [to_mcp_tool(capability) for capability in _MANIFEST]}
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
