"""Tests for Control B — the Elastic Web retrieval agent (Phase 10).

Verifies that the RetrievalAgent:
  * returns all Control-A-identical metric fields,
  * successfully completes the 5 canonical demo intents,
  * performs at least one retrieval call,
  * uses FEWER input tokens than Control A (no-retrieval baseline) for the
    same intent, proving retrieval reduces the LLM context.
"""

from __future__ import annotations

import pytest

from capability import Capability
from intent_ir import IntentIR

from control_a import BaselineAgent
from control_b import RetrievalAgent
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

METRIC_FIELDS = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "llm_calls",
    "tool_calls",
    "retrieval_calls",
    "steps",
    "wall_clock_latency_ms",
    "success",
    "estimated_model_cost",
}


@pytest.fixture(scope="module")
def capabilities() -> list:
    return build_manifest()


@pytest.fixture(scope="module")
def agent(capabilities) -> RetrievalAgent:
    return RetrievalAgent(capabilities)


def test_run_returns_all_metric_fields(agent, capabilities):
    result = agent.run(DEMO_INTENTS[0], capabilities)
    assert METRIC_FIELDS.issubset(result.keys())
    for field in METRIC_FIELDS:
        assert field in result, f"missing metric field: {field}"


def test_retrieval_calls_at_least_one(agent, capabilities):
    result = agent.run(DEMO_INTENTS[0], capabilities)
    assert result["retrieval_calls"] >= 1


@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_completes_demo_intents(agent, capabilities, intent):
    result = agent.run(intent, capabilities)
    assert result["success"] is True, f"failed for {intent.intent_id}: {result}"
    assert result["tool_calls"] == 1
    assert result["llm_calls"] == 1
    assert result["retrieval_calls"] >= 1
    assert result["total_tokens"] == result["input_tokens"] + result["output_tokens"]


@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_input_tokens_smaller_than_control_a(capabilities, intent):
    """Retrieval must reduce the LLM context vs Control A (no retrieval)."""
    control_a = BaselineAgent(capabilities)
    control_b = RetrievalAgent(capabilities)

    a = control_a.run(intent)
    b = control_b.run(intent)

    assert b["input_tokens"] < a["input_tokens"], (
        f"{intent.intent_id}: Control B input_tokens ({b['input_tokens']}) "
        f"not smaller than Control A ({a['input_tokens']})"
    )
    # Both must succeed for the comparison to be meaningful.
    assert a["success"] is True
    assert b["success"] is True
