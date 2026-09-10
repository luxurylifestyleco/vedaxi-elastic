"""Tests for Control C — recipe-assisted execution (Phase 12).

Asserts that:
  * exactly 3 hand-written recipes exist and are all active,
  * each recipe executes successfully against the demo bank,
  * llm_calls is 0 (recipe-assisted, no model rediscovery),
  * steps matches the recipe's step count.
"""

from __future__ import annotations

import os
import sys

import pytest

# Make sibling packages and the demo-bank app importable.
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

from recipe import RecipeStatus  # noqa: E402

import control_c  # noqa: E402

EXPECTED_RECIPES = {
    "statement.retrieve": "retrieve_statement",
    "payment.execute": "make_payment",
    "card.freeze": "freeze_card",
}

# (intent, params) pairs used to exercise each recipe against the demo bank.
RUN_CASES = [
    ("statement.retrieve", {"intent_family": "retrieve_statement"}, {"period": "2026-08"}),
    ("payment.execute", {"intent_family": "make_payment"}, {"amount": 142.75, "payee": "electricity"}),
    ("card.freeze", {"intent_family": "freeze_card"}, {"card_id": "CARD-9001"}),
]


def _harness() -> control_c.ControlC:
    return control_c.ControlC()


# ----------------------------------------------------------------------
# Recipe registration
# ----------------------------------------------------------------------


def test_three_recipes_exist_and_are_active():
    harness = _harness()
    recipes = {r.recipe_id: r for r in harness.recipes()}
    assert set(recipes) == set(EXPECTED_RECIPES)
    for recipe in recipes.values():
        assert recipe.status == RecipeStatus.ACTIVE


def test_recipes_have_expected_intent_families():
    harness = _harness()
    recipes = {r.recipe_id: r for r in harness.recipes()}
    for recipe_id, family in EXPECTED_RECIPES.items():
        assert recipes[recipe_id].intent_family == family


def test_recipes_define_expected_steps():
    harness = _harness()
    recipes = {r.recipe_id: r for r in harness.recipes()}
    assert [s.capability_id for s in recipes["statement.retrieve"].steps] == ["get_statement"]
    assert [s.capability_id for s in recipes["payment.execute"].steps] == [
        "get_balance",
        "make_payment",
    ]
    assert [s.capability_id for s in recipes["card.freeze"].steps] == ["freeze_card"]


def test_payment_recipe_steps_form_dag():
    harness = _harness()
    recipe = next(r for r in harness.recipes() if r.recipe_id == "payment.execute")
    by_id = {s.step_id: s for s in recipe.steps}
    assert by_id["make_payment"].depends_on == ["get_balance"]
    # Topological order must place get_balance before make_payment.
    order = recipe.topological_order()
    assert order.index("get_balance") < order.index("make_payment")


# ----------------------------------------------------------------------
# Execution against the demo bank
# ----------------------------------------------------------------------


@pytest.mark.parametrize("recipe_id,intent,params", RUN_CASES)
def test_recipe_executes_successfully(recipe_id, intent, params):
    harness = _harness()
    result = harness.run(intent, params=params)
    assert result["recipe_id"] == recipe_id
    assert result["metrics"]["success"] is True
    # Every step produced a successful bank result.
    for step_result in result["results"].values():
        assert step_result["ok"] is True


def test_llm_calls_is_zero_for_all_recipes():
    harness = _harness()
    for recipe_id, intent, params in RUN_CASES:
        result = harness.run(intent, params=params)
        assert result["metrics"]["llm_calls"] == 0, recipe_id
        assert result["metrics"]["input_tokens"] == 0, recipe_id
        assert result["metrics"]["output_tokens"] == 0, recipe_id
        assert result["metrics"]["total_tokens"] == 0, recipe_id
        assert result["metrics"]["estimated_model_cost"] == 0.0, recipe_id


def test_steps_metric_matches_recipe_step_count():
    harness = _harness()
    recipes = {r.recipe_id: r for r in harness.recipes()}
    for recipe_id, intent, params in RUN_CASES:
        result = harness.run(intent, params=params)
        assert result["metrics"]["steps"] == len(recipes[recipe_id].steps), recipe_id
        assert result["metrics"]["tool_calls"] == len(recipes[recipe_id].steps), recipe_id


def test_metric_fields_match_control_ab():
    harness = _harness()
    result = harness.run({"intent_family": "retrieve_statement"})
    assert set(result["metrics"].keys()) == set(control_c.METRIC_FIELDS)


def test_unknown_intent_raises():
    harness = _harness()
    with pytest.raises(ValueError):
        harness.run("do something completely unrelated")
