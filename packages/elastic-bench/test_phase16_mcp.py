"""Phase 16 — MCP adapter tests.

Verifies that the MCP adapter (mcp_adapter.py, demo_mcp_tools.py) discovers
and invokes tools, normalizes them into Capability objects, and records
execution results.
"""

from __future__ import annotations

import os
import sys

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("capability-registry",):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

from capability import Capability  # noqa: E402
from demo_mcp_tools import DEMO_TOOL_REGISTRY, MCPTool, get_demo_tools  # noqa: E402
from mcp_adapter import ExecutionResult, MCPAdapter  # noqa: E402


@pytest.fixture
def adapter() -> MCPAdapter:
    return MCPAdapter(tool_registry=get_demo_tools())


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discovery_returns_capabilities(adapter):
    caps = adapter.discover()
    assert len(caps) == len(DEMO_TOOL_REGISTRY)
    assert all(isinstance(c, Capability) for c in caps)


def test_discovery_finds_all_demo_tools(adapter):
    names = {c.id for c in adapter.discover()}
    assert names == {"get_statement", "make_payment", "get_balance", "freeze_card"}


def test_discovery_falls_back_to_demo_registry():
    adapter = MCPAdapter()
    assert len(adapter.discover()) == len(DEMO_TOOL_REGISTRY)


def test_get_capability_returns_none_for_unknown(adapter):
    adapter.discover()
    assert adapter.get_capability("does_not_exist") is None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalization_maps_fields(adapter):
    adapter.discover()
    cap = adapter.get_capability("get_balance")
    assert cap is not None
    assert cap.id == "get_balance"
    assert cap.provider == "mcp"
    assert cap.protocol == "mcp"
    assert cap.endpoint == "get_balance"
    assert cap.inputs["account_id"]["type"] == "string"
    assert cap.inputs["account_id"]["required"] is True
    assert cap.outputs["available_balance"] == "number"


def test_normalization_humanizes_name(adapter):
    adapter.discover()
    assert adapter.get_capability("freeze_card").name == "Freeze Card"


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def test_invoke_returns_result_and_records(adapter):
    adapter.discover()
    result = adapter.invoke("get_balance", {"account_id": "acc-123"})
    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.result["account_id"] == "acc-123"
    assert result.error is None
    assert len(adapter.execution_log()) == 1


def test_invoke_auto_discovers(adapter):
    result = adapter.invoke("freeze_card", {"card_id": "card-9"})
    assert result.success is True
    assert result.result["status"] == "frozen"


def test_invoke_records_failure(adapter):
    adapter.discover()
    result = adapter.invoke("make_payment", {"from_account": "a", "to_account": "b", "amount": -5})
    assert result.success is False
    assert "amount must be positive" in result.error


def test_invoke_unknown_tool_raises(adapter):
    adapter.discover()
    with pytest.raises(KeyError):
        adapter.invoke("does_not_exist", {})


def test_invoke_tool_without_callable_returns_failure():
    tool = MCPTool(
        name="no_callable",
        description="A tool with no callable.",
        input_schema={"type": "object", "properties": {}},
        callable=None,
    )
    adapter = MCPAdapter(tool_registry=[tool])
    adapter.discover()
    result = adapter.invoke("no_callable", {})
    assert result.success is False
    assert "no callable" in result.error
