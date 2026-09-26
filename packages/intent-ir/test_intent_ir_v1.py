"""Schema validation for Intent IR V1.

Tests the schema, not a parser and not an LLM.
"""

from __future__ import annotations

import json
import os

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "intent_ir.schema.json")
EXAMPLES_PATH = os.path.join(HERE, "intent_ir_examples.json")

REQUIRED_UTTERANCES = [
    "Call Mom.",
    "Open WhatsApp.",
    "Search YouTube for jazz.",
    "Send this to Mom.",
    "Play the second one.",
    "Find a flight to London.",
    "Nothing overnight.",
    "I'd prefer Emirates.",
    "Something sarcastic.",
    "Actually, make that Friday.",
    "Find somewhere for dinner tonight.",
    "Book that one.",
]


@pytest.fixture(scope="module")
def schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def examples() -> dict:
    with open(EXAMPLES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema)


def test_schema_is_valid_draft2020(schema: dict) -> None:
    Draft202012Validator.check_schema(schema)


def test_schema_version_is_v1(schema: dict) -> None:
    assert schema["properties"]["schema_version"]["const"] == "1.0"


def test_schema_forbids_unknown_top_level_fields(schema: dict) -> None:
    assert schema["additionalProperties"] is False


def test_only_identity_fields_are_required(schema: dict) -> None:
    assert set(schema["required"]) == {"schema_version", "intent_id", "revision"}


def test_corpus_covers_required_utterances(examples: dict) -> None:
    seen = {row["utterance"] for row in examples["examples"]}
    missing = [u for u in REQUIRED_UTTERANCES if u not in seen]
    assert missing == []


def test_corpus_size_is_in_range(examples: dict) -> None:
    n = len(examples["examples"])
    assert 20 <= n <= 40


def test_every_corpus_intent_validates(validator: Draft202012Validator, examples: dict) -> None:
    errors = []
    for row in examples["examples"]:
        try:
            validate(row["intent"], validator.schema)
        except ValidationError as exc:
            errors.append(f"{row['id']}: {exc.message}")
    assert errors == []


def test_simple_intent_omits_optional_structure(examples: dict) -> None:
    call_mom = next(r for r in examples["examples"] if r["id"] == "call-mom")
    intent = call_mom["intent"]
    assert "slots" not in intent
    assert "preferences" not in intent
    assert "exclusions" not in intent
    assert "domain" not in intent
    assert "target" not in intent


def test_unresolved_deixis_has_no_invented_value(examples: dict) -> None:
    send = next(r for r in examples["examples"] if r["id"] == "send-this-to-mom")
    obj = send["intent"]["object"]
    assert obj["status"] == "unresolved"
    assert obj.get("value") in (None, )
    assert obj["surface"] == "this"


def test_preference_is_not_collapsed_into_a_slot(examples: dict) -> None:
    row = next(r for r in examples["examples"] if r["id"] == "flight-prefer-emirates")
    intent = row["intent"]
    slot_names = {s["name"] for s in intent.get("slots", [])}
    assert "airline" not in slot_names
    prefs = intent["preferences"]
    assert any(p["path"] == "airline" and p["value"] == "Emirates" for p in prefs)


def test_exclusion_is_not_rewritten_as_a_slot(examples: dict) -> None:
    row = next(r for r in examples["examples"] if r["id"] == "flight-nothing-overnight")
    intent = row["intent"]
    slot_names = {s["name"] for s in intent.get("slots", [])}
    assert "schedule" not in slot_names
    assert any(e["path"] == "schedule" and e["value"] == "overnight" for e in intent["exclusions"])


def test_later_turn_reuses_intent_id_and_bumps_revision(examples: dict) -> None:
    by_id = {r["id"]: r for r in examples["examples"]}
    r1 = by_id["find-flight-london"]["intent"]
    r4 = by_id["flight-friday"]["intent"]
    assert r1["intent_id"] == r4["intent_id"] == "flight-london"
    assert r1["revision"] == 1
    assert r4["revision"] == 4
    assert r4["schema_version"] == r1["schema_version"] == "1.0"
    # Preference and exclusion survive the Friday update.
    assert any(p["path"] == "airline" for p in r4["preferences"])
    assert any(e["path"] == "schedule" for e in r4["exclusions"])


def test_hmm_is_valid_with_only_identity(validator: Draft202012Validator) -> None:
    validate(
        {"schema_version": "1.0", "intent_id": "hmm", "revision": 1},
        validator.schema,
    )


def test_rejects_unknown_top_level_field(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "1.0",
                "intent_id": "x",
                "revision": 1,
                "capability_id": "nope",
            },
            validator.schema,
        )


def test_rejects_missing_intent_id(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate({"schema_version": "1.0", "revision": 1}, validator.schema)


def test_rejects_wrong_schema_version(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {"schema_version": "2.0", "intent_id": "x", "revision": 1},
            validator.schema,
        )


def test_rejects_revision_zero(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {"schema_version": "1.0", "intent_id": "x", "revision": 0},
            validator.schema,
        )


def test_rejects_resolved_slot_without_value(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "1.0",
                "intent_id": "x",
                "revision": 1,
                "action": {"status": "resolved"},
            },
            validator.schema,
        )


def test_rejects_resolved_slot_with_null_value(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "1.0",
                "intent_id": "x",
                "revision": 1,
                "action": {"status": "resolved", "value": None},
            },
            validator.schema,
        )


def test_rejects_slot_item_without_name(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "1.0",
                "intent_id": "x",
                "revision": 1,
                "slots": [{"status": "resolved", "value": "jazz"}],
            },
            validator.schema,
        )


def test_rejects_unknown_slot_status(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "1.0",
                "intent_id": "x",
                "revision": 1,
                "action": {"status": "guessed", "value": "call"},
            },
            validator.schema,
        )


def test_rejects_unknown_slot_property(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "schema_version": "1.0",
                "intent_id": "x",
                "revision": 1,
                "action": {"status": "resolved", "value": "call", "confidence": 0.9},
            },
            validator.schema,
        )


def test_unresolved_action_is_valid(validator: Draft202012Validator) -> None:
    validate(
        {
            "schema_version": "1.0",
            "intent_id": "x",
            "revision": 1,
            "action": {"status": "unresolved", "value": None},
        },
        validator.schema,
    )


def test_v1_module_validates_call_mom() -> None:
    from intent_ir_v1 import validate_v1

    doc = validate_v1(
        {
            "schema_version": "1.0",
            "intent_id": "call-mom",
            "revision": 1,
            "action": {"status": "resolved", "value": "call"},
            "object": {"status": "resolved", "value": "Mom"},
        }
    )
    assert doc["intent_id"] == "call-mom"


def test_v1_module_rejects_extra_field() -> None:
    from intent_ir_v1 import try_validate_v1

    ok, _, err = try_validate_v1(
        {
            "schema_version": "1.0",
            "intent_id": "x",
            "revision": 1,
            "capability_id": "nope",
        }
    )
    assert ok is False
    assert err
