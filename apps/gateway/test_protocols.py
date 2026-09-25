"""Focused gateway checks for generated discovery and protocol boundaries."""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def server():
    httpd = create_app()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def request(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as response:
            raw = response.read().decode()
            return response.status, response.headers, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode()


def test_machine_discovery_and_agent_card_are_live_and_truthful(server):
    status, headers, text = request(server, "GET", "/agents.txt")
    assert status == 200
    assert headers.get_content_type() == "text/plain"
    assert "MCP: http://127.0.0.1:8000/mcp" in text
    assert "A2A: http://127.0.0.1:8000/.well-known/agent-card.json" in text
    assert "WebMCP:" not in text
    assert "UCP:" not in text

    status, _, raw = request(server, "GET", "/agents.json")
    discovery = json.loads(raw)
    assert status == 200
    assert set(discovery) >= {"mcp", "a2a"}
    assert "webmcp" not in discovery
    assert "ucp" not in discovery

    status, _, raw = request(server, "GET", "/.well-known/agent-card.json")
    card = json.loads(raw)
    assert status == 200
    assert card["skills"]
    assert {skill["id"] for skill in card["skills"]} >= {"get_balance"}

    status, _, _ = request(server, "GET", "/.well-known/ucp")
    assert status == 404


def test_mcp_serving_projects_and_executes_through_runtime_with_evidence(server):
    status, _, raw = request(
        server,
        "POST",
        "/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    tools = json.loads(raw)["result"]["tools"]
    assert status == 200
    assert next(tool for tool in tools if tool["name"] == "get_balance")["_meta"][
        "elastic"
    ]["provider"] == "demo-bank"

    status, _, raw = request(
        server,
        "POST",
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_balance", "arguments": {"account_id": "ACC-1"}},
        },
    )
    result = json.loads(raw)["result"]
    assert status == 200
    assert result["isError"] is False
    trace_id = result["structuredContent"]["trace_id"]
    status, _, raw = request(server, "GET", f"/traces/{trace_id}")
    trace = json.loads(raw)
    assert status == 200
    assert trace["protocol_metadata"]["source_protocol"] == "mcp"
    assert trace["capability_ids"] == ["get_balance"]
    assert trace["outcome"] == "delivered"


def test_a2a_message_enters_intent_retrieval_runtime_and_returns_evidence(server):
    status, _, raw = request(
        server,
        "POST",
        "/message:send",
        {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_USER",
                "parts": [
                    {"text": "Get my August bank statement"},
                    {"data": {"account_id": "ACC-1"}},
                ],
            }
        },
    )
    task = json.loads(raw)["task"]
    assert status == 200
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    trace_id = task["metadata"]["traceId"]
    status, _, raw = request(server, "GET", f"/traces/{trace_id}")
    trace = json.loads(raw)
    assert status == 200
    assert trace["protocol_metadata"]["source_protocol"] == "a2a"
    assert trace["outcome"] == "delivered"
