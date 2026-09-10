"""Tests for the Elastic Web MCP adapter (Phase 7).

Covers discovery, normalization, invocation, and result recording on
:class:`~mcp_adapter.MCPAdapter` against the demo MCP tool registry.
"""

from __future__ import annotations

import pytest

from capability import Capability
from demo_mcp_tools import DEMO_TOOL_REGISTRY, get_demo_tools
from mcp_adapter import ExecutionResult, MCPAdapter


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
    # No explicit registry and no MCP SDK -> demo tools are used.
    adapter = MCPAdapter()
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
