"""Intent IR compiler adapter.

Exposes a stable ``compile(text) -> IntentIR`` interface so downstream
consumers are decoupled from the compiler implementation. The current
implementation is a simple rule-based parser; it can later be swapped for
a real LLM compiler without changing the interface.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

from intent_ir import IntentIR

# ---------------------------------------------------------------------------
# Compiler interface
# ---------------------------------------------------------------------------


class IntentCompiler(ABC):
    """Interface for any Intent IR compiler (rule-based or LLM)."""

    @abstractmethod
    def compile(self, text: str) -> IntentIR:
        """Compile a natural-language request into an IntentIR.

        Raises:
            ValueError: if the text cannot be parsed into an intent.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Rule-based implementation
# ---------------------------------------------------------------------------

_MONTHS: Dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# (regex, object, domain, action, goal, desired_output)
_DOCUMENT_RULES: List[tuple] = [
    (
        re.compile(r"bank\s+statement", re.IGNORECASE),
        "account_statement",
        "banking",
        "retrieve",
        "retrieve_financial_document",
        "pdf",
    ),
    (
        re.compile(r"(credit\s+card\s+)?statement", re.IGNORECASE),
        "account_statement",
        "banking",
        "retrieve",
        "retrieve_financial_document",
        "pdf",
    ),
    (
        re.compile(r"invoice", re.IGNORECASE),
        "invoice",
        "billing",
        "retrieve",
        "retrieve_financial_document",
        "pdf",
    ),
    (
        re.compile(r"receipt", re.IGNORECASE),
        "receipt",
        "billing",
        "retrieve",
        "retrieve_financial_document",
        "pdf",
    ),
]


class RuleBasedCompiler(IntentCompiler):
    """Simple, deterministic rule-based Intent IR compiler.

    Handles a small set of financial-document retrieval patterns. This is a
    structural placeholder — not a sophisticated intent engine.
    """

    def __init__(self, default_year: Optional[int] = None) -> None:
        self._default_year = default_year or date.today().year

    def compile(self, text: str) -> IntentIR:
        if not text or not text.strip():
            raise ValueError("cannot compile empty text")

        lowered = text.lower()

        # Match a known document pattern.
        for pattern, obj, domain, action, goal, output in _DOCUMENT_RULES:
            if pattern.search(lowered):
                constraints: Dict[str, object] = {}
                period = self._extract_period(lowered)
                if period is not None:
                    constraints["period"] = period
                return IntentIR(
                    intent_id=IntentIR.new_id(),
                    goal=goal,
                    domain=domain,
                    action=action,
                    object=obj,
                    constraints=constraints,
                    context={"source_text": text.strip()},
                    desired_output=output,
                    authority={},
                    disclosure={},
                    success_conditions=[f"{obj} delivered as {output}"],
                    confidence=0.9,
                    metadata={"compiler": "rule-based", "version": "0.1.0"},
                )

        raise ValueError(f"unable to parse intent from: {text!r}")

    def _extract_period(self, lowered: str) -> Optional[str]:
        """Return a 'YYYY-MM' period string if a month is mentioned."""
        for name, month in _MONTHS.items():
            if re.search(rf"\b{name}\b", lowered):
                return f"{self._default_year:04d}-{month:02d}"
        return None


# Default compiler instance for convenience.
default_compiler = RuleBasedCompiler()
