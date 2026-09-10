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
from manifest import build_manifest  # noqa: E402
from recipe import Recipe, RecipeStep  # noqa: E402
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
    fn = getattr(bank, capability_id, None)
    if fn is None or not callable(fn):
        return 500, {"error": f"no callable bank function for {capability_id!r}"}
    try:
        result = fn(**args)
    except TypeError as exc:
        return 400, {"error": f"invalid arguments: {exc}"}
    except Exception as exc:  # noqa: BLE001 - surface any execution failure
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    return 200, {"capability_id": capability_id, "result": result}


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


# ---------------------------------------------------------------------------
# Routing table: (method, regex) -> handler.
# ---------------------------------------------------------------------------
_ROUTES: List[Tuple[str, str, Callable[..., Tuple[int, Dict[str, Any]]]]] = [
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
                    self._send_json(400, {"error": "invalid JSON body"})
                    return
                status, payload = handler(*groups, body=body)
            else:
                status, payload = handler(*groups)
            self._send_json(status, payload)
            return
        self._send_json(404, {"error": f"no route for {self.command} {path}"})

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
