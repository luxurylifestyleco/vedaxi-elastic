"""Tests for WebMCP Adapter (Web-native HTTP capability discovery and execution)."""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
for _p in [
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "adapters"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.webmcp.webmcp_adapter import WebMCPAdapter
from capability import Capability


class MockWebMCPHandler(BaseHTTPRequestHandler):
    """Simulates a WebMCP server as defined in examples/sample_webmcp.py."""

    def do_GET(self):
        if self.path == "/capabilities/get_balance":
            data = {
                "id": "get_balance",
                "name": "Get Balance",
                "description": "Fetch account balance over WebMCP.",
                "domain": "accounts",
                "inputs": {"account_id": {"type": "string"}},
                "outputs": {"balance": {"type": "number"}},
                "permissions": ["accounts:read"],
                "protocol": "webmcp",
                "endpoint": "/capabilities/get_balance/execute",
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/capabilities/get_balance/execute":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            req = json.loads(raw.decode("utf-8"))
            args = req.get("args", {})
            account_id = args.get("account_id", "ACC-UNKNOWN")

            res = {
                "capability_id": "get_balance",
                "result": {"account_id": account_id, "available_balance": 8750.50, "currency": "USD"},
            }
            body = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet during tests


@pytest.fixture
def mock_webmcp_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockWebMCPHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_webmcp_discovery_and_invocation(mock_webmcp_server):
    adapter = WebMCPAdapter(base_url=mock_webmcp_server)
    cap = adapter.discover_capability("get_balance")

    assert cap is not None
    assert isinstance(cap, Capability)
    assert cap.protocol == "webmcp"
    assert cap.metadata["specification"] == "custom-http-capability-api"
    assert cap.metadata["webmcp_spec"] is False
    assert cap.provider == "webmcp-service"
    assert cap.id == "webmcp.get_balance"

    # Invoke capability
    res = adapter.invoke("webmcp.get_balance", {"account_id": "ACC-999"})
    assert res.success is True
    assert res.error is None
    assert res.result["available_balance"] == 8750.50
    assert res.result["account_id"] == "ACC-999"


def test_webmcp_fallback_on_unreachable_endpoint():
    fallback_invoked = False

    def local_fallback(cap_id, args):
        nonlocal fallback_invoked
        fallback_invoked = True
        return {"account_id": args.get("account_id"), "available_balance": 100.0, "source": "fallback"}

    # Port 59999 is inactive
    adapter = WebMCPAdapter(base_url="http://127.0.0.1:59999", fallback_fn=local_fallback)
    res = adapter.invoke("get_balance", {"account_id": "ACC-FALLBACK"})

    assert res.success is True
    assert fallback_invoked is True
    assert res.result["source"] == "fallback"
    assert res.result["available_balance"] == 100.0
