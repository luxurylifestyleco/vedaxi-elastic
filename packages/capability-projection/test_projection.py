from __future__ import annotations

from types import SimpleNamespace

import pytest

from a2a import A2AClient, A2AInboundAdapter
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
    adapter = MCPAdapter(remote_client=client, provider="remote.example")
    registry = CapabilityRegistry()
    caps = adapter.register(registry)
    assert caps[0].metadata["source"] == "remote-mcp"
    assert caps[0].metadata["source_endpoint"] == "https://mcp.example/mcp"
    assert registry.get_by_id("remote_search") is caps[0]
    assert adapter.executor("remote_search", {"query": "elastic"}) == {
        "matches": ["remote"]
    }
    assert transport.methods[-1] == "tools/call"


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
        )
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
