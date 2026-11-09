"""Tests for the Elastic Web MCP adapter (Phase 7).

Covers discovery, normalization, invocation, and result recording on
:class:`~mcp_adapter.MCPAdapter` against the demo MCP tool registry.
"""

from __future__ import annotations

import os
import pytest
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _package in ("intent-ir", "recipe-schema", "recipe-runtime", "capability-retrieval"):
    _path = os.path.join(_REPO_ROOT, "packages", _package)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from capability import Capability
from demo_mcp_tools import DEMO_TOOL_REGISTRY, get_demo_tools
from mcp_adapter import ExecutionResult, MCPAdapter
from registry import CapabilityRegistry
from intent_ir import IntentIR
from runner import RecipeDAGRunner
from recipe import Recipe, RecipeStep
from remote_mcp import RemoteMCPClient
from factory import build_retriever


def _synthetic_remote_transport(payload, headers):
    """Offline MCP JSON-RPC fixture; no socket or provider is contacted."""
    method = payload.get("method")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"protocolVersion": "2025-06-18"}}, {}
    if method == "notifications/initialized":
        return None, {}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {
                "tools": [{
                    "name": "remote_fixture_lookup",
                    "description": "Retrieve a synthetic remote fixture record.",
                    "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
                    "outputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}},
                }]
            },
        }, {"Mcp-Session-Id": "synthetic-session"}
    if method == "tools/call":
        arguments = payload["params"]["arguments"]
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {"structuredContent": {"key": arguments["key"], "value": "synthetic-value"}},
        }, {"Mcp-Session-Id": "synthetic-session"}
    raise AssertionError(f"unexpected synthetic MCP method: {method}")


@pytest.fixture
def adapter() -> MCPAdapter:
    """An adapter pre-configured with the demo tool registry."""
    return MCPAdapter(tool_registry=get_demo_tools())


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------

def test_discovery_returns_capability_objects(adapter: MCPAdapter) -> None:
    caps = adapter.discover()
    assert len(caps) == len(DEMO_TOOL_REGISTRY)
    assert all(isinstance(c, Capability) for c in caps)


def test_discovery_finds_all_demo_tools(adapter: MCPAdapter) -> None:
    caps = adapter.discover()
    names = {c.id for c in caps}
    assert names == {"get_statement", "make_payment", "get_balance", "freeze_card"}


def test_list_capabilities_matches_discovery(adapter: MCPAdapter) -> None:
    adapter.discover()
    listed = adapter.list_capabilities()
    assert len(listed) == len(DEMO_TOOL_REGISTRY)
    assert all(isinstance(c, Capability) for c in listed)


def test_discovery_falls_back_to_demo_registry() -> None:
    # Demo tools are fixtures and require explicit opt-in.
    adapter = MCPAdapter(allow_demo_fixtures=True)
    caps = adapter.discover()
    assert len(caps) == len(DEMO_TOOL_REGISTRY)


# ----------------------------------------------------------------------
# Normalization
# ----------------------------------------------------------------------

def test_normalization_maps_fields(adapter: MCPAdapter) -> None:
    adapter.discover()
    cap = adapter.get_capability("get_balance")
    assert cap is not None
    # tool name -> id
    assert cap.id == "get_balance"
    # description -> description
    assert cap.description == (
        "Retrieve the current available and ledger balance for an account."
    )
    # input schema -> inputs
    assert "account_id" in cap.inputs
    assert cap.inputs["account_id"]["type"] == "string"
    assert cap.inputs["account_id"]["required"] is True
    # output schema -> outputs
    assert cap.outputs["available_balance"] == "number"
    # provider / protocol / endpoint
    assert cap.provider == "mcp"
    assert cap.protocol == "mcp"
    assert cap.endpoint == "get_balance"


def test_normalization_handles_optional_and_defaults(adapter: MCPAdapter) -> None:
    adapter.discover()
    cap = adapter.get_capability("make_payment")
    assert cap is not None
    # required field flagged
    assert cap.inputs["amount"]["required"] is True
    # optional field with default
    assert cap.inputs["currency"]["required"] is False
    assert cap.inputs["currency"]["default"] == "USD"


def test_normalization_humanizes_name(adapter: MCPAdapter) -> None:
    adapter.discover()
    cap = adapter.get_capability("freeze_card")
    assert cap is not None
    assert cap.name == "Freeze Card"


# ----------------------------------------------------------------------
# Invocation
# ----------------------------------------------------------------------

def test_invoke_returns_result_and_records_it(adapter: MCPAdapter) -> None:
    adapter.discover()
    result = adapter.invoke("get_balance", {"account_id": "acc-123"})
    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.tool_name == "get_balance"
    assert result.capability_id == "get_balance"
    assert result.result["account_id"] == "acc-123"
    assert result.result["available_balance"] == 1250.75
    assert result.error is None
    assert result.duration_ms >= 0.0

    # recorded in the execution log
    log = adapter.execution_log()
    assert len(log) == 1
    assert log[0] is result


def test_invoke_records_failures(adapter: MCPAdapter) -> None:
    adapter.discover()
    result = adapter.invoke("make_payment", {"from_account": "a", "to_account": "b", "amount": -5})
    assert result.success is False
    assert result.error is not None
    assert "amount must be positive" in result.error
    assert len(adapter.execution_log()) == 1


def test_invoke_unknown_tool_raises(adapter: MCPAdapter) -> None:
    adapter.discover()
    with pytest.raises(KeyError):
        adapter.invoke("does_not_exist", {})


def test_invoke_auto_discovers(adapter: MCPAdapter) -> None:
    # Invoking before an explicit discover() should still work.
    result = adapter.invoke("freeze_card", {"card_id": "card-9"})
    assert result.success is True
    assert result.result["status"] == "frozen"
    assert len(adapter.list_capabilities()) == len(DEMO_TOOL_REGISTRY)


def test_trusted_remote_fixture_flows_through_registry_retrieval_runner_and_evidence():
    client = RemoteMCPClient(
        "http://127.0.0.1:9/synthetic-mcp",
        trusted=True,
        transport=_synthetic_remote_transport,
    )
    adapter = MCPAdapter(
        remote_client=client,
        provider="synthetic-remote-mcp",
        protocol="mcp",
        domain="synthetic",
        allow_demo_fixtures=False,
    )
    registry = CapabilityRegistry()
    adapter.register(registry)
    capability = registry.get_by_id("remote_fixture_lookup")
    assert capability is not None
    assert capability.metadata["source"] == "remote-mcp"

    intent = IntentIR(
        intent_id="remote-fixture-intent",
        goal="retrieve_synthetic_remote_record",
        domain="synthetic",
        action="retrieve",
        object="remote_fixture_record",
        constraints={"key": "demo"},
        desired_output="json",
        context={"protocol": "mcp"},
    )
    candidate = build_retriever("keyword", registry.list()).retrieve(intent, k=1)
    assert candidate[0].capability_id == "remote_fixture_lookup"

    recipe = Recipe(
        recipe_id="synthetic-remote-recipe",
        intent_family="retrieve_synthetic_remote_record",
        steps=[RecipeStep(step_id="lookup", action="retrieve", capability_id="remote_fixture_lookup")],
    )
    execution = RecipeDAGRunner().run(
        recipe,
        params={"key": "demo"},
        executor=adapter.executor,
    )
    assert execution.success is True
    assert execution.results["lookup"] == {"key": "demo", "value": "synthetic-value"}
    evidence = adapter.execution_log()[0].to_dict()["metadata"]
    assert evidence == {
        "source": "remote-mcp",
        "provider": "synthetic-remote-mcp",
        "protocol": "mcp",
        "endpoint": "http://127.0.0.1:9/synthetic-mcp",
        "trusted": True,
    }


def test_untrusted_remote_provider_fails_closed_before_discovery():
    client = RemoteMCPClient(
        "http://127.0.0.1:9/unknown-mcp",
        trusted=False,
        transport=_synthetic_remote_transport,
    )
    adapter = MCPAdapter(remote_client=client, allow_demo_fixtures=False)
    with pytest.raises(PermissionError, match="not trusted"):
        adapter.discover()


def test_explicitly_trusted_remote_provider_can_discover_without_demo_fallback():
    client = RemoteMCPClient(
        "https://mcp.example/mcp", trusted=True, transport=_synthetic_remote_transport
    )
    adapter = MCPAdapter(
        remote_client=client,
        provider="authorized-remote-provider",
        allow_demo_fixtures=False,
        trusted_remote_provider=True,
    )
    assert adapter.discover()[0].metadata["source"] == "remote-mcp"


def test_unknown_remote_provider_fails_closed_even_when_client_is_trusted():
    client = RemoteMCPClient(
        "http://127.0.0.1:9/unknown-mcp",
        trusted=True,
        transport=_synthetic_remote_transport,
    )
    adapter = MCPAdapter(
        remote_client=client,
        provider="unknown-remote-provider",
        allow_demo_fixtures=False,
    )
    with pytest.raises(PermissionError, match="provider is not trusted"):
        adapter.discover()
