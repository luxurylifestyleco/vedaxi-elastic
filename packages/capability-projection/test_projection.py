from __future__ import annotations

from types import SimpleNamespace

import pytest

from a2a import (
    A2AClient,
    A2AContentTypeNotSupportedError,
    A2AInboundAdapter,
    A2ATaskStore,
    PostgresA2ATaskStore,
    SQLiteA2ATaskStore,
)
from capability import Capability
from discovery import (
    agent_card,
    agents_json,
    agents_txt,
    negotiate_ucp_capabilities,
    ucp_profile,
)
from intent_ir import IntentIR
from mcp_adapter import MCPAdapter
from factory import build_retriever
from projection import (
    project,
    to_a2a_skill,
    to_mcp_tool,
    to_ucp_capability,
    to_webmcp_tool,
)
from registry import CapabilityRegistry
from remote_mcp import MCP_PROTOCOL_VERSION, RemoteMCPClient
from runner import RecipeDAGRunner
from telemetry import EventBus, ListSubscriber, TelemetryRecorder


class _FakePostgres:
    def __init__(self):
        self.rows = {}
        self.calls = []

    def connect(self, _dsn):
        owner = self
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params=()):
                owner.calls.append((sql, params))
                if sql.startswith("INSERT INTO public.a2a_tasks"):
                    keys = ("task_id", "tenant_id", "principal_id", "session_id", "context_id", "message_id", "intent_id", "trace_id", "outcome_id", "evidence_id", "verification_id", "state", "cancel_state")
                    owner.rows[params[0]] = dict(zip(keys, params))
                elif sql.startswith("SELECT"):
                    self.result = None
                    if "WHERE task_id" in sql:
                        row = owner.rows.get(params[0])
                        self.result = row if row and row["tenant_id"] == params[1] else None
                    elif "WHERE message_id" in sql:
                        self.result = next((row for row in owner.rows.values() if row["message_id"] == params[0] and row["session_id"] == params[1] and row["tenant_id"] == params[2]), None)
            def fetchone(self): return self.result
            def fetchall(self): return list(owner.rows.values())
        class Connection:
            def cursor(self): return Cursor()
            def commit(self): pass
            def rollback(self): pass
            def close(self): pass
        return Connection()


def test_postgres_task_store_preserves_tenant_idempotency_and_cancel_state():
    fake = _FakePostgres()
    store = PostgresA2ATaskStore("postgresql://test", fake.connect)
    task = {"id": "task-1", "contextId": "ctx-1", "status": {"state": "TASK_STATE_SUBMITTED"},
            "metadata": {"tenantId": "tenant-1", "principalId": "principal-1", "sessionId": "session-1",
                         "messageId": "message-1", "traceId": "trace-1"}}
    store.put(task)
    assert fake.calls[0] == (
        "SELECT set_config('app.tenant_id', %s, true)",
        ("tenant-1",),
    )
    assert store.get_by_message(
        "message-1", "session-1", tenant_id="tenant-1"
    )["metadata"]["tenantId"] == "tenant-1"
    assert store.get("task-1", tenant_id="tenant-2") is None
    canceled = store.cancel("task-1", tenant_id="tenant-1")
    assert canceled["status"]["state"] == "canceled"
    assert fake.rows["task-1"]["cancel_state"] == "canceled"


def test_postgres_task_store_requires_scoped_configuration():
    with pytest.raises(ValueError):
        PostgresA2ATaskStore("")
    with pytest.raises(ValueError):
        PostgresA2ATaskStore("postgresql://test", lambda _: None).put({"id": "unscoped"})
    fake = _FakePostgres()
    store = PostgresA2ATaskStore("postgresql://test", fake.connect)
    with pytest.raises(ValueError):
        store.get("task-1")


def capability(**changes):
    values = {
        "id": "search_products",
        "name": "Search Products",
        "description": "Search the product catalog.",
        "domain": "commerce",
        "inputs": {"query": "string"},
        "outputs": {"items": "array"},
        "permissions": ["catalog:read"],
        "provider": "shop",
        "protocol": "rest",
        "endpoint": "/products/search",
        "metadata": {
            "source": "public-catalog",
            "commerce_operation": "product_search",
            "ucp_enabled": True,
            "ucp_service_endpoint": "https://elastic.example/ucp/v1",
        },
    }
    values.update(changes)
    return Capability(**values)


def test_capability_projects_to_a2a_and_mcp_without_losing_identity():
    cap = capability()
    a2a = to_a2a_skill(cap)
    mcp = to_mcp_tool(cap)
    assert a2a["id"] == mcp["name"] == cap.id
    assert mcp["inputSchema"]["properties"]["query"]["type"] == "string"
    assert mcp["_meta"]["elastic"]["provider"] == "shop"


def test_webmcp_projection_is_explicitly_metadata_only_and_fail_closed():
    tool = to_webmcp_tool(capability())
    assert tool["capabilityId"] == "search_products"
    assert tool["webmcp"] == {
        "api": "document.modelContext",
        "registration": "metadata-only",
        "execution": "unavailable",
        "failClosed": True,
    }
    assert "execute" not in tool


def test_discovery_and_agent_card_are_generated_from_enabled_capabilities():
    caps = [capability()]
    card = agent_card(caps, "https://elastic.example")
    text = agents_txt(caps, "https://elastic.example", "https://web.example/tools")
    structured = agents_json(caps, "https://elastic.example", "https://web.example/tools")
    assert card["skills"][0]["id"] == "search_products"
    assert "MCP: https://elastic.example/mcp" in text
    assert "A2A: https://elastic.example/.well-known/agent-card.json" in text
    assert "WebMCP: https://web.example/tools" in text
    assert structured["webmcp"] == [
        {
            "url": "https://web.example/tools",
            "transport": "browser-boundary",
            "status": "metadata-only",
            "execution": "unavailable",
        }
    ]
    assert "UCP: https://elastic.example/.well-known/ucp" in text
    assert structured["mcp"][0]["transport"] == "streamable-http"
    assert structured["a2a"][0]["url"].endswith("agent-card.json")


def test_agent_card_uses_v1_interfaces_and_does_not_claim_unsupported_features():
    card = agent_card([capability()], "https://elastic.example", version="2.4.0")
    assert card["version"] == "2.4.0"
    assert "protocolVersion" not in card
    assert "additionalInterfaces" not in card
    assert card["supportedInterfaces"] == [
        {
            "url": "https://elastic.example/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        },
        {
            "url": "https://elastic.example",
            "protocolBinding": "HTTP+JSON",
            "protocolVersion": "1.0",
        },
    ]
    assert card["capabilities"] == {
        "streaming": True,
        "pushNotifications": False,
    }
    assert card["skills"][0]["tags"] == ["commerce", "rest"]


def test_webmcp_is_not_discovered_without_explicit_boundary_url():
    assert "webmcp" not in agents_json([capability()], "https://elastic.example")


def test_ucp_accepts_only_supported_commerce_capabilities():
    projected = to_ucp_capability(capability())
    assert projected["name"] == "dev.ucp.shopping.catalog.search"
    assert projected["version"] == "2026-08-25"
    assert projected["schema"].endswith("/schemas/shopping/catalog_search.json")
    with pytest.raises(ValueError, match="not eligible"):
        to_ucp_capability(capability(domain="research", metadata={}))


def test_ucp_fails_closed_for_unimplemented_checkout_and_missing_opt_in():
    with pytest.raises(ValueError, match="not eligible"):
        to_ucp_capability(
            capability(
                metadata={"commerce_operation": "checkout", "ucp_enabled": True}
            )
        )
    with pytest.raises(ValueError, match="not eligible"):
        to_ucp_capability(
            capability(
                metadata={"commerce_operation": "product_search"}
            )
        )


def test_ucp_profile_has_required_registries_and_negotiates_exact_capabilities():
    business = ucp_profile([capability()], "https://business.example")
    platform = ucp_profile([capability()], "https://platform.example")
    assert business["ucp"]["services"]["dev.ucp.shopping"][0]["transport"] == "rest"
    assert business["ucp"]["payment_handlers"] == {}
    result = negotiate_ucp_capabilities(business, platform)
    assert result["ucp"]["version"] == "2026-08-25"
    assert "dev.ucp.shopping.catalog.search" in result["ucp"]["capabilities"]


def test_ucp_negotiation_rejects_version_mismatch():
    business = ucp_profile([capability()], "https://business.example")
    platform = ucp_profile([capability()], "https://platform.example")
    platform["ucp"]["version"] = "2026-01-23"
    with pytest.raises(ValueError, match="exact UCP protocol version"):
        negotiate_ucp_capabilities(business, platform)


def test_dummy_protocol_needs_only_an_adapter():
    cap = capability()
    assert project(cap, lambda value: {"dummy": value.id}) == {
        "dummy": "search_products"
    }


class _Compiler:
    def compile(self, _text):
        return IntentIR(
            intent_id="intent-1",
            goal="search_catalog",
            domain="commerce",
            action="search",
            object="products",
            desired_output="json",
        )


class _Retriever:
    def retrieve(self, _intent, k=1):
        assert k == 1
        return [SimpleNamespace(capability_id="search_products")]


def test_a2a_request_runs_through_elastic_runtime_and_keeps_protocol_metadata():
    cap = capability()
    bus = EventBus()
    events = ListSubscriber()
    bus.subscribe(events)
    recorder = TelemetryRecorder(bus)
    calls = []
    adapter = A2AInboundAdapter(
        compiler=_Compiler(),
        retriever=_Retriever(),
        capability_by_id=lambda value: cap if value == cap.id else None,
        runner=RecipeDAGRunner(bus=bus),
        executor=lambda cap_id, args: calls.append((cap_id, args)) or {"items": []},
        bus=bus,
        source_endpoint="https://elastic.example/message:send",
    )
    response = adapter.handle(
        {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_USER",
                "parts": [{"text": "Find red shoes"}, {"data": {"query": "red shoes"}}],
            }
        }
    )
    assert response["task"]["status"]["state"] == "TASK_STATE_WORKING"
    assert calls == [("search_products", {"query": "red shoes"})]
    record = recorder.get(response["task"]["metadata"]["traceId"])
    assert record is not None
    assert record.outcome is None
    assert record.protocol_metadata["source_protocol"] == "a2a"
    selected = next(event for event in events.events if event.event_type.value == "capability.selected")
    assert selected.payload["protocol"]["source_protocol"] == "a2a"
    assert selected.payload["protocol"]["source_endpoint"].endswith("/message:send")
    assert selected.payload["capability_id"] == "search_products"
    assert "outcome.delivered" not in [event.event_type.value for event in events.events]
    assert "evaluation.completed" in [event.event_type.value for event in events.events]
    metadata = response["task"]["metadata"]
    assert metadata["outcomeStatus"] == "PARTIALLY_COMPLETED"
    assert metadata["verificationStatus"] == "INSUFFICIENT"
    assert metadata["completionAuthoritative"] is False


def test_a2a_request_preserves_correlation_from_intent_through_verification():
    cap = capability()
    bus = EventBus()
    events = ListSubscriber()
    bus.subscribe(events)
    adapter = A2AInboundAdapter(
        compiler=_Compiler(),
        retriever=_Retriever(),
        capability_by_id=lambda value: cap if value == cap.id else None,
        runner=RecipeDAGRunner(bus=bus),
        executor=lambda _cap_id, _args: {"items": []},
        bus=bus,
        source_endpoint="https://elastic.example/message:send",
    )

    task = adapter.handle(
        {
            "message": {
                "messageId": "correlation-1",
                "role": "ROLE_USER",
                "parts": [{"text": "Find red shoes"}],
            }
        }
    )["task"]

    metadata = task["metadata"]
    evaluation = next(
        event for event in events.events if event.event_type.value == "evaluation.completed"
    )
    execution_events = [
        event
        for event in events.events
        if event.event_type.value in {"recipe.started", "tool.called", "tool.completed"}
    ]

    assert metadata["intentId"] == "intent-1"
    assert metadata["traceId"] == evaluation.trace_id
    assert evaluation.intent_id == metadata["intentId"]
    assert evaluation.outcome_id == metadata["outcomeId"]
    assert evaluation.evidence_id == metadata["evidenceId"]
    assert evaluation.verification_id == f"verification-{metadata['traceId']}"
    assert evaluation.payload["outcome_id"] == metadata["outcomeId"]
    assert evaluation.payload["evidence_id"] == metadata["evidenceId"]
    assert evaluation.payload["verification_id"] == metadata["verificationId"]
    assert all(
        event.trace_id == metadata["traceId"] and event.intent_id == metadata["intentId"]
        for event in execution_events
    )


def test_a2a_chat_task_bridge_is_multiturn_idempotent_and_human_readable():
    cap = capability()
    calls = []
    store = A2ATaskStore()
    adapter = A2AInboundAdapter(
        compiler=_Compiler(),
        retriever=_Retriever(),
        capability_by_id=lambda value: cap if value == cap.id else None,
        runner=RecipeDAGRunner(bus=EventBus()),
        executor=lambda cap_id, args: calls.append((cap_id, args)) or {"items": []},
        bus=EventBus(),
        source_endpoint="https://elastic.example/a2a",
        task_store=store,
    )
    first = adapter.handle({
        "message": {
            "messageId": "chat-1",
            "contextId": "ctx-1",
            "role": "user",
            "metadata": {"sessionId": "sess-1"},
            "parts": [{"text": "Find red shoes"}],
        }
    })["task"]
    follow_up = adapter.handle({
        "message": {
            "messageId": "chat-2",
            "contextId": "ctx-1",
            "role": "user",
            "metadata": {"sessionId": "sess-1"},
            "parts": [{"text": "Find blue shoes"}],
        }
    })["task"]
    duplicate = adapter.handle({
        "message": {
            "messageId": "chat-1",
            "contextId": "ctx-1",
            "role": "user",
            "metadata": {"sessionId": "sess-1"},
            "parts": [{"text": "Find red shoes"}],
        }
    })["task"]

    assert first["contextId"] == follow_up["contextId"] == "ctx-1"
    assert first["id"] != follow_up["id"]
    assert duplicate["id"] == first["id"]
    assert len(calls) == 2
    assert first["metadata"]["sessionId"] == "sess-1"
    assert first["metadata"]["messageId"] == "chat-1"
    assert first["artifacts"][0]["parts"][0]["text"] == (
        "The request executed, but verification is incomplete."
    )
    assert first["artifacts"][0]["parts"][1]["mediaType"] == "application/json"
    with pytest.raises(ValueError, match="another context"):
        adapter.handle({
            "message": {
                "messageId": "chat-1",
                "contextId": "ctx-2",
                "role": "user",
                "metadata": {"sessionId": "sess-1"},
                "parts": [{"text": "Find red shoes"}],
            }
        })


def test_sqlite_a2a_store_survives_restart_and_preserves_idempotency(tmp_path):
    path = str(tmp_path / "chat.sqlite")
    task = {
        "id": "task-1",
        "contextId": "ctx-1",
        "status": {"state": "TASK_STATE_SUBMITTED"},
        "metadata": {
            "tenantId": "tenant-1",
            "sessionId": "session-1",
            "messageId": "message-1",
        },
    }
    first = SQLiteA2ATaskStore(path)
    first.put(task)
    first.close()

    second = SQLiteA2ATaskStore(path)
    assert second.get("task-1") == task
    assert second.get_by_message("message-1", "session-1") == task
    canceled = second.cancel("task-1")
    assert canceled["status"]["state"] == "TASK_STATE_CANCELED"
    assert canceled["metadata"]["cancelState"] == "canceled"
    second.close()


def test_sqlite_a2a_store_keeps_tenant_metadata_and_session_ownership(tmp_path):
    store = SQLiteA2ATaskStore(str(tmp_path / "chat.sqlite"))
    first = {
        "id": "task-tenant-a",
        "contextId": "ctx-a",
        "status": {"state": "TASK_STATE_SUBMITTED"},
        "metadata": {"tenantId": "tenant-a", "sessionId": "session-a", "messageId": "same-message"},
    }
    second = {
        "id": "task-tenant-b",
        "contextId": "ctx-b",
        "status": {"state": "TASK_STATE_SUBMITTED"},
        "metadata": {"tenantId": "tenant-b", "sessionId": "session-b", "messageId": "same-message"},
    }
    store.put(first)
    store.put(second)

    assert store.get("task-tenant-a")["metadata"]["tenantId"] == "tenant-a"
    assert store.get_by_message("same-message", "session-a") == first
    assert store.get_by_message("same-message", "session-b") == second
    assert store.get_by_message("same-message", "other-session") is None
    store.close()


def test_sqlite_a2a_store_requires_explicit_durable_configuration():
    with pytest.raises(ValueError, match="database path"):
        SQLiteA2ATaskStore("")


def test_sqlite_a2a_store_does_not_change_terminal_tasks(tmp_path):
    store = SQLiteA2ATaskStore(str(tmp_path / "chat.sqlite"))
    task = {
        "id": "task-terminal",
        "contextId": "ctx-1",
        "status": {"state": "TASK_STATE_COMPLETED"},
        "metadata": {"tenantId": "tenant-1", "sessionId": "session-1"},
    }
    store.put(task)
    assert store.cancel(task["id"]) == task
    store.close()


def test_a2a_local_stream_does_not_call_pending_verification_terminal():
    cap = capability()
    adapter = A2AInboundAdapter(
        compiler=_Compiler(),
        retriever=_Retriever(),
        capability_by_id=lambda value: cap if value == cap.id else None,
        runner=RecipeDAGRunner(bus=EventBus()),
        executor=lambda _cap_id, _args: {"items": []},
        bus=EventBus(),
        source_endpoint="https://elastic.example/a2a",
    )

    events = adapter.stream({
        "message": {
            "messageId": "stream-1",
            "role": "user",
            "parts": [{"text": "Find red shoes"}],
        }
    })

    assert [event["type"] for event in events] == ["task.status", "task.status"]
    assert events[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert events[0]["terminal"] is False
    assert events[0]["task"]["id"] == events[1]["task"]["id"]
    assert events[1]["terminal"] is False
    assert events[1]["task"]["metadata"]["completionAuthoritative"] is False


def test_a2a_rejects_unsupported_media_before_compilation():
    adapter = A2AInboundAdapter(
        compiler=_Compiler(),
        retriever=_Retriever(),
        capability_by_id=lambda _value: None,
        runner=RecipeDAGRunner(bus=EventBus()),
        executor=lambda _cap_id, _args: {},
        bus=EventBus(),
        source_endpoint="https://elastic.example/a2a",
    )

    with pytest.raises(A2AContentTypeNotSupportedError):
        adapter.handle({
            "message": {
                "messageId": "unsupported-media",
                "role": "user",
                "parts": [{"raw": "dGNr", "mediaType": "application/x-unsupported"}],
            }
        })


def test_a2a_canonical_task_normalizes_all_protocol_states():
    from a2a import _canonical_task

    expected = {
        "TASK_STATE_SUBMITTED": "submitted",
        "TASK_STATE_WORKING": "working",
        "TASK_STATE_INPUT_REQUIRED": "input-required",
        "TASK_STATE_AUTH_REQUIRED": "auth-required",
        "TASK_STATE_COMPLETED": "completed",
        "TASK_STATE_FAILED": "failed",
        "TASK_STATE_CANCELED": "canceled",
        "TASK_STATE_REJECTED": "rejected",
    }
    for wire_state, canonical_state in expected.items():
        task = _canonical_task({"id": "task", "status": {"state": wire_state}})
        assert task["status"]["state"] == canonical_state


def test_a2a_stream_rejects_unsupported_push_configuration():
    cap = capability()
    adapter = A2AInboundAdapter(
        compiler=_Compiler(),
        retriever=_Retriever(),
        capability_by_id=lambda value: cap if value == cap.id else None,
        runner=RecipeDAGRunner(bus=EventBus()),
        executor=lambda _cap_id, _args: {"items": []},
        bus=EventBus(),
        source_endpoint="https://elastic.example/a2a",
    )

    with pytest.raises(NotImplementedError, match="push notification"):
        adapter.stream({"message": {}}, push_config={"url": "https://client.example/hook"})

    with pytest.raises(PermissionError, match="not trusted"):
        A2AClient("https://agent.example").stream("hello")


class _RemoteTransport:
    def __init__(self, fail_call=False):
        self.methods = []
        self.fail_call = fail_call

    def __call__(self, payload, _headers):
        method = payload["method"]
        self.methods.append(method)
        if method == "notifications/initialized":
            return None, {}
        if method == "initialize":
            result = {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "remote_search",
                        "title": "Remote Search",
                        "description": "Search remotely.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    }
                ]
            }
        elif method == "tools/call" and self.fail_call:
            return {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -1}}, {}
        else:
            result = {"structuredContent": {"matches": ["remote"]}, "isError": False}
        return {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}, {
            "Mcp-Session-Id": "session-1"
        }


def test_remote_mcp_discovers_registers_and_invokes_without_demo_fallback():
    transport = _RemoteTransport()
    client = RemoteMCPClient(
        "https://mcp.example/mcp", trusted=True, transport=transport
    )
    adapter = MCPAdapter(
        remote_client=client, provider="synthetic-remote-mcp"
    )
    registry = CapabilityRegistry()
    caps = adapter.register(registry)
    assert caps[0].metadata["source"] == "remote-mcp"
    assert caps[0].metadata["source_endpoint"] == "https://mcp.example/mcp"
    assert registry.get_by_id("remote_search") is caps[0]
    assert adapter.executor("remote_search", {"query": "elastic"}) == {
        "matches": ["remote"]
    }
    assert transport.methods[-1] == "tools/call"


def test_synthetic_provider_conformance_is_local_and_unverified_without_receipt():
    """Prove the trusted fixture path; local execution is not provider proof."""
    transport = _RemoteTransport()
    client = RemoteMCPClient(
        "https://mcp.example/mcp", trusted=True, transport=transport
    )
    adapter = MCPAdapter(
        remote_client=client,
        provider="synthetic-remote-mcp",
        domain="synthetic",
        allow_demo_fixtures=False,
    )
    registry = CapabilityRegistry()
    adapter.register(registry)
    canonical = registry.get_by_id("remote_search")
    assert canonical is not None
    assert canonical.metadata["source"] == "remote-mcp"
    assert canonical.provider == "synthetic-remote-mcp"

    class _SyntheticCompiler:
        def compile(self, _text):
            return IntentIR(
                intent_id="synthetic-conformance-intent",
                goal="search remote",
                domain="synthetic",
                action="search",
                object="remote record",
                constraints={"query": "elastic"},
                desired_output="json",
                context={"protocol": "mcp"},
            )

    bus = EventBus()
    events = ListSubscriber()
    bus.subscribe(events)
    inbound = A2AInboundAdapter(
        compiler=_SyntheticCompiler(),
        retriever=build_retriever("keyword", registry.list()),
        capability_by_id=registry.get_by_id,
        runner=RecipeDAGRunner(bus=bus),
        executor=adapter.executor,
        bus=bus,
        source_endpoint="https://elastic.example/message:send",
    )

    task = inbound.handle(
        {
            "message": {
                "messageId": "synthetic-conformance-message",
                "role": "user",
                "parts": [{"text": "Search remote record"}, {"data": {"query": "elastic"}}],
            }
        }
    )["task"]

    assert task["status"]["state"] == "TASK_STATE_WORKING"
    assert task["metadata"]["outcomeStatus"] == "PARTIALLY_COMPLETED"
    assert task["metadata"]["verificationStatus"] == "INSUFFICIENT"
    assert task["metadata"]["completionAuthoritative"] is False
    evaluation = next(
        event for event in events.events if event.event_type.value == "evaluation.completed"
    )
    assert evaluation.payload["evidence_id"] == task["metadata"]["evidenceId"]
    assert evaluation.payload["verification_id"] == task["metadata"]["verificationId"]
    evidence = adapter.execution_log()[0]
    assert evidence.result == {"matches": ["remote"]}
    assert evidence.metadata == {
        "source": "remote-mcp",
        "provider": "synthetic-remote-mcp",
        "protocol": "mcp",
        "endpoint": "https://mcp.example/mcp",
        "trusted": True,
    }
    assert transport.methods.count("tools/list") == 1
    assert transport.methods.count("tools/call") == 1


def test_remote_mcp_requires_trust_and_failure_never_uses_demo_execution():
    with pytest.raises(PermissionError, match="not trusted"):
        MCPAdapter(
            remote_client=RemoteMCPClient(
                "https://mcp.example/mcp", transport=_RemoteTransport()
            )
        ).discover()

    transport = _RemoteTransport(fail_call=True)
    adapter = MCPAdapter(
        remote_client=RemoteMCPClient(
            "https://mcp.example/mcp", trusted=True, transport=transport
        ),
        provider="synthetic-remote-mcp",
    )
    adapter.discover()
    result = adapter.invoke("remote_search", {"query": "elastic"})
    assert result.success is False
    assert result.result is None
    assert "remote MCP tools/call failed" in result.error
    assert transport.methods.count("tools/call") == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com/mcp",
        "http://localhost.evil.example/mcp",
        "http://127.0.0.1.evil.example/mcp",
    ],
)
def test_remote_mcp_rejects_non_loopback_http(endpoint):
    with pytest.raises(ValueError, match="must use HTTPS"):
        RemoteMCPClient(endpoint, trusted=True)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_outbound_protocols_allow_exact_loopback_http(host):
    RemoteMCPClient(f"http://{host}/mcp", trusted=True, transport=_RemoteTransport())
    A2AClient(f"http://{host}", trusted=True, transport=lambda *_: {})


def test_a2a_requires_trust_and_https_for_remote_hosts():
    with pytest.raises(PermissionError, match="not trusted"):
        A2AClient("https://agent.example").send("hello")
    with pytest.raises(ValueError, match="must use HTTPS"):
        A2AClient("http://localhost.evil.example", trusted=True)


def test_a2a_client_supports_jsonrpc_task_polling_and_cancel():
    requests = []

    def transport(url, payload, _headers):
        requests.append((url, payload))
        return {"jsonrpc": "2.0", "id": payload["id"], "result": {"ok": True}}

    client = A2AClient("https://agent.example/a2a", trusted=True, transport=transport)
    client.send("hello")
    client.get_task("task-1")
    client.cancel_task("task-1")

    assert [payload["method"] for _, payload in requests] == [
        "message/send", "tasks/get", "tasks/cancel"
    ]
    assert all(url == "https://agent.example/a2a" for url, _ in requests)
