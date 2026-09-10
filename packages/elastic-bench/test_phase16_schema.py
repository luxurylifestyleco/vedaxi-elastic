"""Phase 16 — Schema tests.

Validates that:
  * IntentIR instances validate against packages/intent-ir/schema.json
    (jsonschema), including rejection of invalid documents.
  * Capability and Recipe models validate (Pydantic) and reject bad input.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("intent-ir", "capability-registry", "recipe-schema"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

import jsonschema  # noqa: E402
from capability import Capability  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from recipe import Recipe, RecipeStep  # noqa: E402

_SCHEMA_PATH = os.path.join(_PACKAGES, "intent-ir", "schema.json")


@pytest.fixture(scope="module")
def schema() -> dict:
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _valid_intent_dict() -> dict:
    return {
        "intent_id": "demo-1",
        "goal": "get_statement",
        "domain": "statements/documents",
        "action": "retrieve",
        "object": "statement",
        "constraints": {},
        "context": {"period": "2026-08"},
        "desired_output": "pdf",
        "authority": {},
        "disclosure": {},
        "success_conditions": [],
        "confidence": 1.0,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# IntentIR vs schema.json
# ---------------------------------------------------------------------------


def test_schema_file_exists():
    assert os.path.exists(_SCHEMA_PATH)


def test_valid_intent_validates_against_schema(schema):
    jsonschema.validate(_valid_intent_dict(), schema)


def test_intent_ir_model_dump_validates_against_schema(schema):
    intent = IntentIR(
        intent_id="demo-1",
        goal="get_statement",
        domain="statements/documents",
        action="retrieve",
        object="statement",
        desired_output="pdf",
        context={"period": "2026-08"},
    )
    jsonschema.validate(intent.model_dump(), schema)


def test_schema_rejects_missing_required_field(schema):
    data = _valid_intent_dict()
    del data["goal"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)


def test_schema_rejects_unknown_field(schema):
    data = _valid_intent_dict()
    data["bogus_field"] = "nope"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)


def test_schema_rejects_confidence_out_of_range(schema):
    data = _valid_intent_dict()
    data["confidence"] = 1.5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)


def test_schema_rejects_wrong_type(schema):
    data = _valid_intent_dict()
    data["success_conditions"] = "not-a-list"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)


# ---------------------------------------------------------------------------
# IntentIR Pydantic model
# ---------------------------------------------------------------------------


def test_intent_ir_roundtrip():
    intent = IntentIR(
        intent_id="i-1",
        goal="make_payment",
        domain="payments",
        action="pay",
        object="bill",
        desired_output="json",
    )
    assert IntentIR.model_validate(intent.model_dump()) == intent


def test_intent_ir_rejects_unknown_field():
    with pytest.raises(Exception):
        IntentIR(
            intent_id="i-1",
            goal="g",
            domain="d",
            action="a",
            object="o",
            desired_output="json",
            bogus="x",
        )


def test_intent_ir_rejects_blank_required():
    with pytest.raises(Exception):
        IntentIR(
            intent_id="   ",
            goal="g",
            domain="d",
            action="a",
            object="o",
            desired_output="json",
        )


def test_intent_ir_new_id_is_unique():
    assert IntentIR.new_id() != IntentIR.new_id()


# ---------------------------------------------------------------------------
# Capability model
# ---------------------------------------------------------------------------


def test_capability_roundtrip():
    cap = Capability(
        id="get_balance",
        name="Get Balance",
        description="Retrieve account balance.",
        domain="accounts",
    )
    assert Capability.model_validate(cap.model_dump()) == cap


def test_capability_rejects_unknown_field():
    with pytest.raises(Exception):
        Capability(
            id="c",
            name="n",
            description="d",
            domain="accounts",
            bogus="x",
        )


def test_capability_rejects_blank_required():
    with pytest.raises(Exception):
        Capability(id="  ", name="n", description="d", domain="accounts")


def test_capability_defaults():
    cap = Capability(id="c", name="n", description="d", domain="accounts")
    assert cap.provider == "demo-bank"
    assert cap.protocol == "rest"
    assert cap.inputs == {}
    assert cap.outputs == {}
    assert cap.permissions == []
    assert cap.endpoint is None


# ---------------------------------------------------------------------------
# Recipe model
# ---------------------------------------------------------------------------


def test_recipe_roundtrip():
    recipe = Recipe(
        recipe_id="r1",
        intent_family="retrieve_statement",
        steps=[
            RecipeStep(
                step_id="s1",
                action="retrieve",
                capability_id="get_statement",
                args={"period": "2026-08"},
            )
        ],
    )
    assert Recipe.model_validate(recipe.model_dump()) == recipe


def test_recipe_rejects_unknown_field():
    with pytest.raises(Exception):
        Recipe(recipe_id="r1", intent_family="f", bogus="x")


def test_recipe_rejects_blank_required():
    with pytest.raises(Exception):
        Recipe(recipe_id="  ", intent_family="f")


def test_recipe_rejects_unknown_dependency():
    with pytest.raises(Exception):
        Recipe(
            recipe_id="bad",
            intent_family="f",
            steps=[
                RecipeStep(step_id="s1", action="a", capability_id="c"),
                RecipeStep(
                    step_id="s2",
                    action="a",
                    capability_id="c",
                    depends_on=["missing"],
                ),
            ],
        )


def test_recipe_rejects_cycle():
    with pytest.raises(Exception):
        Recipe(
            recipe_id="cycle",
            intent_family="f",
            steps=[
                RecipeStep(
                    step_id="s1", action="a", capability_id="c", depends_on=["s2"]
                ),
                RecipeStep(
                    step_id="s2", action="a", capability_id="c", depends_on=["s1"]
                ),
            ],
        )
