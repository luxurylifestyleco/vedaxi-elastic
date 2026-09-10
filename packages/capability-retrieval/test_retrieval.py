"""Tests for the baseline capability retrieval package.

Covers the swappable interface, the three commodity strategies (keyword,
vector, semantic-router), the factory, and the result contract (scores in
[0,1], latency recorded, top-k behavior).
"""

from __future__ import annotations

import pytest

from capability import Capability
from intent_ir import IntentIR
from registry import CapabilityRegistry
from seed import build_seed_capabilities, seed_registry

from factory import build_retriever, available_strategies
from retriever import CapabilityCandidate, CapabilityRetriever
from strategies import (
    KeywordRetriever,
    SemanticRouterRetriever,
    VectorRetriever,
)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    seed_registry(reg)
    return reg


@pytest.fixture(scope="module")
def capabilities(registry) -> list:
    return registry.list()


@pytest.fixture(scope="module")
def statement_intent() -> IntentIR:
    return IntentIR(
        intent_id="test-1",
        goal="retrieve_financial_document",
        domain="banking",
        action="retrieve",
        object="account_statement",
        constraints={"period": "2026-08"},
        context={"channel": "web"},
        desired_output="pdf",
        authority={"required": ["account_owner"]},
        disclosure={"shareable": False},
        success_conditions=["statement delivered as pdf"],
        confidence=0.9,
        metadata={"compiler": "test"},
    )


# ---------------------------------------------------------------------------
# Interface / result contract
# ---------------------------------------------------------------------------


def test_retriever_is_abstract():
    with pytest.raises(TypeError):
        CapabilityRetriever(capabilities)  # type: ignore[abstract]


def test_candidate_has_expected_fields(capabilities, statement_intent):
    retriever = KeywordRetriever(capabilities)
    results = retriever.retrieve(statement_intent, k=3)
    assert results
    cand = results[0]
    assert isinstance(cand, CapabilityCandidate)
    assert isinstance(cand.capability_id, str)
    assert isinstance(cand.score, float)
    assert isinstance(cand.retrieval_latency_ms, float)
    assert 0.0 <= cand.score <= 1.0
    assert cand.retrieval_latency_ms >= 0.0


def test_scores_are_floats_in_0_1(capabilities, statement_intent):
    for retriever in (
        KeywordRetriever(capabilities),
        VectorRetriever(capabilities),
        SemanticRouterRetriever(capabilities),
    ):
        for cand in retriever.retrieve(statement_intent, k=10):
            assert isinstance(cand.score, float)
            assert 0.0 <= cand.score <= 1.0


def test_latency_is_recorded(capabilities, statement_intent):
    for retriever in (
        KeywordRetriever(capabilities),
        VectorRetriever(capabilities),
        SemanticRouterRetriever(capabilities),
    ):
        for cand in retriever.retrieve(statement_intent, k=5):
            assert cand.retrieval_latency_ms >= 0.0


def test_results_sorted_descending(capabilities, statement_intent):
    retriever = VectorRetriever(capabilities)
    results = retriever.retrieve(statement_intent, k=10)
    scores = [c.score for c in results]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# get_statement appears in top-3 for keyword and vector
# ---------------------------------------------------------------------------


def test_keyword_get_statement_in_top3(capabilities, statement_intent):
    retriever = KeywordRetriever(capabilities)
    results = retriever.retrieve(statement_intent, k=3)
    ids = [c.capability_id for c in results]
    assert "get_statement" in ids


def test_vector_get_statement_in_top3(capabilities, statement_intent):
    retriever = VectorRetriever(capabilities)
    results = retriever.retrieve(statement_intent, k=3)
    ids = [c.capability_id for c in results]
    assert "get_statement" in ids


# ---------------------------------------------------------------------------
# top-k behavior
# ---------------------------------------------------------------------------


def test_top5_returns_more_than_top3(capabilities, statement_intent):
    for retriever in (
        KeywordRetriever(capabilities),
        VectorRetriever(capabilities),
        SemanticRouterRetriever(capabilities),
    ):
        top3 = retriever.retrieve(statement_intent, k=3)
        top5 = retriever.retrieve(statement_intent, k=5)
        assert len(top5) > len(top3)


def test_top10_returns_more_than_top5(capabilities, statement_intent):
    for retriever in (
        KeywordRetriever(capabilities),
        VectorRetriever(capabilities),
        SemanticRouterRetriever(capabilities),
    ):
        top5 = retriever.retrieve(statement_intent, k=5)
        top10 = retriever.retrieve(statement_intent, k=10)
        assert len(top10) > len(top5)


def test_k_clamped_to_corpus_size(capabilities, statement_intent):
    retriever = KeywordRetriever(capabilities)
    results = retriever.retrieve(statement_intent, k=10_000)
    assert len(results) == len(capabilities)


def test_k_zero_returns_empty(capabilities, statement_intent):
    retriever = KeywordRetriever(capabilities)
    assert retriever.retrieve(statement_intent, k=0) == []


def test_negative_k_raises(capabilities, statement_intent):
    retriever = KeywordRetriever(capabilities)
    with pytest.raises(ValueError):
        retriever.retrieve(statement_intent, k=-1)


# ---------------------------------------------------------------------------
# Semantic router
# ---------------------------------------------------------------------------


def test_semantic_router_routes_statement_domain(capabilities, statement_intent):
    retriever = SemanticRouterRetriever(capabilities)
    results = retriever.retrieve(statement_intent, k=len(capabilities))
    # get_statement is in the statements/documents domain, which the rule
    # table routes to for this intent.
    by_id = {c.capability_id: c.score for c in results}
    assert by_id["get_statement"] == 1.0
    # A capability in an unrelated domain should score 0.0.
    assert by_id["freeze_card"] == 0.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_builds_all_strategies(capabilities):
    for name in ("keyword", "vector", "semantic_router"):
        retriever = build_retriever(name, capabilities)
        assert isinstance(retriever, CapabilityRetriever)


def test_factory_accepts_aliases(capabilities):
    assert isinstance(build_retriever("embedding", capabilities), VectorRetriever)
    assert isinstance(build_retriever("tfidf", capabilities), VectorRetriever)
    assert isinstance(build_retriever("semantic", capabilities), SemanticRouterRetriever)


def test_factory_unknown_strategy_raises(capabilities):
    with pytest.raises(ValueError):
        build_retriever("does_not_exist", capabilities)


def test_available_strategies(capabilities):
    names = available_strategies()
    assert {"keyword", "vector", "semantic_router"}.issubset(set(names))
