"""Offline contract checks; shopping is a state fixture, not a provider."""
from copy import deepcopy
import json

import pytest

from conversation_state import (
    CompactState, FieldSpec, RESEARCH_SCHEMA, StateField, TaskSchema,
    apply_patch, new_state, validate_state,
)


SHOPPING = TaskSchema(
    schema_id="shopping_fixture",
    fields={
        "brand": FieldSpec(), "line": FieldSpec(),
        "size": FieldSpec(kind="number", minimum=1, maximum=25, subject_scoped=True),
        "size_system": FieldSpec(choices=["US", "UK", "EU"], subject_scoped=True),
        "budget": FieldSpec(kind="number", minimum=0, maximum=1000000),
        "currency": FieldSpec(choices=["USD", "INR", "EUR"]),
        "recipient": FieldSpec(subject_scoped=True),
    },
    derived_dependencies={"products": ["brand", "line", "size", "size_system", "budget", "currency", "recipient"],
                          "recommendation": ["products"]},
)


def test_shopping_revisions_preserve_unmentioned_fields_and_invalidate_transitively():
    state = new_state(SHOPPING, subject="self")
    state = apply_patch(state, SHOPPING, {"brand": "Nike", "size": 10, "size_system": "US", "budget": 150, "currency": "USD"}, [], 1).state
    for line in ("Jordan", "LeBron"):
        result = apply_patch(state, SHOPPING, {"line": line}, [], state.revision)
        assert result.state.fields["size"].value == 10
        assert result.state.fields["budget"].value == 150
        assert result.invalidated == ["products", "recommendation"]
        assert "size" in result.preserved
        state = result.state


def test_subject_change_drops_bound_values_but_preserves_explicit_replacement():
    state = apply_patch(new_state(SHOPPING, "self"), SHOPPING,
                        {"size": 10, "size_system": "US", "budget": 150}, [], 1).state
    result = apply_patch(state, SHOPPING, {"recipient": "child", "size": 4}, [], 2, subject="child")
    assert result.state.fields["size"].value == 4
    assert "size_system" in result.state.cleared
    assert "size_system" not in result.state.fields
    assert result.state.fields["budget"].value == 150
    assert result.invalidated == ["products", "recommendation"]


def test_explicit_clear_differs_from_unknown_and_repeated_clear_is_noop():
    state = new_state(RESEARCH_SCHEMA)
    assert "query" not in state.fields and "query" not in state.cleared
    result = apply_patch(state, RESEARCH_SCHEMA, {}, ["query"], 1)
    assert result.state.cleared == ["query"] and result.needs_clarification == ["query"]
    assert result.state.revision == 2
    assert apply_patch(result.state, RESEARCH_SCHEMA, {}, ["query"], 2).state == result.state


def test_noop_preserves_provenance_and_explicit_remember_is_only_an_effect():
    state = CompactState(schema_id="research", fields={"query": StateField(value="coastal erosion", source="verified_run")})
    result = apply_patch(state, RESEARCH_SCHEMA, {"query": "coastal erosion"}, [], 1)
    assert result.state == state and result.remember == {} and result.changed == []
    remembered = apply_patch(state, RESEARCH_SCHEMA, {}, [], 1, remember=["query"])
    assert remembered.state == state and remembered.remember["query"].value == "coastal erosion"
    remembered.remember["query"].value = "changed effect"
    assert state.fields["query"].value == "coastal erosion"


@pytest.mark.parametrize("changes,clears,revision,remember", [
    ({"unknown": "x"}, [], 1, []), ({"query": "ab"}, [], 1, []),
    ({"query": 123}, [], 1, []), ({"query": "valid"}, ["query"], 1, []),
    ({"query": "valid"}, [], 0, []), ({}, [], True, []),
    ({}, [], 1, ["query"]), ({}, ["query", "query"], 1, []),
])
def test_invalid_patch_is_atomic(changes, clears, revision, remember):
    state = new_state(RESEARCH_SCHEMA)
    before = deepcopy(state)
    with pytest.raises(ValueError):
        apply_patch(state, RESEARCH_SCHEMA, changes, clears, revision, remember=remember)
    assert state == before


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1, "100", 10**1000])
def test_numeric_bounds_and_strict_types(value):
    with pytest.raises(ValueError):
        apply_patch(new_state(SHOPPING), SHOPPING, {"budget": value}, [], 1)


def test_state_validation_rejects_unknowns_invalid_revisions_and_extra_payload():
    for payload in (
        {"schema_id": "research", "fields": {"wrong": {"value": "x"}}},
        {"schema_id": "research", "invalidated": {"results": 2}},
        {"schema_id": "research", "fields": {"query": {"value": "abc"}}, "cleared": ["query"]},
        {"schema_id": "research", "transcript": []},
        {"schema_id": "different"},
    ):
        with pytest.raises(ValueError):
            validate_state(payload, RESEARCH_SCHEMA)


def test_compactness_reset_and_no_aliasing():
    state = new_state(RESEARCH_SCHEMA)
    for n in range(100):
        previous = state
        state = apply_patch(state, RESEARCH_SCHEMA, {"query": f"query {n:03}"}, [], state.revision).state
        assert previous.revision == n + 1
    assert len(json.dumps(state.model_dump())) < 500
    assert set(state.invalidated) == {"results", "summary"}
    reset = new_state(RESEARCH_SCHEMA)
    assert reset.revision == 1 and reset.fields == {} and reset.cleared == []


def test_schema_rejects_cycles_and_unknown_dependencies():
    for dependencies in ({"a": ["b"], "b": ["a"]}, {"a": ["missing"]}):
        with pytest.raises(ValueError):
            TaskSchema(schema_id="bad", fields={"query": FieldSpec()}, derived_dependencies=dependencies)


def test_stale_revision_has_distinct_conflict_type():
    from conversation_state import StateConflict
    with pytest.raises(StateConflict):
        apply_patch(new_state(RESEARCH_SCHEMA), RESEARCH_SCHEMA, {}, [], 2)
