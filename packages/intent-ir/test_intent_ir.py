"""Tests for the Intent IR package: schema, Pydantic model, and compiler."""

from __future__ import annotations

import json
import os
from datetime import date

import pytest
from jsonschema import Draft202012Validator, validate

from compiler import IntentCompiler, RuleBasedCompiler
from intent_ir import IntentIR, IntentState

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.json")

EXPECTED_FIELDS = {
    "intent_revision",
    "intent_id",
    "schema_version",
    "original_expression",
    "state",
    "goal",
    "domain",
    "action",
    "object",
    "constraints",
    "preferences",
    "context",
    "desired_output",
    "authority",
    "disclosure",
    "success_conditions",
    "confidence",
    "uncertainty",
    "fulfillment",
    "metadata",
}

REQUIRED_FIELDS = {
    "intent_id",
    "goal",
    "domain",
    "action",
    "object",
    "constraints",
    "context",
    "desired_output",
    "authority",
    "disclosure",
    "success_conditions",
    "confidence",
    "metadata",
}


@pytest.fixture(scope="module")
def schema() -> dict:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def validator(schema) -> Draft202012Validator:
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_defines_all_expected_fields(schema):
    props = set(schema["properties"].keys())
    assert props == EXPECTED_FIELDS


def test_schema_requires_all_expected_fields(schema):
    assert set(schema["required"]) == REQUIRED_FIELDS


def test_schema_is_valid_draft2020(schema):
    # jsonschema raises if the schema itself is invalid.
    Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


def test_model_roundtrip_matches_schema(validator):
    ir = IntentIR(
        intent_id="abc123",
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
    validate(ir.model_dump(), validator.schema)


def test_model_rejects_unknown_fields():
    with pytest.raises(Exception):
        IntentIR(
            intent_id="x",
            goal="g",
            domain="d",
            action="a",
            object="o",
            desired_output="pdf",
            bogus_field="nope",
        )


def test_model_rejects_unsupported_schema_versions():
    with pytest.raises(Exception):
        IntentIR(
            schema_version="2.0",
            intent_id="x",
            goal="g",
            domain="d",
            action="a",
            object="o",
            desired_output="pdf",
        )


def test_schema_rejects_unsupported_versions(validator):
    payload = IntentIR(
        intent_id="x",
        goal="g",
        domain="d",
        action="a",
        object="o",
        desired_output="pdf",
    ).model_dump()
    payload["schema_version"] = "2.0"
    assert list(validator.iter_errors(payload))


def test_model_rejects_blank_required_strings():
    with pytest.raises(Exception):
        IntentIR(
            intent_id="x",
            goal="",
            domain="d",
            action="a",
            object="o",
            desired_output="pdf",
        )


def test_model_rejects_blank_intent_id():
    with pytest.raises(Exception):
        IntentIR(
            intent_id="   ",
            goal="g",
            domain="d",
            action="a",
            object="o",
            desired_output="pdf",
        )


def test_model_rejects_out_of_range_confidence():
    with pytest.raises(Exception):
        IntentIR(
            intent_id="x",
            goal="g",
            domain="d",
            action="a",
            object="o",
            desired_output="pdf",
            confidence=1.5,
        )


def test_model_defaults():
    ir = IntentIR(
        intent_id="x",
        goal="g",
        domain="d",
        action="a",
        object="o",
        desired_output="pdf",
    )
    assert ir.constraints == {}
    assert ir.schema_version == "1.1"
    assert ir.original_expression is None
    assert ir.state is IntentState.FORMED
    assert ir.preferences == {}
    assert ir.context == {}
    assert ir.authority == {}
    assert ir.disclosure == {}
    assert ir.success_conditions == []
    assert ir.confidence == 1.0
    assert ir.uncertainty == {}
    assert ir.fulfillment == {}
    assert ir.metadata == {}


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


def test_compiler_handles_example(validator):
    compiler = RuleBasedCompiler(default_year=2026)
    ir = compiler.compile("I need my August bank statement")
    assert ir.goal == "retrieve_financial_document"
    assert ir.domain == "banking"
    assert ir.action == "retrieve"
    assert ir.object == "account_statement"
    assert ir.constraints == {"period": "2026-08"}
    assert ir.desired_output == "pdf"
    assert ir.original_expression == "I need my August bank statement"
    assert ir.state is IntentState.FORMED
    # The compiled IR must validate against the schema.
    validate(ir.model_dump(), validator.schema)


def test_intent_preserves_uncertainty_and_separates_preferences():
    ir = IntentIR(
        intent_id="x",
        goal="find_option",
        domain="commerce",
        action="search",
        object="product",
        desired_output="json",
        state=IntentState.DISCOVERY,
        original_expression="Find me something suitable",
        constraints={"budget_max": 100},
        preferences={"color": "blue"},
        uncertainty={"missing": ["size"], "needs_clarification": True},
    )
    assert ir.state is IntentState.DISCOVERY
    assert ir.constraints["budget_max"] == 100
    assert ir.preferences["color"] == "blue"
    assert ir.uncertainty["needs_clarification"] is True


def test_compiler_generates_unique_intent_ids():
    compiler = RuleBasedCompiler(default_year=2026)
    a = compiler.compile("I need my August bank statement")
    b = compiler.compile("I need my August bank statement")
    assert a.intent_id != b.intent_id


def test_compiler_default_year_is_current():
    compiler = RuleBasedCompiler()
    ir = compiler.compile("I need my August bank statement")
    assert ir.constraints["period"] == f"{date.today().year}-08"


def test_compiler_rejects_empty_text():
    compiler = RuleBasedCompiler()
    with pytest.raises(ValueError):
        compiler.compile("   ")


def test_compiler_rejects_unrecognized_text():
    compiler = RuleBasedCompiler()
    with pytest.raises(ValueError):
        compiler.compile("please do something completely unrelated")


def test_compiler_interface_is_abstract():
    with pytest.raises(TypeError):
        IntentCompiler()  # type: ignore[abstract]


@pytest.mark.parametrize("revision", [True, 0, -1, "1", 1.5, None])
def test_intent_revision_rejects_coercion(revision):
    with pytest.raises(ValueError):
        IntentIR(intent_id="revision", goal="search", domain="commerce", action="search", object="products", desired_output="json", intent_revision=revision)


def test_intent_revision_round_trip_preserves_permissions(validator):
    intent = IntentIR(intent_id="revision", goal="search", domain="commerce", action="search", object="products", desired_output="json", intent_revision=3, authority={"permissions": ["read"]}, disclosure={"share": False})
    payload = intent.model_dump(mode="json")
    assert not list(validator.iter_errors(payload))
    restored = IntentIR.model_validate_json(intent.model_dump_json())
    assert restored == intent
    assert restored.intent_revision == 3
