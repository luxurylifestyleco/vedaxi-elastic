"""Shared agent plumbing for Elastic Web Control A and Control B.

The deterministic rule-based "LLM" and the demo-bank invocation logic live
here so that both controls use the SAME model and the SAME underlying
capabilities. The only difference between the controls is whether the LLM
sees all capabilities (Control A) or only the top-K retrieved ones
(Control B).
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

import bank
from capability import Capability
from intent_ir import IntentIR

# Demo-intent default arguments keyed by capability id. These mirror the
# canonical demo intents wired in ``bank.run_intent`` so the agent can
# invoke the selected capability with sensible synthetic values.
_DEMO_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "get_statement": {"period": "2026-08"},
    "make_payment": {"amount": 142.75, "payee": "electricity"},
    "freeze_card": {"card_id": "CARD-9001"},
    "get_income_proof": {},
    "export_transactions": {"months": 6},
}


def _intent_terms(intent: IntentIR) -> List[str]:
    """Routing-relevant terms from the intent used by the rule-based LLM."""
    return [
        intent.goal,
        intent.action,
        intent.object,
        intent.domain,
        intent.desired_output,
    ]


def build_prompt(intent: IntentIR, caps: List[Capability]) -> str:
    """Build the LLM prompt from the intent and a list of capabilities.

    The list passed in is exactly what the LLM is allowed to see: all
    capabilities for Control A, or only the top-K retrieved ones for
    Control B.
    """
    lines = [
        f"Intent: {intent.goal} (domain={intent.domain}, action={intent.action}, "
        f"object={intent.object}, desired_output={intent.desired_output})",
        "Available capabilities:",
    ]
    for i, cap in enumerate(caps, 1):
        lines.append(f"{i}. {cap.id}: {cap.description}")
    return "\n".join(lines)


def llm_select(intent: IntentIR, caps: List[Capability]) -> Capability:
    """Deterministic rule-based 'LLM' that selects the best capability.

    Scores each candidate by how many intent routing terms appear in its
    id/name/description/domain, then picks the best. Ties break by the
    order the candidates were presented. This is the SAME model for both
    controls; only the candidate list differs.
    """
    terms = _intent_terms(intent)
    best: Optional[Capability] = None
    best_score = -1
    for cap in caps:
        haystack = " ".join([cap.id, cap.name, cap.description, cap.domain]).lower()
        score = sum(1 for t in terms if t.lower() in haystack)
        # Exact id match on the goal is a strong signal the capability is
        # the intended one (e.g. goal "make_payment" -> make_payment).
        if cap.id == intent.goal:
            score += 10
        if score > best_score:
            best_score = score
            best = cap
    return best  # caps is non-empty (k >= 1)


def build_kwargs(intent: IntentIR, cap: Capability) -> Dict[str, Any]:
    """Build invocation kwargs for the selected capability.

    Merges demo defaults with intent context/constraints, filtered to the
    bank function's accepted parameters.
    """
    fn = getattr(bank, cap.id, None)
    params: set = set()
    if fn is not None and callable(fn):
        try:
            params = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            params = set()

    kwargs: Dict[str, Any] = {}
    for src in (intent.context, intent.constraints):
        for key, val in src.items():
            if key in params:
                kwargs[key] = val
    for key, val in _DEMO_DEFAULTS.get(cap.id, {}).items():
        if key in params:
            kwargs.setdefault(key, val)
    return kwargs


def invoke(cap: Capability, intent: IntentIR) -> Dict[str, Any]:
    """Invoke a capability against the demo-bank function.

    Returns the bank function's result dict. Raises if the capability has
    no backing function or the call fails.
    """
    fn = getattr(bank, cap.id, None)
    if fn is None or not callable(fn):
        raise AttributeError(f"bank has no callable for capability '{cap.id}'")
    kwargs = build_kwargs(intent, cap)
    return fn(**kwargs)
