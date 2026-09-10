"""Phase 16 — Retrieval tests.

Verifies that the capability retriever (retriever.py, strategies.py,
factory.py) returns sensible top-K results for the canonical demo intents
across all three commodity strategies.
"""

from __future__ import annotations

import os
import sys

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("intent-ir", "capability-registry", "capability-retrieval"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

from factory import build_retriever  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402
from retriever import CapabilityCandidate, CapabilityRetriever  # noqa: E402

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

# The capability each demo intent should retrieve at or near the top.
EXPECTED_TOP = {
    "demo-1": "get_statement",
    "demo-2": "make_payment",
    "demo-3": "freeze_card",
    "demo-4": "get_income_proof",
    "demo-5": "export_transactions",
}

STRATEGIES = ["keyword", "vector", "semantic_router"]


@pytest.fixture(scope="module")
def capabilities():
    return build_manifest()


@pytest.fixture(scope="module")
def retriever(capabilities):
    return build_retriever("keyword", capabilities)


# ---------------------------------------------------------------------------
# Interface / result shape
# ---------------------------------------------------------------------------


def test_retriever_is_capability_retriever(retriever):
    assert isinstance(retriever, CapabilityRetriever)


def test_retrieve_returns_candidates(retriever):
    results = retriever.retrieve(DEMO_INTENTS[0], k=5)
    assert len(results) == 5
    assert all(isinstance(r, CapabilityCandidate) for r in results)


def test_retrieve_scores_in_range(retriever):
    for r in retriever.retrieve(DEMO_INTENTS[0], k=10):
        assert 0.0 <= r.score <= 1.0


def test_retrieve_sorted_descending(retriever):
    results = retriever.retrieve(DEMO_INTENTS[0], k=10)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_k_clamped_to_corpus(retriever, capabilities):
    results = retriever.retrieve(DEMO_INTENTS[0], k=10_000)
    assert len(results) == len(capabilities)


def test_retrieve_negative_k_raises(retriever):
    with pytest.raises(ValueError):
        retriever.retrieve(DEMO_INTENTS[0], k=-1)


def test_retrieve_zero_k_returns_empty(retriever):
    assert retriever.retrieve(DEMO_INTENTS[0], k=0) == []


def test_retrieve_reports_latency(retriever):
    for r in retriever.retrieve(DEMO_INTENTS[0], k=3):
        assert r.retrieval_latency_ms >= 0.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_factory_builds_each_strategy(capabilities, strategy):
    r = build_retriever(strategy, capabilities)
    assert isinstance(r, CapabilityRetriever)


def test_factory_accepts_aliases(capabilities):
    assert isinstance(build_retriever("keywords", capabilities), CapabilityRetriever)
    assert isinstance(build_retriever("embedding", capabilities), CapabilityRetriever)
    assert isinstance(build_retriever("semantic", capabilities), CapabilityRetriever)


def test_factory_unknown_strategy_raises(capabilities):
    with pytest.raises(ValueError):
        build_retriever("does_not_exist", capabilities)


def test_factory_available_strategies():
    import factory

    assert {"keyword", "vector", "semantic_router"}.issubset(
        set(factory.available_strategies())
    )


# ---------------------------------------------------------------------------
# Top-K quality across strategies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_expected_capability_in_top_k(capabilities, strategy, intent):
    r = build_retriever(strategy, capabilities)
    results = r.retrieve(intent, k=5)
    ids = [c.capability_id for c in results]
    assert EXPECTED_TOP[intent.intent_id] in ids, (
        f"{strategy}/{intent.intent_id}: expected {EXPECTED_TOP[intent.intent_id]} "
        f"in top-5, got {ids}"
    )


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("intent", DEMO_INTENTS, ids=lambda i: i.intent_id)
def test_expected_capability_is_top_result(capabilities, strategy, intent):
    """The canonical capability should be the single best match."""
    r = build_retriever(strategy, capabilities)
    results = r.retrieve(intent, k=1)
    assert results[0].capability_id == EXPECTED_TOP[intent.intent_id], (
        f"{strategy}/{intent.intent_id}: top result {results[0].capability_id}, "
        f"expected {EXPECTED_TOP[intent.intent_id]}"
    )


def test_keyword_retrieval_orders_by_relevance(capabilities):
    r = build_retriever("keyword", capabilities)
    # A statement intent should rank statement capabilities above card ones.
    results = r.retrieve(DEMO_INTENTS[0], k=10)
    ids = [c.capability_id for c in results]
    assert ids.index("get_statement") < ids.index("freeze_card")
