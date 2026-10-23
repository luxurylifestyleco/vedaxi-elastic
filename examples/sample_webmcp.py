"""Elastic Web — sample WebMCP-compatible capability (developer onboarding).

Shows how a single demo-bank capability can be exposed over HTTP in a
WebMCP-compatible way. WebMCP is the emerging standard for exposing
capabilities to AI agents over plain HTTP/JSON (a web-native sibling of
MCP). The shape here mirrors the repo's thin gateway
(``apps/gateway/app.py``): a capability is described by a JSON manifest and
invoked via a POST endpoint that returns JSON.

This example is dependency-free (stdlib ``http.server``) and exposes one
capability, ``get_balance``, at two endpoints:

    GET  /capabilities/get_balance   -> capability manifest (discovery)
    POST /capabilities/get_balance/execute  { "args": {...} } -> result

Run from the repo root:

    .venv/Scripts/python.exe examples/sample_webmcp.py

Then:

    curl -s http://127.0.0.1:8001/capabilities/get_balance
    curl -s -X POST http://127.0.0.1:8001/capabilities/get_balance/execute \
         -H 'Content-Type: application/json' \
         -d '{"args": {"account_id": "ACC-1001"}}'
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# sys.path bootstrap so the example can import the sibling packages directly.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _path in (
    _PACKAGES,
    os.path.join(_PACKAGES, "capability-registry"),
    os.path.join(_REPO_ROOT, "apps", "demo-bank"),
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from manifest import build_manifest  # noqa: E402

# The capability we expose over WebMCP.
CAPABILITY_ID = "get_balance"


def _capability_manifest() -> dict:
    """Return the WebMCP manifest for the exposed capability."""
    for cap in build_manifest():
        if cap.id == CAPABILITY_ID:
            return {
                "id": cap.id,
                "name": cap.name,
                "description": cap.description,
                "domain": cap.domain,
                "inputs": cap.inputs,
                "outputs": cap.outputs,
                "permissions": cap.permissions,
                "provider": cap.provider,
                "protocol": "webmcp",
                "endpoint": f"/capabilities/{cap.id}/execute",
            }
    raise KeyError(f"capability not found: {CAPABILITY_ID}")


class WebMCPHandler(BaseHTTPRequestHandler):
    server_version = "ElasticWebWebMCP/0.1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # Discovery: GET /capabilities/{id} -> manifest
        if self.command == "GET" and path == f"/capabilities/{CAPABILITY_ID}":
            self._send_json(200, _capability_manifest())
            return

        # Invocation: POST /capabilities/{id}/execute { "args": {...} }
        if self.command == "POST" and path == f"/capabilities/{CAPABILITY_ID}/execute":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "invalid JSON body"})
                return
            args = body.get("args", {})
            if not isinstance(args, dict):
                self._send_json(400, {"error": "'args' must be an object"})
                return
            import bank

            fn = getattr(bank, CAPABILITY_ID, None)
            if fn is None or not callable(fn):
                self._send_json(500, {"error": f"no callable for {CAPABILITY_ID!r}"})
                return
            try:
                result = fn(**args)
            except TypeError as exc:
                self._send_json(400, {"error": f"invalid arguments: {exc}"})
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            self._send_json(200, {"capability_id": CAPABILITY_ID, "result": result})
            return

        self._send_json(404, {"error": f"no route for {self.command} {path}"})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def main() -> None:
    host, port = "127.0.0.1", int(os.environ.get("WEBMCP_PORT", "8001"))
    server = ThreadingHTTPServer((host, port), WebMCPHandler)
    print(f"WebMCP capability server listening on http://{host}:{port}")
    print(f"  GET  {host}:{port}/capabilities/{CAPABILITY_ID}")
    print(f"  POST {host}:{port}/capabilities/{CAPABILITY_ID}/execute")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()


if __name__ == "__main__":
    main()
