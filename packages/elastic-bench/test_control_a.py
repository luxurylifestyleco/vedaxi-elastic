"""Tests for Control A — the Elastic Web baseline agent (Phase 9).

Verifies that the BaselineAgent:
  * returns all metric fields,
  * successfully completes the 5 canonical demo intents,
  * performs at least one tool call and reports success.
"""

from __future__ import annotations

import pytest

from capability import Capability
from intent_ir import IntentIR

from control_a import BaselineAgent, METRIC_FIELDS
from manifest import build_manifest

# The 5 canonical demo intents, matching bank.run_intent.
DEMO_INTENTS = [
    IntentIR(
        intent_id="demo-1",
        goal="get_statement",
        domain="statements/documents",
        action="retrieve",
        object="statement",
        desired_output="pdf",
        context={"period": "2026-08"},
    ),
    IntentIR(
        intent_id="demo-2",
        goal="make_payment",
        domain="payments",
        action="pay",
        object="bill",
        desired_output="json",
        context={"payee": "electricity", "amount": 142.75},
    ),
    IntentIR(
        intent_id="demo-3",
        goal="freeze_card",
        domain="cards",
        action="freeze",
        object="card",
        desired_output="json",
        context={"card_id": "CARD-9001"},
    ),
    IntentIR(
        intent_id="demo-4",
        goal="get_income_proof",
        domain="statements/documents",
        action="retrieve",
        object="income_proof",
        desired_output="pdf",
        context={},
    ),
    IntentIR(
        intent_id="demo-5",
        goal="export_transactions",
        domain="accounts",
        action="export",
        object="transactions",
        desired_output="csv",
        context={"months": 6},
    ),
]


@pytest.fixture(scope="module")
def capabilities() -> list:
    return build_manifest()


@pytest.fixture(scope="module")
def agent(capabilities) -> BaselineAgent:
    return BaselineAgent(capabilities)


def test_run_returns_all_metric_fields(agent, capabilities):
    result = agent.run(DEMO_INTENTS[0], capabilities)
    for field in METRIC_FIELDS:
        assert field in result, f"missing metric field: {field}"


def test_metric_fields_are_typed(agent, capabilities):
    result = agent.run(DEMO_INTENTS[0], capabilities)
    assert isinstance(result["input_tokens"], int)
    assert isinstance(result["output_tokens"], int)
    assert isinstance(result["total_tokens"], int)
    assert isinstance(result["llm_calls"], int)
    assert isinstance(result["tool_calls"], int)
    assert isinstance(result["retrieval_calls"], int)
    assert isinstance(result["steps"], int)
    assert isinstance(result["wall_clock_latency_ms"], float)
    assert isinstance(result["success"], bool)
    assert isinstance(result["estimated_model_cost"], float)


@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_completes_demo_intents(agent, capabilities, intent):
    result = agent.run(intent, capabilities)
    assert result["success"] is True, f"failed for {intent.intent_id}: {result}"
    assert result["tool_calls"] >= 1
    assert result["llm_calls"] == 1
    assert result["retrieval_calls"] == 0  # Control A: full list, no retrieval
    assert result["total_tokens"] == result["input_tokens"] + result["output_tokens"]
    assert result["estimated_model_cost"] > 0.0


def test_selects_expected_capability_for_each_intent(agent, capabilities):
    expected = {
        "demo-1": "get_statement",
        "demo-2": "make_payment",
        "demo-3": "freeze_card",
        "demo-4": "get_income_proof",
        "demo-5": "export_transactions",
    }
    for intent in DEMO_INTENTS:
        result = agent.run(intent, capabilities)
        assert result["selected_capability"] == expected[intent.intent_id], (
            f"{intent.intent_id}: selected {result['selected_capability']}, "
            f"expected {expected[intent.intent_id]}"
        )
