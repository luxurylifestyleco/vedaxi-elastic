"""Focused gateway checks for generated discovery and protocol boundaries."""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

os.environ["ENABLE_SYNTHETIC_UCP_CATALOG"] = "1"

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


def request(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
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
    assert "UCP: http://127.0.0.1:8000/.well-known/ucp" in text

    status, _, raw = request(server, "GET", "/agents.json")
    discovery = json.loads(raw)
    assert status == 200
    assert set(discovery) >= {"mcp", "a2a"}
    assert "webmcp" not in discovery
    assert "ucp" in discovery

    status, _, raw = request(server, "GET", "/.well-known/agent-card.json")
    card = json.loads(raw)
    assert status == 200
    assert card["skills"]
    assert {skill["id"] for skill in card["skills"]} >= {"get_balance"}

    status, _, raw = request(server, "GET", "/.well-known/ucp")
    profile = json.loads(raw)
    assert status == 200
    assert profile["ucp"]["version"] == "2026-08-25"
    assert profile["ucp"]["payment_handlers"] == {}
    assert set(profile["ucp"]["capabilities"]) == {
        "dev.ucp.shopping.catalog.search",
        "dev.ucp.shopping.catalog.lookup",
    }


def test_ucp_catalog_search_and_lookup_run_through_runtime(server):
    status, _, raw = request(
        server,
        "POST",
        "/ucp/v1/catalog/search",
        {"query": "runner"},
        headers={"UCP-Agent": "https://platform.example/.well-known/ucp"},
    )
    payload = json.loads(raw)
    assert status == 200
    assert payload["ucp"]["capabilities"] == {
        "dev.ucp.shopping.catalog.search": [{"version": "2026-08-25"}]
    }
    assert payload["products"][0]["id"] == "prod_runner_pro"

    status, _, raw = request(
        server,
        "POST",
        "/ucp/v1/catalog/lookup",
        {"ids": ["prod_runner_pro", "prod_missing"]},
        headers={"UCP-Agent": "https://platform.example/.well-known/ucp"},
    )
    payload = json.loads(raw)
    assert status == 200
    assert [item["id"] for item in payload["products"]] == ["prod_runner_pro"]
    assert payload["messages"][0]["code"] == "not_found"


def test_ucp_catalog_rejects_malformed_requests_and_unimplemented_routes(server):
    status, _, raw = request(
        server,
        "POST",
        "/ucp/v1/catalog/search",
        {},
        headers={"UCP-Agent": "https://platform.example/.well-known/ucp"},
    )
    assert status == 400
    payload = json.loads(raw)
    assert "query" in payload["error"]
    status, _, raw = request(
        server,
        "POST",
        "/ucp/v1/catalog/lookup",
        {"ids": []},
        headers={"UCP-Agent": "https://platform.example/.well-known/ucp"},
    )
    assert status == 400
    payload = json.loads(raw)
    assert "ids" in payload["error"]
    status, _, raw = request(server, "POST", "/ucp/v1/catalog/search", {"query": "runner"})
    payload = json.loads(raw)
    assert status == 400
    assert "UCP-Agent" in payload["error"]
    status, _, raw = request(server, "POST", "/ucp/v1/checkout", {})
    payload = json.loads(raw)
    assert status == 400
    assert "UCP-Agent" in payload["error"]


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
    assert task["status"]["state"] == "TASK_STATE_WORKING"
    trace_id = task["metadata"]["traceId"]
    status, _, raw = request(server, "GET", f"/traces/{trace_id}")
    trace = json.loads(raw)
    assert status == 200
    assert trace["protocol_metadata"]["source_protocol"] == "a2a"
    assert trace["outcome"] is None
