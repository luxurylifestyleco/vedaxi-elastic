"""Phase 16 — Failure cases.

Every failure mode must fail GRACEFULLY (raise a typed exception or return
a failure result) rather than crash the process. Where the underlying code
does NOT handle a case gracefully, the test documents that as a finding by
asserting the actual (non-graceful) behavior explicitly.

Failure modes covered:
  1. missing capability   — invoke a capability id with no backing bank fn
  2. wrong arguments      — pass invalid args to a bank function
  3. tool timeout         — simulate a timeout in a tool call
  4. recipe step failure  — a recipe step that fails
  5. MCP unavailable      — adapter with no tools / SDK not importable
  6. ambiguous intent    — an intent matching multiple capabilities
  7. unknown intent       — Control C raises ValueError
"""

from __future__ import annotations

import os
import sys
import time

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("intent-ir", "capability-registry", "capability-retrieval", "recipe-schema", "telemetry"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

import bank  # noqa: E402
from agent_common import invoke  # noqa: E402
from capability import Capability  # noqa: E402
from control_a import BaselineAgent  # noqa: E402
from control_b import RetrievalAgent  # noqa: E402
import control_c  # noqa: E402
from demo_mcp_tools import MCPTool  # noqa: E402
from factory import build_retriever  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402
from mcp_adapter import MCPAdapter  # noqa: E402
from recipe import Recipe, RecipeStep  # noqa: E402
from store import RecipeStore  # noqa: E402


@pytest.fixture(scope="module")
def capabilities():
    return build_manifest()


def _intent(goal="get_statement", domain="statements/documents", action="retrieve",
            object="statement", desired_output="pdf", **kw) -> IntentIR:
    return IntentIR(
        intent_id="fail-1",
        goal=goal,
        domain=domain,
        action=action,
        object=object,
        desired_output=desired_output,
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. Missing capability — no backing bank function
# ---------------------------------------------------------------------------


def test_missing_capability_invoke_raises_attribute_error():
    """invoke() on a capability with no bank function raises AttributeError."""
    cap = Capability(
        id="no_such_bank_function",
        name="Missing",
        description="A capability with no backing bank function.",
        domain="accounts",
    )
    with pytest.raises(AttributeError):
        invoke(cap, _intent())


def test_missing_capability_agent_records_failure(capabilities):
    """Control A/B catch the missing-capability error and report success=False."""
    caps = list(capabilities) + [
        Capability(
            id="no_such_bank_function",
            name="Missing",
            description="A capability with no backing bank function.",
            domain="accounts",
        )
    ]
    agent = BaselineAgent(caps)
    result = agent.run(_intent(goal="no_such_bank_function"), caps)
    assert result["success"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# 2. Wrong arguments — invalid args to a bank function
# ---------------------------------------------------------------------------


def test_wrong_arguments_raise_typed_error():
    """get_statement with a malformed period raises ValueError."""
    with pytest.raises(ValueError):
        bank.get_statement(period="not-a-date")


def test_wrong_arguments_mcp_adapter_records_failure():
    """The MCP adapter records a wrong-argument call as a graceful failure."""
    adapter = MCPAdapter(tool_registry=[
        MCPTool(
            name="get_statement",
            description="Retrieve a statement.",
            input_schema={"type": "object", "properties": {}},
            callable=bank.get_statement,
        )
    ])
    adapter.discover()
    result = adapter.invoke("get_statement", {"period": "not-a-date"})
    assert result.success is False
    assert result.error is not None
    assert "ValueError" in result.error


# ---------------------------------------------------------------------------
# 3. Tool timeout — simulated timeout in a tool call
# ---------------------------------------------------------------------------


def test_tool_timeout_is_recorded_as_failure():
    """A tool that times out (raises TimeoutError) is recorded, not a crash."""
    def slow_tool(**kwargs):
        time.sleep(0.05)
        raise TimeoutError("tool timed out after 50ms")

    adapter = MCPAdapter(tool_registry=[
        MCPTool(
            name="slow_tool",
            description="A tool that times out.",
            input_schema={"type": "object", "properties": {}},
            callable=slow_tool,
        )
    ])
    adapter.discover()
    result = adapter.invoke("slow_tool", {})
    assert result.success is False
    assert "TimeoutError" in result.error
    assert result.duration_ms >= 0.0
    # The adapter survived and recorded the failure.
    assert len(adapter.execution_log()) == 1


def test_tool_timeout_does_not_crash_adapter():
    """Invoking a timing-out tool must not raise out of the adapter."""
    def slow_tool(**kwargs):
        time.sleep(0.05)
        raise TimeoutError("timeout")

    adapter = MCPAdapter(tool_registry=[
        MCPTool(name="slow_tool", description="times out",
                input_schema={"type": "object", "properties": {}}, callable=slow_tool)
    ])
    adapter.discover()
    # No exception propagates.
    result = adapter.invoke("slow_tool", {})
    assert result.success is False


# ---------------------------------------------------------------------------
# 4. Recipe step failure
# ---------------------------------------------------------------------------


def test_recipe_step_failure_raises_from_store():
    """RecipeStore.execute re-raises a failing step's exception."""
    store = RecipeStore()
    store.create(Recipe(
        recipe_id="r",
        intent_family="f",
        steps=[RecipeStep(step_id="s1", action="a", capability_id="boom")],
    ))

    def failing_executor(capability_id, args):
        raise RuntimeError("step failed")

    with pytest.raises(RuntimeError):
        store.execute("r", executor=failing_executor)


def test_recipe_step_failure_control_c_returns_graceful_failure():
    """Control C catches a failing recipe step and returns success=False."""
    harness = control_c.ControlC()
    # Override the store's executor path by registering a recipe whose step
    # capability has no backing bank function -> _bank_executor raises.
    store = RecipeStore()
    store.create(Recipe(
        recipe_id="broken.recipe",
        intent_family="broken_family",
        steps=[RecipeStep(step_id="s1", action="a", capability_id="no_such_bank_fn")],
    ))
    harness.store = store
    result = harness.run({"intent_family": "broken_family"})
    assert result["metrics"]["success"] is False
    assert "error" in result
    assert result["results"] == {}


# ---------------------------------------------------------------------------
# 5. MCP unavailable — no tools / SDK not importable
# ---------------------------------------------------------------------------


def test_mcp_adapter_with_no_tools_discovers_empty():
    """An adapter with an empty registry discovers zero capabilities."""
    adapter = MCPAdapter(tool_registry=[])
    caps = adapter.discover()
    assert caps == []
    assert len(adapter) == 0


def test_mcp_adapter_with_no_tools_invoke_raises_keyerror():
    """Invoking on an empty adapter raises KeyError (graceful, typed)."""
    adapter = MCPAdapter(tool_registry=[])
    adapter.discover()
    with pytest.raises(KeyError):
        adapter.invoke("anything", {})


def test_mcp_sdk_unavailable_falls_back_to_demo(monkeypatch):
    """If the MCP SDK is not importable, the adapter falls back to demo tools."""
    adapter = MCPAdapter()
    # Force the SDK path to report unavailability.
    monkeypatch.setattr(adapter, "_discover_from_mcp_sdk", lambda: None)
    caps = adapter.discover()
    assert len(caps) == 4  # demo registry


# ---------------------------------------------------------------------------
# 6. Ambiguous intent — matches multiple capabilities
# ---------------------------------------------------------------------------


def test_ambiguous_intent_returns_multiple_candidates(capabilities):
    """An intent matching several capabilities returns >1 candidate, no crash."""
    retriever = build_retriever("keyword", capabilities)
    # A generic 'get account' intent matches many account capabilities.
    intent = _intent(goal="get_account", domain="accounts", action="get",
                     object="account", desired_output="json")
    results = retriever.retrieve(intent, k=5)
    assert len(results) > 1
    # Scores are valid and ordered.
    assert all(0.0 <= r.score <= 1.0 for r in results)
    assert [r.score for r in results] == sorted([r.score for r in results], reverse=True)


def test_ambiguous_intent_agent_still_selects_one(capabilities):
    """Control A/B pick a single capability for an ambiguous intent (no crash)."""
    agent = BaselineAgent(capabilities)
    intent = _intent(goal="get_account", domain="accounts", action="get",
                     object="account", desired_output="json")
    result = agent.run(intent, capabilities)
    # The agent must have selected exactly one capability and completed.
    assert "selected_capability" in result
    assert result["tool_calls"] >= 1


# ---------------------------------------------------------------------------
# 7. Unknown intent — matches nothing
# ---------------------------------------------------------------------------


def test_unknown_intent_control_c_raises_valueerror():
    """Control C raises ValueError for an intent that matches no recipe."""
    harness = control_c.ControlC()
    with pytest.raises(ValueError):
        harness.run("do something completely unrelated")


def test_unknown_intent_control_c_dict_raises_valueerror():
    """A dict intent with no resolvable family also raises ValueError."""
    harness = control_c.ControlC()
    with pytest.raises(ValueError):
        harness.run({"text": "book a flight to tokyo"})


def test_unknown_intent_bank_raises_valueerror():
    """bank.run_intent raises ValueError for an unknown intent."""
    with pytest.raises(ValueError):
        bank.run_intent("book a flight to tokyo")
