"""Factory for building capability retrievers by strategy name.

The factory decouples callers from concrete strategy classes. Given a
strategy name and a set of capabilities, it returns a ready-to-use
:class:`~retriever.CapabilityRetriever`. New strategies (including a
proprietary ranking algorithm) can be registered here without changing
callers.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Type

from capability import Capability

from retriever import CapabilityRetriever
from strategies import KeywordRetriever, SemanticRouterRetriever, VectorRetriever

# Strategy name -> constructor. The constructor takes an iterable of
# capabilities and returns a CapabilityRetriever.
_BUILDERS: Dict[str, Callable[[Iterable[Capability]], CapabilityRetriever]] = {
    "keyword": KeywordRetriever,
    "vector": VectorRetriever,
    "semantic_router": SemanticRouterRetriever,
}

# Aliases so callers can use either the canonical name or a common synonym.
_ALIASES: Dict[str, str] = {
    "keyword": "keyword",
    "keywords": "keyword",
    "vector": "vector",
    "embedding": "vector",
    "tfidf": "vector",
    "semantic_router": "semantic_router",
    "semantic-router": "semantic_router",
    "semantic": "semantic_router",
    "router": "semantic_router",
}


def build_retriever(
    strategy: str, capabilities: Iterable[Capability]
) -> CapabilityRetriever:
    """Build a retriever for the given strategy name.

    Args:
        strategy: Strategy name, e.g. ``"keyword"``, ``"vector"``, or
            ``"semantic_router"``. Common synonyms are accepted.
        capabilities: The capabilities to retrieve from.

    Returns:
        A configured :class:`~retriever.CapabilityRetriever`.

    Raises:
        ValueError: If the strategy name is unknown.
    """
    key = _ALIASES.get(strategy.strip().lower(), strategy.strip().lower())
    builder = _BUILDERS.get(key)
    if builder is None:
        known = ", ".join(sorted(_BUILDERS))
        raise ValueError(f"unknown retrieval strategy {strategy!r}; known: {known}")
    return builder(capabilities)


def register_strategy(
    name: str, builder: Callable[[Iterable[Capability]], CapabilityRetriever]
) -> None:
    """Register a custom strategy builder (e.g. a proprietary ranker)."""
    _BUILDERS[name.strip().lower()] = builder


def available_strategies() -> list:
    """Return the canonical strategy names."""
    return sorted(_BUILDERS)
