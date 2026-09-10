"""Commodity retrieval strategies for Elastic Web.

Three baseline strategies, all implementing the swappable
:class:`~retriever.CapabilityRetriever` interface:

A. Keyword retrieval — tokenize the intent and score capabilities by term
   overlap with their id/name/description/domain.

B. Vector retrieval — a deterministic, local TF-IDF-style bag-of-words
   embedding with cosine similarity. No external embedding API and no
   pgvector: the "embedding" is a sparse term-frequency vector built from
   the corpus vocabulary, so results are reproducible and dependency-free.

C. Semantic-router-style routing — map the intent's goal/domain/action to
   capability domains via a simple rule table, then score within the
   matched domain.

All strategies are commodity retrieval only. No ranking learning.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple

from capability import Capability
from intent_ir import IntentIR

from retriever import (
    CapabilityRetriever,
    _capability_text,
    _intent_text,
    tokenize,
)

# ---------------------------------------------------------------------------
# A. Keyword retrieval
# ---------------------------------------------------------------------------


class KeywordRetriever(CapabilityRetriever):
    """Score capabilities by term overlap with the intent text.

    Each capability is scored as the fraction of distinct intent terms that
    appear in the capability's id/name/description/domain. A capability that
    covers every intent term scores 1.0; one that shares none scores 0.0.
    """

    def __init__(self, capabilities: Iterable[Capability]) -> None:
        super().__init__(capabilities)
        self._index: List[Tuple[Capability, Counter]] = []
        for cap in self._capabilities:
            self._index.append((cap, Counter(tokenize(_capability_text(cap)))))

    def _score(self, intent: IntentIR) -> List[Tuple[str, float]]:
        query_terms = set(tokenize(_intent_text(intent)))
        if not query_terms:
            return [(cap.id, 0.0) for cap, _ in self._index]

        results: List[Tuple[str, float]] = []
        for cap, term_counts in self._index:
            overlap = sum(1 for t in query_terms if term_counts[t] > 0)
            results.append((cap.id, overlap / len(query_terms)))
        return results


# ---------------------------------------------------------------------------
# B. Vector retrieval (local TF-IDF + cosine similarity)
# ---------------------------------------------------------------------------


class VectorRetriever(CapabilityRetriever):
    """Score capabilities by cosine similarity of TF-IDF vectors.

    The corpus vocabulary is built once at construction. Each capability is
    embedded as a sparse TF-IDF vector (term frequency weighted by inverse
    document frequency). The intent is embedded the same way and scored by
    cosine similarity, so results are deterministic and require no external
    embedding service or pgvector.
    """

    def __init__(self, capabilities: Iterable[Capability]) -> None:
        super().__init__(capabilities)
        self._doc_terms: List[Counter] = [
            Counter(tokenize(_capability_text(cap))) for cap in self._capabilities
        ]
        self._vocab: List[str] = self._build_vocab(self._doc_terms)
        self._idf: Dict[str, float] = self._build_idf(self._doc_terms, self._vocab)
        self._doc_vectors: List[Dict[str, float]] = [
            self._tfidf(terms) for terms in self._doc_terms
        ]

    @staticmethod
    def _build_vocab(doc_terms: Sequence[Counter]) -> List[str]:
        vocab: set = set()
        for terms in doc_terms:
            vocab.update(terms)
        return sorted(vocab)

    @staticmethod
    def _build_idf(
        doc_terms: Sequence[Counter], vocab: List[str]
    ) -> Dict[str, float]:
        n = len(doc_terms)
        idf: Dict[str, float] = {}
        for term in vocab:
            df = sum(1 for terms in doc_terms if terms[term] > 0)
            idf[term] = math.log((1.0 + n) / (1.0 + df)) + 1.0
        return idf

    def _tfidf(self, terms: Counter) -> Dict[str, float]:
        total = sum(terms.values()) or 1.0
        vec: Dict[str, float] = {}
        for term, count in terms.items():
            tf = count / total
            vec[term] = tf * self._idf.get(term, 1.0)
        return vec

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        dot = 0.0
        for term, val in a.items():
            if term in b:
                dot += val * b[term]
        if dot == 0.0:
            return 0.0
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _score(self, intent: IntentIR) -> List[Tuple[str, float]]:
        query_vec = self._tfidf(Counter(tokenize(_intent_text(intent))))
        return [
            (cap.id, self._cosine(query_vec, doc_vec))
            for cap, doc_vec in zip(self._capabilities, self._doc_vectors)
        ]


# ---------------------------------------------------------------------------
# C. Semantic-router-style routing
# ---------------------------------------------------------------------------

# Rule table mapping intent goal/domain/action to capability domains.
# Each entry is a (field, value) pair; the first matching rule wins.
_ROUTE_RULES: List[Tuple[str, str, str]] = [
    # (intent_field, value, capability_domain)
    ("goal", "retrieve_financial_document", "statements/documents"),
    ("goal", "get_statement", "statements/documents"),
    ("goal", "download_document", "statements/documents"),
    ("goal", "get_document", "statements/documents"),
    ("goal", "get_balance", "accounts"),
    ("goal", "get_account", "accounts"),
    ("goal", "list_accounts", "accounts"),
    ("goal", "get_transactions", "accounts"),
    ("goal", "transfer_funds", "payments"),
    ("goal", "make_payment", "payments"),
    ("goal", "pay_bill", "payments"),
    ("goal", "freeze_card", "cards"),
    ("goal", "get_card", "cards"),
    ("goal", "get_loan", "loans"),
    ("goal", "apply_for_loan", "loans"),
    ("goal", "get_portfolio", "investments"),
    ("goal", "get_insurance", "insurance"),
    ("goal", "get_profile", "KYC/profile"),
    ("goal", "update_profile", "KYC/profile"),
    ("goal", "get_offers", "offers"),
    ("goal", "get_support", "support"),
    # domain-level fallbacks
    ("domain", "banking", "statements/documents"),
    ("domain", "accounts", "accounts"),
    ("domain", "payments", "payments"),
    ("domain", "cards", "cards"),
    ("domain", "loans", "loans"),
    ("domain", "investments", "investments"),
    ("domain", "insurance", "insurance"),
    ("domain", "kyc", "KYC/profile"),
    ("domain", "profile", "KYC/profile"),
    ("domain", "offers", "offers"),
    ("domain", "support", "support"),
    # action-level fallbacks
    ("action", "retrieve", "statements/documents"),
    ("action", "download", "statements/documents"),
    ("action", "get", "accounts"),
    ("action", "list", "accounts"),
    ("action", "transfer", "payments"),
    ("action", "pay", "payments"),
    ("action", "freeze", "cards"),
    ("action", "apply", "loans"),
    ("action", "buy", "investments"),
    ("action", "sell", "investments"),
    ("action", "file", "insurance"),
    ("action", "update", "KYC/profile"),
    ("action", "redeem", "offers"),
    ("action", "create", "support"),
]


class SemanticRouterRetriever(CapabilityRetriever):
    """Route an intent to a capability domain via a rule table.

    The intent's goal, then domain, then action are matched against
    :data:`_ROUTE_RULES`. The first matching rule selects a capability
    domain; capabilities in that domain score 1.0, all others 0.0. If no
    rule matches, every capability scores 0.0 (no confident route).
    """

    def __init__(self, capabilities: Iterable[Capability]) -> None:
        super().__init__(capabilities)
        self._by_domain: Dict[str, List[str]] = {}
        for cap in self._capabilities:
            self._by_domain.setdefault(cap.domain, []).append(cap.id)

    def _route_domain(self, intent: IntentIR) -> str | None:
        for field, value, domain in _ROUTE_RULES:
            actual = getattr(intent, field, None)
            if actual is not None and str(actual).lower() == value.lower():
                return domain
        return None

    def _score(self, intent: IntentIR) -> List[Tuple[str, float]]:
        domain = self._route_domain(intent)
        if domain is None:
            return [(cap.id, 0.0) for cap in self._capabilities]
        matched = set(self._by_domain.get(domain, []))
        return [(cap.id, 1.0 if cap.id in matched else 0.0) for cap in self._capabilities]
