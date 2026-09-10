"""Baseline Capability Retrieval interface for Elastic Web.

This module defines the swappable retrieval contract. A retriever takes a
structured :class:`~intent_ir.IntentIR` and returns the top-k matching
capabilities as :class:`CapabilityCandidate` objects (capability id, a 0-1
score, and the retrieval latency in milliseconds).

The interface is deliberately minimal and strategy-agnostic so that a
proprietary ranking algorithm can later replace the commodity strategies
without changing callers: any implementation only needs to subclass
:class:`CapabilityRetriever` and implement ``_score``.

This is commodity retrieval only — no ranking learning, no external
embedding APIs, no pgvector dependency.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Iterable, List, Tuple

from pydantic import BaseModel, Field

from capability import Capability
from intent_ir import IntentIR

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class CapabilityCandidate(BaseModel):
    """A single retrieval result.

    Attributes:
        capability_id: The id of the matched capability.
        score: Relevance score in the range [0.0, 1.0] (higher is better).
        retrieval_latency_ms: Wall-clock time taken to score the intent
            against the corpus, in milliseconds.
    """

    capability_id: str = Field(description="Id of the matched capability.")
    score: float = Field(ge=0.0, le=1.0, description="Relevance score, 0.0 to 1.0.")
    retrieval_latency_ms: float = Field(
        ge=0.0, description="Retrieval latency in milliseconds."
    )


# ---------------------------------------------------------------------------
# Shared text utilities
# ---------------------------------------------------------------------------

# Small stopword set to keep term overlap meaningful. Not exhaustive — it
# only removes the most common English function words.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "for", "of", "to", "in", "on", "with",
        "over", "my", "i", "me", "your", "from", "as", "at", "by", "is", "are",
        "be", "this", "that", "it", "its", "all", "new", "current", "full",
        "specific", "high", "level", "held", "customer", "return", "single",
        "another", "party", "send", "among", "multiple", "participants",
        "check", "status", "registered", "recurring", "future", "dated",
        "approved", "partial", "prepayment", "outstanding", "repayment",
        "newly", "issued", "temporarily", "prevent", "further", "replacement",
        "optionally", "number", "reason", "limits", "object", "lost", "stolen",
        "block", "fetch", "including", "type", "branch", "expiring", "coverage",
        "details", "frequently", "asked", "questions", "answers", "available",
        "redemption", "coupon", "earned", "points", "history", "promotions",
        "preferred", "time", "topic", "agent", "session", "start", "chat",
        "ticket", "category", "subject", "description", "callback", "schedule",
        "call", "back", "into", "between", "two", "owned", "make", "initiate",
        "single", "payee", "account", "amount", "currency", "reference",
        "over", "period", "financial", "year", "interest", "tax", "filing",
        "annual", "report", "repayment", "outstanding", "balance", "principal",
        "maturity", "date", "rate", "purchase", "product", "sell", "units",
        "performance", "metrics", "returns", "fixed", "deposit", "cover",
        "renew", "expiring", "verification", "upload", "binary", "add",
        "update", "nominee", "phone", "email", "contact", "address", "change",
        "registered", "preferred", "delivery", "request", "new", "cheque",
        "book", "download", "specific", "document", "id", "list", "all",
        "documents", "available", "account", "over", "period", "format",
    }
)

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumerics and underscores, drop stopwords.

    Compound identifiers such as ``retrieve_financial_document`` or
    ``account_statement`` are split into their constituent terms so they can
    match capability text.
    """
    if not text:
        return []
    tokens = [t for t in _TOKEN_RE.split(text.lower()) if t]
    return [t for t in tokens if t not in _STOPWORDS]


def _intent_text(intent: IntentIR) -> str:
    """Concatenate the intent's routing-relevant fields into a searchable blob."""
    parts = [
        intent.goal,
        intent.domain,
        intent.action,
        intent.object,
        intent.desired_output,
    ]
    return " ".join(parts)


def _capability_text(cap: Capability) -> str:
    """Concatenate a capability's routing-relevant fields into a searchable blob."""
    return " ".join([cap.id, cap.name, cap.description, cap.domain])


# ---------------------------------------------------------------------------
# Retrieval interface
# ---------------------------------------------------------------------------


class CapabilityRetriever(ABC):
    """Swappable retrieval contract.

    Subclasses implement :meth:`_score`, which returns ``(capability_id,
    score)`` pairs for every candidate. The base class handles latency
    measurement, sorting, and top-k truncation, so every strategy reports
    consistent ``CapabilityCandidate`` results.

    A proprietary ranking algorithm can replace any commodity strategy by
    subclassing this interface and implementing ``_score`` — callers are
    unaffected.
    """

    def __init__(self, capabilities: Iterable[Capability]) -> None:
        self._capabilities: List[Capability] = list(capabilities)

    def retrieve(
        self, intent: IntentIR, k: int = 5
    ) -> List[CapabilityCandidate]:
        """Return the top-k capabilities for the given intent.

        Args:
            intent: The structured intent to retrieve capabilities for.
            k: Number of candidates to return (clamped to the corpus size).

        Returns:
            A list of up to ``k`` :class:`CapabilityCandidate` objects,
            ordered by descending score.
        """
        if k < 0:
            raise ValueError("k must be non-negative")
        start = time.perf_counter()
        scored: List[Tuple[str, float]] = self._score(intent)
        latency_ms = (time.perf_counter() - start) * 1000.0

        scored.sort(key=lambda item: item[1], reverse=True)
        top = scored[:k]
        return [
            CapabilityCandidate(
                capability_id=cid,
                score=float(score),
                retrieval_latency_ms=latency_ms,
            )
            for cid, score in top
        ]

    @abstractmethod
    def _score(self, intent: IntentIR) -> List[Tuple[str, float]]:
        """Score every capability against the intent.

        Returns:
            A list of ``(capability_id, score)`` tuples. Scores must be in
            the range [0.0, 1.0].
        """
        raise NotImplementedError
