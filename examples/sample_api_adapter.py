"""Elastic Web — sample API adapter (developer onboarding).

A minimal adapter that wraps a demo-bank capability as a REST API endpoint.
This is the pattern a developer would use to expose any registered
capability over HTTP without touching the capability implementation.

The adapter is generic: given a capability id, it looks up the capability
in the demo-bank manifest, exposes its metadata at ``GET /capabilities/{id}``,
and invokes the underlying bank function at ``POST /capabilities/{id}/execute``.
It uses only the Python standard library (``http.server``), mirroring the
repo's thin gateway (``apps/gateway/app.py``).

Run from the repo root:

    .venv/Scripts/python.exe examples/sample_api_adapter.py

Then:

    curl -s http://127.0.0.1:8002/capabilities/get_balance
    curl -s -X POST http://127.0.0.1:8002/capabilities/get_balance/execute \
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


class CapabilityApiAdapter:
    """Wrap a single demo-bank capability as a REST API endpoint.

    Args:
        capability_id: The id of the capability to expose (e.g. ``get_balance``).
    """

    def __init__(self, capability_id: str) -> None:
        self.capability_id = capability_id
        self._capability = self._lookup(capability_id)

    def _lookup(self, capability_id: str):
        for cap in build_manifest():
            if cap.id == capability_id:
                return cap
        raise KeyError(f"capability not found: {capability_id}")

    def manifest(self) -> dict:
        """Return the capability's declared metadata (discovery)."""
        cap = self._capability
        return {
            "id": cap.id,
            "name": cap.name,
            "description": cap.description,
            "domain": cap.domain,
            "inputs": cap.inputs,
            "outputs": cap.outputs,
            "permissions": cap.permissions,
            "provider": cap.provider,
            "protocol": "rest",
            "endpoint": f"/capabilities/{cap.id}/execute",
        }

    def execute(self, args: dict) -> dict:
        """Invoke the underlying bank function with the given args."""
        import bank

        fn = getattr(bank, self.capability_id, None)
        if fn is None or not callable(fn):
            raise KeyError(f"no callable bank function for {self.capability_id!r}")
        return fn(**args)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "ElasticWebApiAdapter/0.1.0"

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
        adapter: CapabilityApiAdapter = self.server.adapter  # type: ignore[attr-defined]

        if self.command == "GET" and path == f"/capabilities/{adapter.capability_id}":
            self._send_json(200, adapter.manifest())
            return

        if self.command == "POST" and path == f"/capabilities/{adapter.capability_id}/execute":
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
            try:
                result = adapter.execute(args)
            except TypeError as exc:
                self._send_json(400, {"error": f"invalid arguments: {exc}"})
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            self._send_json(200, {"capability_id": adapter.capability_id, "result": result})
            return

        self._send_json(404, {"error": f"no route for {self.command} {path}"})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def main() -> None:
    capability_id = os.environ.get("API_CAPABILITY_ID", "get_balance")
    host, port = "127.0.0.1", int(os.environ.get("API_PORT", "8002"))
    adapter = CapabilityApiAdapter(capability_id)
    server = ThreadingHTTPServer((host, port), ApiHandler)
    server.adapter = adapter  # type: ignore[attr-defined]
    print(f"API adapter serving capability {capability_id!r} on http://{host}:{port}")
    print(f"  GET  {host}:{port}/capabilities/{capability_id}")
    print(f"  POST {host}:{port}/capabilities/{capability_id}/execute")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()


if __name__ == "__main__":
    main()
