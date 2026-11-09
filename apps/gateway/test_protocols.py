"""Focused gateway checks for generated discovery and protocol boundaries."""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

os.environ["ENABLE_SYNTHETIC_UCP_CATALOG"] = "1"

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from app import PostgresChatSessionStore, SQLiteChatSessionStore, create_app  # noqa: E402
import app as gateway_app  # noqa: E402
from execution_context import ChatSession, PrincipalKind  # noqa: E402


class _FakeSessionDb:
    def __init__(self):
        self.calls = []

    def connect(self, _dsn):
        owner = self
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params=()): owner.calls.append((sql, params))
            def fetchone(self): return None
        class Connection:
            def cursor(self): return Cursor()
            def commit(self): pass
            def rollback(self): pass
            def close(self): pass
        return Connection()


def test_postgres_chat_store_uses_server_resolved_tenant_and_fail_closed_dsn():
    with pytest.raises(ValueError):
        PostgresChatSessionStore("")
    fake = _FakeSessionDb()
    store = PostgresChatSessionStore("postgresql://test", fake.connect)
    now = datetime.now(timezone.utc)
    session = ChatSession(
        session_id="session-pg", tenant_id="tenant-pg", principal_id="principal-pg",
        principal_kind=PrincipalKind.HUMAN, authenticated_at=now, consent_id="consent-pg",
        consented_scopes=("chat:send",), scopes=("chat:send",), issued_at=now,
        expires_at=now + timedelta(hours=1), authorization_decision_id="decision-pg",
    )
    store.put(session, "context-pg")
    setting_sql, setting_params = fake.calls[0]
    assert "set_config('app.tenant_id'" in setting_sql
    assert setting_params == ("tenant-pg",)
    sql, params = fake.calls[1]
    assert "public.chat_sessions" in sql
    assert params[1:4] == ("tenant-pg", "principal-pg", "human")
    with pytest.raises(ValueError):
        store.get("session-pg")


def test_postgres_chat_store_persists_message_parts(monkeypatch):
    store = PostgresChatSessionStore("postgresql://test", lambda _dsn: None)
    now = datetime.now(timezone.utc)
    session = ChatSession(
        session_id="session-pg", tenant_id="tenant-pg", principal_id="principal-pg",
        principal_kind=PrincipalKind.HUMAN, authenticated_at=now, consent_id="consent-pg",
        consented_scopes=("chat:send",), scopes=("chat:send",), issued_at=now,
        expires_at=now + timedelta(hours=1), authorization_decision_id="decision-pg",
    )
    monkeypatch.setattr(store, "get", lambda *_args, **_kwargs: session)
    queries = []
    def query(sql, params=(), **_kwargs):
        queries.append((sql, params))
        return ("context-pg",) if "SELECT context_id" in sql else None
    monkeypatch.setattr(store, "_query", query)
    store.add_message("session-pg", "message-pg", "", tenant_id="tenant-pg", parts=[{"text": "hello"}])
    assert queries[-1][1][-2] == json.dumps([{"text": "hello"}])


def test_gateway_chat_lookups_pass_server_tenant_to_store(monkeypatch):
    now = datetime.now(timezone.utc)
    session = ChatSession(
        session_id="session-pg", tenant_id="tenant-pg", principal_id="principal-pg",
        principal_kind=PrincipalKind.HUMAN, authenticated_at=now, consent_id="consent-pg",
        consented_scopes=("chat:send",), scopes=("chat:send",), issued_at=now,
        expires_at=now + timedelta(hours=1), authorization_decision_id="decision-pg",
    )
    calls = []

    class TenantRequiredStore:
        def get(self, session_id, *, tenant_id):
            calls.append(("get", session_id, tenant_id))
            return session if session_id == session.session_id else None

        def context_owner(self, context_id, *, tenant_id):
            calls.append(("context_owner", context_id, tenant_id))
            return session.session_id if context_id == "context-pg" else None

    monkeypatch.setattr(gateway_app, "_CHAT_SESSIONS", TenantRequiredStore())
    monkeypatch.setattr(gateway_app, "_CHAT_DEV_TENANT", "tenant-pg")
    message = {
        "messageId": "message-pg",
        "contextId": "context-pg",
        "metadata": {"sessionId": "session-pg"},
    }

    reference = gateway_app._authorize_chat_message(message)

    assert reference["tenantId"] == "tenant-pg"
    assert calls == [
        ("get", "session-pg", "tenant-pg"),
        ("context_owner", "context-pg", "tenant-pg"),
    ]
    calls.clear()
    assert gateway_app._task_tenant_id("session-pg") == "tenant-pg"
    assert calls == [("get", "session-pg", "tenant-pg")]


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


def test_sqlite_chat_sessions_survive_restart_and_revoke(tmp_path):
    path = str(tmp_path / "chat.sqlite")
    now = datetime.now(timezone.utc)
    session = ChatSession(
        session_id="session-1",
        tenant_id="tenant-1",
        principal_id="principal-1",
        principal_kind=PrincipalKind.HUMAN,
        authenticated_at=now,
        consent_id="consent-1",
        consented_scopes=("chat:send",),
        scopes=("chat:send",),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        authorization_decision_id="decision-1",
    )
    first = SQLiteChatSessionStore(path)
    first.put(session, "context-1")
    first.add_message("session-1", "message-1", "task-1")

    second = SQLiteChatSessionStore(path)
    assert second.get("session-1").session_id == "session-1"
    assert second.context_owner("context-1") == "session-1"
    revoked = second.revoke("session-1", now)
    assert revoked.revoked_at == now


def test_sqlite_chat_sessions_isolate_context_and_session_ownership(tmp_path):
    path = str(tmp_path / "chat.sqlite")
    now = datetime.now(timezone.utc)
    first = ChatSession(
        session_id="session-a",
        tenant_id="tenant-a",
        principal_id="principal-a",
        principal_kind=PrincipalKind.HUMAN,
        authenticated_at=now,
        consent_id="consent-a",
        consented_scopes=("chat:send",),
        scopes=("chat:send",),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        authorization_decision_id="decision-a",
    )
    second = first.model_copy(update={
        "session_id": "session-b",
        "tenant_id": "tenant-b",
        "principal_id": "principal-b",
        "consent_id": "consent-b",
        "authorization_decision_id": "decision-b",
    })
    store = SQLiteChatSessionStore(path)
    store.put(first, "context-a")
    store.put(second, "context-b")

    assert store.get("session-a").tenant_id == "tenant-a"
    assert store.context_owner("context-a") == "session-a"
    assert store.context_owner("context-b") == "session-b"
    assert store.context_owner("context-missing") is None
    assert store.get("session-missing") is None


def test_sqlite_chat_session_store_rejects_missing_durable_configuration():
    with pytest.raises((TypeError, ValueError)):
        SQLiteChatSessionStore(None)


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
    status, headers, raw = request(
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
    assert headers.get_content_type() == "application/json"
    assert task["status"]["state"] == "TASK_STATE_WORKING"
    trace_id = task["metadata"]["traceId"]
    status, _, raw = request(server, "GET", f"/traces/{trace_id}")
    trace = json.loads(raw)
    assert status == 200
    assert trace["protocol_metadata"]["source_protocol"] == "a2a"
    assert trace["outcome"] is None


def test_a2a_tck_fixture_profile_is_opt_in_and_isolated(server, monkeypatch):
    monkeypatch.setenv("ELASTIC_A2A_TCK_FIXTURE", "1")
    base_message = {"role": "ROLE_USER", "parts": [{"text": "TCK artifact test"}]}
    cases = {
        "tck-artifact-text-1": ("text", "Generated text content"),
        "tck-artifact-file-1": ("raw", "dGNr"),
        "tck-artifact-file-url-1": ("url", "https://example.com/output.txt"),
        "tck-artifact-data-1": ("data", {"key": "value", "count": 42}),
    }
    for message_id, (part_key, expected) in cases.items():
        message = {**base_message, "messageId": message_id}
        status, _, raw = request(server, "POST", "/message:send", {"message": message})
        payload = json.loads(raw)
        assert status == 200 and "task" in payload
        part = payload["task"]["artifacts"][0]["parts"][0]
        assert part[part_key] == expected
        if part_key in {"raw", "url"}:
            assert part["filename"] == "output.txt"
            assert part["mediaType"] == "text/plain"

    status, _, raw = request(
        server,
        "POST",
        "/message:send",
        {"message": {**base_message, "messageId": "tck-message-response-1"}},
    )
    payload = json.loads(raw)
    assert status == 200
    assert payload["message"]["parts"] == [{"text": "Direct message response"}]

    monkeypatch.setenv("GATEWAY_ENV", "production")
    status, _, raw = request(
        server,
        "POST",
        "/message:send",
        {"message": {**base_message, "messageId": "tck-artifact-text-production"}},
    )
    assert status == 200
    assert "task" in json.loads(raw)
    monkeypatch.setenv("GATEWAY_ENV", "development")
    with pytest.raises(RuntimeError, match="loopback"):
        create_app(production=True)


def test_a2a_jsonrpc_task_lifecycle_and_version_guard(server):
    body = {
        "jsonrpc": "2.0",
        "id": "rpc-1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "rpc-msg-1",
                "role": "user",
                "parts": [{"kind": "text", "text": "Get my August bank statement"}],
            }
        },
    }
    status, _, raw = request(server, "POST", "/a2a", body, headers={"A2A-Version": "1.0"})
    payload = json.loads(raw)
    assert status == 200
    assert payload["id"] == "rpc-1"
    task = payload["result"]
    assert task["status"]["state"] == "working"
    task_id = task["id"]

    status, _, raw = request(server, "POST", "/a2a", {
        "jsonrpc": "2.0", "id": "rpc-2", "method": "tasks/get", "params": {"id": task_id}
    })
    fetched = json.loads(raw)
    assert status == 200
    assert fetched["result"]["id"] == task_id
    assert fetched["result"]["metadata"]["traceId"] == task["metadata"]["traceId"]

    status, _, raw = request(server, "GET", f"/tasks/{task_id}")
    http_task = json.loads(raw)
    assert status == 200
    assert http_task["id"] == task_id

    status, _, raw = request(server, "POST", "/a2a", {
        "jsonrpc": "2.0", "id": "rpc-3", "method": "tasks/cancel", "params": {"id": task_id}
    })
    canceled = json.loads(raw)
    assert status == 200
    assert canceled["result"]["status"]["state"] == "working"
    assert canceled["result"]["metadata"]["cancellationRequested"] is True

    status, _, raw = request(server, "POST", "/a2a", {
        "jsonrpc": "2.0", "id": "rpc-4", "method": "tasks/get", "params": {"id": "missing-task"}
    })
    missing = json.loads(raw)
    assert status == 200
    assert missing["error"]["code"] == -32001

    status, _, raw = request(server, "POST", "/a2a", body, headers={"A2A-Version": "0.3"})
    unsupported = json.loads(raw)
    assert status == 400
    assert unsupported["error"]["code"] == -32005

    status, _, raw = request(
        server,
        "POST",
        "/message:send",
        {"message": {"messageId": "versioned-rest", "role": "user", "parts": [{"text": "hello"}]}},
        headers={"A2A-Version": "0.3"},
    )
    unsupported_rest = json.loads(raw)
    assert status == 400
    assert unsupported_rest["error"]["code"] == 400
    assert unsupported_rest["error"]["status"] == "INVALID_ARGUMENT"
    assert unsupported_rest["error"]["details"][0]["reason"] == "VersionNotSupportedError"


def test_a2a_rest_errors_and_unsupported_operations_use_aip193(server):
    status, headers, raw = request(server, "GET", "/tasks/missing-task")
    payload = json.loads(raw)
    assert status == 404
    assert headers.get_content_type() == "application/json"
    assert payload["error"]["code"] == 404
    assert payload["error"]["status"] == "NOT_FOUND"
    assert payload["error"]["details"][0]["@type"] == "type.googleapis.com/google.rpc.ErrorInfo"

    for path, method in (
        ("/tasks/missing-task:cancel", "POST"),
        ("/tasks/missing-task:subscribe", "GET"),
        ("/tasks/missing-task:pushNotificationConfig", "POST"),
        ("/tasks/missing-task:pushNotification", "POST"),
    ):
        status, _, raw = request(server, method, path, {} if method == "POST" else None)
        error = json.loads(raw)["error"]
        expected_status = 404 if path.endswith((":cancel", ":subscribe")) else 400
        assert status == expected_status
        assert error["status"] == ("NOT_FOUND" if path.endswith((":cancel", ":subscribe")) else "INVALID_ARGUMENT")
        assert error["details"][0]["@type"] == "type.googleapis.com/google.rpc.ErrorInfo"


def test_a2a_message_stream_keeps_unverified_execution_nonterminal(server):
    body = {
        "jsonrpc": "2.0",
        "id": "stream-1",
        "method": "message/stream",
        "params": {"message": {"messageId": "stream-msg", "role": "user", "parts": [{"text": "Get my August bank statement"}]}},
    }
    status, headers, raw = request(server, "POST", "/a2a", body)
    assert status == 200
    assert headers.get_content_type() == "text/event-stream"
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
    assert [event["terminal"] for event in events] == [False, False]
    assert events[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert events[-1]["task"]["status"]["state"] in {"TASK_STATE_WORKING", "TASK_STATE_COMPLETED", "TASK_STATE_FAILED"}


def test_a2a_message_stream_rejects_malformed_request(server):
    status, _, raw = request(server, "POST", "/a2a", {
        "jsonrpc": "2.0", "id": "stream-bad", "method": "message/stream", "params": {},
    })
    assert status == 200
    assert json.loads(raw)["error"]["code"] == -32602


class _RejectAuth:
    def authenticate(self, headers):
        return False


def test_a2a_message_stream_rejects_unauthenticated_production_request():
    httpd = create_app(production=True, trusted_auth_adapter=_RejectAuth())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_address[1]}"
        status, headers, raw = request(base, "POST", "/a2a", {
            "jsonrpc": "2.0", "id": "stream-auth", "method": "message/stream",
            "params": {"message": {"role": "user", "parts": [{"text": "hello"}]}},
        })
        assert status == 401
        assert headers.get_content_type() == "application/json"
        assert json.loads(raw)["error"] == "authentication required"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _start_chat(server, scopes=None):
    status, _, raw = request(
        server,
        "POST",
        "/chat/sessions",
        {"consentId": "consent-test", "scopes": scopes or ["support:read"]},
    )
    return status, json.loads(raw)


def test_chat_session_creation_resolves_identity_and_rejects_overrides(server):
    status, session = _start_chat(server)
    assert status == 201
    assert session["tenantId"] == gateway_app._CHAT_DEV_TENANT
    assert session["principalId"] == gateway_app._CHAT_DEV_PRINCIPAL
    status, _, raw = request(
        server,
        "POST",
        "/chat/sessions",
        {"consentId": "consent-test", "scopes": ["support:read"], "tenantId": "attacker"},
    )
    assert status == 400
    assert "server-resolved" in json.loads(raw)["error"]


def test_chat_session_requires_consent_and_revocation_blocks_a2a(server):
    status, _, raw = request(server, "POST", "/chat/sessions", {"scopes": ["support:read"]})
    assert status == 400
    assert "consentId" in json.loads(raw)["error"]
    status, session = _start_chat(server)
    assert status == 201
    status, _, raw = request(server, "POST", f"/chat/sessions/{session['sessionId']}:revoke", {})
    assert status == 200
    status, _, raw = request(
        server,
        "POST",
        "/a2a",
        {
            "jsonrpc": "2.0",
            "id": "revoked-chat",
            "method": "message/send",
            "params": {"message": {"messageId": "revoked-msg", "role": "user", "contextId": session["contextId"], "metadata": {"sessionId": session["sessionId"]}, "parts": [{"text": "Get my August bank statement"}]}},
        },
    )
    assert status == 200
    assert json.loads(raw)["error"]["code"] == -32602


def test_chat_session_context_ownership_and_a2a_reference(server):
    _, first = _start_chat(server)
    _, second = _start_chat(server)
    body = {
        "jsonrpc": "2.0",
        "id": "chat-send",
        "method": "message/send",
        "params": {"message": {"messageId": "chat-msg", "role": "user", "contextId": first["contextId"], "metadata": {"sessionId": first["sessionId"]}, "parts": [{"text": "Get my August bank statement"}]}},
    }
    status, _, raw = request(server, "POST", "/a2a", body)
    payload = json.loads(raw)
    assert status == 200
    assert payload["result"]["metadata"]["sessionId"] == first["sessionId"]
    assert payload["result"]["metadata"]["contextId"] == first["contextId"]
    assert payload["result"]["metadata"]["messageId"] == "chat-msg"
    body["params"]["message"]["contextId"] = second["contextId"]
    status, _, raw = request(server, "POST", "/a2a", body)
    assert json.loads(raw)["error"]["code"] == -32602


def test_chat_task_bridge_is_idempotent_and_session_owned(server):
    _, first = _start_chat(server)
    _, second = _start_chat(server)
    body = {
        "jsonrpc": "2.0",
        "id": "chat-task-1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "stable-chat-message",
                "role": "user",
                "contextId": first["contextId"],
                "metadata": {"sessionId": first["sessionId"]},
                "parts": [{"text": "Get my August bank statement"}],
            }
        },
    }
    status, _, raw = request(server, "POST", "/a2a", body)
    task = json.loads(raw)["result"]
    assert status == 200
    assert task["metadata"]["sessionId"] == first["sessionId"]
    assert task["metadata"]["messageId"] == "stable-chat-message"
    assert task["artifacts"][0]["parts"][0]["text"]

    status, _, raw = request(server, "POST", "/a2a", body)
    duplicate = json.loads(raw)["result"]
    assert status == 200
    assert duplicate["id"] == task["id"]

    wrong_access = {
        "jsonrpc": "2.0",
        "id": "wrong-session",
        "method": "tasks/get",
        "params": {"id": task["id"], "sessionId": second["sessionId"]},
    }
    status, _, raw = request(server, "POST", "/a2a", wrong_access)
    assert status == 200
    assert json.loads(raw)["error"]["code"] == -32602

    right_access = {
        **wrong_access,
        "id": "right-session",
        "params": {"id": task["id"], "sessionId": first["sessionId"]},
    }
    status, _, raw = request(server, "POST", "/a2a", right_access)
    assert status == 200
    assert json.loads(raw)["result"]["id"] == task["id"]

    status, _, raw = request(
        server,
        "POST",
        "/a2a",
        {**right_access, "id": "cancel-task", "method": "tasks/cancel"},
    )
    assert status == 200
    assert json.loads(raw)["result"]["id"] == task["id"]


def test_expired_chat_session_is_rejected_before_a2a(server):
    _, session = _start_chat(server)
    stored = gateway_app._CHAT_SESSIONS.get(session["sessionId"])
    gateway_app._CHAT_SESSIONS._sessions[session["sessionId"]] = stored.model_copy(
        update={"expires_at": datetime.fromtimestamp(0, tz=timezone.utc)}
    )
    status, _, raw = request(
        server,
        "POST",
        "/a2a",
        {"jsonrpc": "2.0", "id": "expired", "method": "message/send", "params": {"message": {"messageId": "expired-msg", "role": "user", "contextId": session["contextId"], "metadata": {"sessionId": session["sessionId"]}, "parts": [{"text": "Get my August bank statement"}]}}},
    )
    assert status == 200
    assert json.loads(raw)["error"]["code"] == -32602


@pytest.fixture
def revision_chat(monkeypatch):
    from a2a import A2ATaskStore
    monkeypatch.setattr(gateway_app, '_A2A_TASKS', A2ATaskStore())
    monkeypatch.setattr(gateway_app, '_CHAT_SESSIONS', gateway_app.ChatSessionStore())
    _, session = gateway_app._handle_chat_session_create({'consentId': 'test-consent', 'scopes': ['chat:send']})
    return {'jsonrpc': '2.0', 'id': 'revision', 'method': 'message/send', 'params': {'message': {
        'role': 'user', 'messageId': 'revision-message', 'contextId': session['contextId'],
        'metadata': {'sessionId': session['sessionId'], 'intentId': 'intent-revision', 'intentRevision': 1},
        'parts': [{'text': 'Get my August bank statement'}]}}}


def test_chat_cancellation_during_dispatch_is_visible_and_blocks_result(revision_chat, monkeypatch):
    message=revision_chat['params']['message']
    def executor(*_):
        task=gateway_app._A2A_TASKS.all()[0]
        _, canceled=gateway_app._handle_a2a_rpc({'jsonrpc':'2.0','id':'cancel','method':'tasks/cancel','params':{'id':task['id'],'sessionId':message['metadata']['sessionId']}})
        assert canceled['result']['metadata']['cancellationRequested'] is True
        return {'secret-result': 'late'}
    monkeypatch.setattr(gateway_app,'_bank_executor',executor)
    _, response=gateway_app._handle_a2a_rpc(revision_chat)
    task=response['result']
    assert task['status']['state']=='canceled'
    assert task['metadata']['completionAuthoritative'] is False
    assert 'secret-result' not in str(task)


def test_chat_revocation_during_dispatch_pauses_and_discards_result(revision_chat, monkeypatch):
    def executor(*_):
        gateway_app._handle_chat_session_revoke(revision_chat['params']['message']['metadata']['sessionId'])
        return {'secret-result':'late'}
    monkeypatch.setattr(gateway_app,'_bank_executor',executor)
    _, response=gateway_app._handle_a2a_rpc(revision_chat)
    task=response['result']
    assert task['status']['state']=='auth-required'
    assert task['metadata']['completionAuthoritative'] is False
    assert 'secret-result' not in str(task)


@pytest.mark.parametrize('method',['message/send','message/stream'])
def test_chat_replay_checks_revision_and_context(revision_chat,method):
    from copy import deepcopy
    gateway_app._handle_a2a_rpc(revision_chat)
    changed=deepcopy(revision_chat); changed['method']=method
    changed['params']['message']['metadata']['intentRevision']=2
    handler=gateway_app._handle_a2a_rpc if method=='message/send' else gateway_app._handle_a2a_stream
    _, response=handler(changed)
    assert response['error']['code']==-32602
    assert 'revision' in response['error']['message']
    changed['params']['message']['metadata']['intentRevision']=1
    session_id=changed['params']['message']['metadata']['sessionId']
    gateway_app._CHAT_SESSIONS.put(gateway_app._CHAT_SESSIONS.get(session_id),'other-context')
    changed['params']['message']['contextId']='other-context'
    _, response=handler(changed)
    assert response['error']['code']==-32602
    assert 'context' in response['error']['message']


def test_chat_stream_replay_does_not_promote_pending_to_terminal(revision_chat):
    revision_chat['method']='message/stream'
    _, first=gateway_app._handle_a2a_stream(revision_chat)
    _, replay=gateway_app._handle_a2a_stream(revision_chat)
    assert first['events'][-1]['terminal'] is False
    assert replay['events'][-1]['terminal'] is False
    assert replay['events'][-1]['task']['metadata']['completionAuthoritative'] is False


def test_legacy_rest_uses_chat_authorization_for_revision_requests(revision_chat,monkeypatch):
    from copy import deepcopy
    calls=[]; monkeypatch.setattr(gateway_app,'_bank_executor',lambda *_: calls.append(True) or {})
    body=deepcopy(revision_chat['params'])
    body['message']['metadata']['tenantId']='forged'
    status,_=gateway_app._handle_a2a_message(body)
    assert status==400 and not calls
    body=deepcopy(revision_chat['params']); body['message']['metadata']['sessionId']='not-owned'
    status,_=gateway_app._handle_a2a_message(body)
    assert status==400 and not calls
    body=deepcopy(revision_chat['params']); body['message']['metadata']['sessionId']=42
    status,_=gateway_app._handle_a2a_message(body)
    assert status==400 and not calls
    status, result=gateway_app._handle_a2a_message(revision_chat['params'])
    assert status==200 and len(calls)==1
    assert result['task']['metadata']['intentRevision']==1
