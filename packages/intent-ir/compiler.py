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

        # Outreach planning is a goal, not a recipe. Steps come from the capability book.
        if re.search(r"\bprospects\b", lowered) and re.search(r"\boutreach\b", lowered):
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="prepare_outreach",
                domain="sales",
                action="prepare",
                object="outreach_plan",
                constraints={"stop_before_contact": True},
                context={"source_text": text.strip()},
                desired_output="json",
                authority={"human_approval_before_contact": True},
                disclosure={},
                success_conditions=[
                    "prospects identified",
                    "companies researched",
                    "outreach plan prepared",
                    "human approval identified",
                    "no contact sent",
                ],
                confidence=0.9,
                metadata={"compiler": "rule-based", "version": "0.1.1"},
            )

        # Omnichannel lead management and operations intent
        if re.search(r"\bleads?\b", lowered) and (
            re.search(r"\bfollow-?ups?\b", lowered)
            or re.search(r"\bresponse\s+times?\b", lowered)
            or re.search(r"\bsatisfaction\b", lowered)
            or re.search(r"\battention\b", lowered)
        ):
            target_mins = 15
            match_mins = re.search(r"(\d+)\s*(?:minute|min)", lowered)
            if match_mins:
                target_mins = int(match_mins.group(1))
            return IntentIR(
                intent_id=IntentIR.new_id(),
                goal="manage_omnichannel_operations",
                domain="operations",
                action="coordinate",
                object="omnichannel_operations_plan",
                constraints={
                    "stop_before_contact": True,
                    "target_response_time_minutes": target_mins,
                },
                context={"source_text": text.strip()},
                desired_output="json",
                authority={"human_approval_before_contact": True},
                disclosure={},
                success_conditions=[
                    "leads ingested across channels",
                    "prospects researched",
                    "response time targets monitored",
                    "customer satisfaction assessed",
                    "follow-ups coordinated",
                    "exceptions and escalations surfaced",
                    "human approval identified",
                    "no contact sent",
                ],
                confidence=0.95,
                metadata={"compiler": "rule-based", "version": "0.1.2"},
            )

        matches = [rule for rule in _DOCUMENT_RULES if rule[0].search(lowered)]
        kinds = []
        if re.search(r"\bstatement\b", lowered):
            kinds.append("statement")
        if re.search(r"\binvoice\b", lowered):
            kinds.append("invoice")
        if re.search(r"\breceipt\b", lowered):
            kinds.append("receipt")
        if len(kinds) > 1:
            raise ValueError(
                "multiple document intents; clarification required before emit"
            )
        if re.search(
            r"\b(dubai|abu dhabi|london|paris|usd|aed|eur|gbp|dollars|dirhams)\b",
            lowered,
        ) or re.search(r"\$\s*\d", text):
            raise ValueError(
                "unsupported constraint; refusing to emit a partial intent"
            )

        # Match a known document pattern. Prefer the first, most specific rule.
        for pattern, obj, domain, action, goal, output in matches:
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
                    metadata={"compiler": "rule-based", "version": "0.1.1",
                              "validated_constraints": list(constraints)},
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
