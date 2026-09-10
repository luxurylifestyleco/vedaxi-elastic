"""Control C — recipe-assisted execution for Elastic Web (Phase 12).

This is the CONTROL C benchmark arm: instead of letting a model rediscover
the procedure for a banking intent (Control A) or retrieve capabilities and
plan on the fly (Control B), a set of hand-written recipes is pre-registered
in a :class:`~store.RecipeStore`. ``run(intent)`` looks up the matching recipe
by intent family and executes its steps against the demo-bank functions
directly — no model calls, no procedure rediscovery.

Because the procedure is fully encoded in the recipe, the model is never
invoked: ``llm_calls`` is always 0 and token/cost metrics are 0. The only
"retrieval" is the deterministic recipe lookup in the store. This isolates the
value of a pre-authored recipe versus the discovery-based controls.

Recipes authored here (hand-written, NOT auto-created):

    * statement.retrieve  -> intent_family "retrieve_statement"
        steps: get_statement(period)
    * payment.execute     -> intent_family "make_payment"
        steps: get_balance then make_payment(amount, payee)
    * card.freeze         -> intent_family "freeze_card"
        steps: freeze_card(card_id)

Metrics recorded per run match Control A/B:
    input_tokens, output_tokens, total_tokens, llm_calls, tool_calls,
    retrieval_calls, steps, wall_clock_latency_ms, success/failure,
    estimated_model_cost.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Import path setup: make sibling packages and the demo-bank app importable.
# ---------------------------------------------------------------------------
_PACKAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _PACKAGES_DIR not in sys.path:
    sys.path.insert(0, _PACKAGES_DIR)

# recipe-schema (recipe.py, store.py) lives in its own subdirectory.
_RECIPE_SCHEMA_DIR = os.path.join(_PACKAGES_DIR, "recipe-schema")
if _RECIPE_SCHEMA_DIR not in sys.path:
    sys.path.insert(0, _RECIPE_SCHEMA_DIR)

_APP_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "apps", "demo-bank"
)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from recipe import Recipe, RecipeStatus, RecipeStep  # noqa: E402
from store import RecipeStore  # noqa: E402

import bank  # noqa: E402

# ---------------------------------------------------------------------------
# Metric field names (shared with Control A/B).
# ---------------------------------------------------------------------------
METRIC_FIELDS = [
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
]

# Estimated cost per 1K tokens for the model used by Control A/B (USD).
# Control C makes no model calls, so cost is always 0.0.
_MODEL_COST_PER_1K = 0.002


def _empty_metrics() -> Dict[str, Any]:
    """A metrics dict with every Control A/B field zeroed."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "retrieval_calls": 0,
        "steps": 0,
        "wall_clock_latency_ms": 0.0,
        "success": False,
        "estimated_model_cost": 0.0,
    }


# ---------------------------------------------------------------------------
# Hand-written recipes.
# ---------------------------------------------------------------------------

def build_statement_retrieve_recipe() -> Recipe:
    """statement.retrieve — retrieve a bank statement for a period."""
    return Recipe(
        recipe_id="statement.retrieve",
        intent_family="retrieve_statement",
        version="1.0.0",
        applicability_conditions=[
            "user is authenticated",
            "user requests a statement for a specific period (YYYY-MM)",
        ],
        invariants=[
            "no data mutation: statement retrieval is read-only",
            "statement must be returned for the requested period",
        ],
        steps=[
            RecipeStep(
                step_id="get_statement",
                action="retrieve",
                capability_id="get_statement",
                args={"period": "2026-08"},
                checkpoints=["statement returned with file_url"],
            ),
        ],
        skills=["document_retrieval", "statements"],
        adaptation_points=["output_format", "account_id"],
        checkpoints=["statement delivered as pdf"],
        success_conditions=[
            "get_statement returns ok=True",
            "statement file_url is present",
        ],
        fallbacks=[
            {"on": "timeout", "action": "retry", "max_retries": 2},
            {"on": "period_invalid", "action": "ask_user_for_period"},
        ],
        freshness_policy={"max_age_seconds": 3600, "stale_action": "re_fetch"},
        metrics=METRIC_FIELDS,
        status=RecipeStatus.ACTIVE,
        provenance={
            "author": "elastic-bench",
            "control": "C",
            "created": "2026-09-10",
            "source": "hand-written",
            "phase": 12,
        },
    )


def build_payment_execute_recipe() -> Recipe:
    """payment.execute — check balance, then make a payment.

    Steps form a DAG: ``get_balance`` must complete before ``make_payment``
    so the payment is only attempted when the account is in a healthy state.
    """
    return Recipe(
        recipe_id="payment.execute",
        intent_family="make_payment",
        version="1.0.0",
        applicability_conditions=[
            "user is authenticated",
            "user requests a payment to a payee for an amount",
        ],
        invariants=[
            "payment amount must be positive",
            "payment must not be initiated if balance is insufficient",
        ],
        steps=[
            RecipeStep(
                step_id="get_balance",
                action="check_balance",
                capability_id="get_balance",
                args={},
                checkpoints=["balance returned"],
            ),
            RecipeStep(
                step_id="make_payment",
                action="pay",
                capability_id="make_payment",
                args={"amount": 142.75, "payee": "electricity"},
                depends_on=["get_balance"],
                checkpoints=["payment completed"],
            ),
        ],
        skills=["payments", "balance_check"],
        adaptation_points=["payee", "amount", "from_account"],
        checkpoints=["payment confirmed"],
        success_conditions=[
            "get_balance returns ok=True",
            "make_payment returns status=completed",
        ],
        fallbacks=[
            {"on": "insufficient_funds", "action": "abort_payment"},
            {"on": "timeout", "action": "retry", "max_retries": 2},
        ],
        freshness_policy={"max_age_seconds": 60, "stale_action": "re_fetch_balance"},
        metrics=METRIC_FIELDS,
        status=RecipeStatus.ACTIVE,
        provenance={
            "author": "elastic-bench",
            "control": "C",
            "created": "2026-09-10",
            "source": "hand-written",
            "phase": 12,
        },
    )


def build_card_freeze_recipe() -> Recipe:
    """card.freeze — freeze a card to prevent further transactions."""
    return Recipe(
        recipe_id="card.freeze",
        intent_family="freeze_card",
        version="1.0.0",
        applicability_conditions=[
            "user is authenticated",
            "user requests to freeze a specific card",
        ],
        invariants=[
            "card must be frozen immediately to block transactions",
            "freeze is reversible via unfreeze",
        ],
        steps=[
            RecipeStep(
                step_id="freeze_card",
                action="freeze",
                capability_id="freeze_card",
                args={"card_id": "CARD-9001"},
                checkpoints=["card status is frozen"],
            ),
        ],
        skills=["cards", "fraud_control"],
        adaptation_points=["card_id", "reason"],
        checkpoints=["card frozen"],
        success_conditions=[
            "freeze_card returns status=frozen",
            "card_id matches the requested card",
        ],
        fallbacks=[
            {"on": "timeout", "action": "retry", "max_retries": 2},
            {"on": "card_not_found", "action": "ask_user_for_card_id"},
        ],
        freshness_policy={"max_age_seconds": 0, "stale_action": "always_execute"},
        metrics=METRIC_FIELDS,
        status=RecipeStatus.ACTIVE,
        provenance={
            "author": "elastic-bench",
            "control": "C",
            "created": "2026-09-10",
            "source": "hand-written",
            "phase": 12,
        },
    )


# ---------------------------------------------------------------------------
# Recipe store + executor.
# ---------------------------------------------------------------------------

def build_store() -> RecipeStore:
    """Create a RecipeStore and register the three hand-written recipes."""
    store = RecipeStore()
    for recipe in (
        build_statement_retrieve_recipe(),
        build_payment_execute_recipe(),
        build_card_freeze_recipe(),
    ):
        store.create(recipe)
    return store


def _bank_executor(capability_id: str, args: Dict[str, Any]) -> Any:
    """Dispatch a step's capability_id to the matching demo-bank function."""
    fn: Optional[Callable[..., Any]] = getattr(bank, capability_id, None)
    if fn is None or not callable(fn):
        raise AttributeError(f"demo-bank has no callable capability: {capability_id}")
    return fn(**args)


# ---------------------------------------------------------------------------
# Intent -> recipe family resolution.
# ---------------------------------------------------------------------------

# Map natural-language intent strings to intent families. This mirrors the
# demo-bank dispatch but routes to a recipe family rather than a function.
_INTENT_FAMILY_KEYWORDS: List[tuple] = [
    ("retrieve_statement", ("statement", "august", "period")),
    ("make_payment", ("pay", "payment", "electricity", "bill")),
    ("freeze_card", ("freeze", "stolen", "card")),
]


def resolve_intent_family(intent: Any) -> str:
    """Resolve an intent (dict or string) to an intent family.

    Accepts either a dict with an ``intent_family`` key or a natural-language
    string matched by keyword. Raises ``ValueError`` if no family matches.
    """
    if isinstance(intent, dict):
        family = intent.get("intent_family")
        if family:
            return str(family)
        text = str(intent.get("text", intent.get("intent", "")))
    else:
        text = str(intent)

    text_lower = text.strip().lower()
    for family, keywords in _INTENT_FAMILY_KEYWORDS:
        if any(kw in text_lower for kw in keywords):
            return family
    raise ValueError(f"no recipe matches intent: {intent!r}")


# ---------------------------------------------------------------------------
# Public runner.
# ---------------------------------------------------------------------------

class ControlC:
    """Recipe-assisted execution harness (Control C).

    Attributes:
        store: The :class:`RecipeStore` holding the hand-written recipes.
    """

    def __init__(self, store: Optional[RecipeStore] = None) -> None:
        self.store = store if store is not None else build_store()

    def run(self, intent: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the recipe matching ``intent`` against the demo bank.

        Args:
            intent: An intent dict (``{"intent_family": ...}``) or a
                natural-language string.
            params: Optional overrides for step args (merged into each step's
                args before execution).

        Returns:
            A dict with ``recipe_id``, ``intent_family``, ``results`` (step_id
            -> bank result), and ``metrics`` (the Control A/B metric fields).

        Raises:
            ValueError: If no recipe matches the intent.
            KeyError: If the resolved recipe is not in the store.
        """
        start = time.perf_counter()
        metrics = _empty_metrics()
        family = resolve_intent_family(intent)
        params = params or {}

        # Deterministic recipe lookup (the only "retrieval" in Control C).
        metrics["retrieval_calls"] = 1
        recipe = self._find_by_family(family)
        if recipe is None:
            raise KeyError(f"no recipe for intent family: {family}")

        # Merge param overrides into each step's args.
        merged_steps = []
        for step in recipe.steps:
            step_args = dict(step.args)
            step_args.update(params)
            merged_steps.append(
                RecipeStep(
                    step_id=step.step_id,
                    action=step.action,
                    capability_id=step.capability_id,
                    args=step_args,
                    depends_on=step.depends_on,
                    checkpoints=step.checkpoints,
                )
            )
        merged_recipe = recipe.model_copy(update={"steps": merged_steps})

        metrics["steps"] = len(merged_recipe.steps)
        metrics["tool_calls"] = len(merged_recipe.steps)

        try:
            results = self.store.execute(
                merged_recipe.recipe_id,
                executor=_bank_executor,
                trace_id=uuid.uuid4().hex,
                intent_id=str(intent),
                version=merged_recipe.version,
            )
            metrics["success"] = True
        except Exception as exc:  # noqa: BLE001 - record any failure
            metrics["success"] = False
            metrics["wall_clock_latency_ms"] = round(
                (time.perf_counter() - start) * 1000.0, 3
            )
            return {
                "recipe_id": recipe.recipe_id,
                "intent_family": family,
                "results": {},
                "metrics": metrics,
                "error": f"{type(exc).__name__}: {exc}",
            }

        metrics["wall_clock_latency_ms"] = round(
            (time.perf_counter() - start) * 1000.0, 3
        )
        # No model calls in Control C: tokens and cost stay 0.
        metrics["estimated_model_cost"] = 0.0

        return {
            "recipe_id": recipe.recipe_id,
            "intent_family": family,
            "results": results,
            "metrics": metrics,
        }

    def _find_by_family(self, family: str) -> Optional[Recipe]:
        """Return the active recipe whose intent_family matches ``family``."""
        for recipe_id in self.store._recipes:  # noqa: SLF001 - store internals
            recipe = self.store.retrieve(recipe_id)
            if recipe is not None and recipe.intent_family == family:
                return recipe
        return None

    def recipes(self) -> List[Recipe]:
        """All registered recipes (latest version each)."""
        out: List[Recipe] = []
        for recipe_id in self.store._recipes:  # noqa: SLF001
            recipe = self.store.retrieve(recipe_id)
            if recipe is not None:
                out.append(recipe)
        return out


# Module-level convenience instance.
control_c = ControlC()


def run(intent: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convenience wrapper: run the recipe matching ``intent``."""
    return control_c.run(intent, params=params)
