"""Phase 16 — Benchmark smoke tests.

Runs the three control agents (A, B, C) against the 5 canonical demo
intents and asserts that every run returns all metric fields and reports
success. This is a smoke test of the benchmark harness, not a re-derivation
of the per-control unit tests (test_control_a/b/c.py).
"""

from __future__ import annotations

import os
import sys

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("intent-ir", "capability-registry", "recipe-schema"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

from control_a import BaselineAgent  # noqa: E402
from control_b import RetrievalAgent  # noqa: E402
import control_c  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402

# The 5 canonical demo intents (mirrors test_control_b.py).
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

# Control C intents (dict form with intent_family).
CONTROL_C_INTENTS = [
    {"intent_family": "retrieve_statement"},
    {"intent_family": "make_payment"},
    {"intent_family": "freeze_card"},
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
def capabilities():
    return build_manifest()


@pytest.fixture(scope="module")
def control_a(capabilities):
    return BaselineAgent(capabilities)


@pytest.fixture(scope="module")
def control_b(capabilities):
    return RetrievalAgent(capabilities)


@pytest.fixture(scope="module")
def control_c_harness():
    return control_c.ControlC()


# ---------------------------------------------------------------------------
# Control A
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_control_a_runs_all_demo_intents(control_a, capabilities, intent):
    result = control_a.run(intent, capabilities)
    assert METRIC_FIELDS.issubset(result.keys())
    assert result["success"] is True, f"demo-{intent.intent_id}: {result}"
    assert result["tool_calls"] >= 1
    assert result["retrieval_calls"] == 0


# ---------------------------------------------------------------------------
# Control B
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_control_b_runs_all_demo_intents(control_b, capabilities, intent):
    result = control_b.run(intent, capabilities)
    assert METRIC_FIELDS.issubset(result.keys())
    assert result["success"] is True, f"demo-{intent.intent_id}: {result}"
    assert result["retrieval_calls"] >= 1
    assert result["tool_calls"] == 1


# ---------------------------------------------------------------------------
# Control C
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", CONTROL_C_INTENTS, ids=lambda i: i["intent_family"])
def test_control_c_runs_all_recipes(control_c_harness, intent):
    result = control_c_harness.run(intent)
    assert METRIC_FIELDS.issubset(result["metrics"].keys())
    assert result["metrics"]["success"] is True, f"{intent}: {result}"
    assert result["metrics"]["llm_calls"] == 0
    assert result["metrics"]["retrieval_calls"] == 1


# ---------------------------------------------------------------------------
# Cross-control metric-field consistency
# ---------------------------------------------------------------------------


def test_all_controls_report_identical_metric_fields(
    control_a, control_b, control_c_harness, capabilities
):
    a = control_a.run(DEMO_INTENTS[0], capabilities)
    b = control_b.run(DEMO_INTENTS[0], capabilities)
    c = control_c_harness.run({"intent_family": "retrieve_statement"})
    assert set(a.keys()) & METRIC_FIELDS == METRIC_FIELDS
    assert set(b.keys()) & METRIC_FIELDS == METRIC_FIELDS
    assert set(c["metrics"].keys()) == METRIC_FIELDS
