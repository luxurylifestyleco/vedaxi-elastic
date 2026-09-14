"""Tests for the Elastic Web recipe data model (Phase 11).

Covers the Recipe/RecipeStep Pydantic schema, DAG validation, and the
RecipeStore storage + execution methods (create, version, retrieve,
deprecate, retire, execute).
"""

from __future__ import annotations

import os
import sys

import pytest

from recipe import Recipe, RecipeStatus, RecipeStep

# Make the telemetry package importable so tests can assert on the events
# emitted during execution. The telemetry package uses relative imports, so
# it must be imported as a package (via its parent dir on sys.path).
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "..")
if _PACKAGES_DIR not in sys.path:
    sys.path.insert(0, _PACKAGES_DIR)

from telemetry.event_bus import EventBus, ListSubscriber  # noqa: E402

from store import RecipeStore  # noqa: E402

EXPECTED_FIELDS = {
    "recipe_id",
    "intent_family",
    "version",
    "applicability_conditions",
    "invariants",
    "steps",
    "skills",
    "adaptation_points",
    "checkpoints",
    "success_conditions",
    "fallbacks",
    "freshness_policy",
    "metrics",
    "status",
    "provenance",
}

STEP_FIELDS = {
    "step_id",
    "action",
    "capability_id",
    "args",
    "depends_on",
    "checkpoints",
}


def _make_recipe(
    recipe_id: str = "r1",
    version: str = "1.0.0",
    steps: list | None = None,
) -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        intent_family="retrieve_financial_document",
        version=version,
        applicability_conditions=["user is authenticated"],
        invariants=["no data mutation"],
        steps=steps or [
            RecipeStep(
                step_id="s1",
                action="retrieve",
                capability_id="get_balance",
                args={"account_id": "acc-1"},
                checkpoints=["balance returned"],
            )
        ],
        skills=["document_retrieval"],
        adaptation_points=["output_format"],
        checkpoints=["document delivered"],
        success_conditions=["statement delivered as pdf"],
        fallbacks=[{"on": "timeout", "action": "retry"}],
        freshness_policy={"max_age_seconds": 3600},
        metrics=["latency", "success"],
        provenance={"author": "test", "created": "2026-09-10"},
    )


def _make_dag_recipe() -> Recipe:
    """A recipe whose steps form a DAG: s1 -> s2, s1 -> s3, s2 -> s4."""
    return Recipe(
        recipe_id="dag",
        intent_family="multi_step",
        steps=[
            RecipeStep(step_id="s1", action="fetch", capability_id="cap_a"),
            RecipeStep(
                step_id="s2",
                action="transform",
                capability_id="cap_b",
                depends_on=["s1"],
            ),
            RecipeStep(
                step_id="s3",
                action="enrich",
                capability_id="cap_c",
                depends_on=["s1"],
            ),
            RecipeStep(
                step_id="s4",
                action="finalize",
                capability_id="cap_d",
                depends_on=["s2", "s3"],
            ),
        ],
    )


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------


def test_recipe_defines_all_expected_fields():
    fields = set(Recipe.model_fields.keys())
    assert fields == EXPECTED_FIELDS


def test_recipe_step_defines_all_expected_fields():
    fields = set(RecipeStep.model_fields.keys())
    assert fields == STEP_FIELDS


def test_resolve_preserves_foundation_family_version_and_retirement_contract():
    store = RecipeStore()
    assert store.resolve("retrieve_financial_document") is None
    older = _make_recipe("older", "1.0.0")
    newer = _make_recipe("newer", "2.0.0")
    retired = _make_recipe("retired", "3.0.0")
    retired.status = RecipeStatus.RETIRED
    store.create(newer)
    store.create(older)  # Selection is version-based, not insertion recency.
    store.create(retired)
    assert store.resolve("retrieve_financial_document") is newer
    assert store.resolve("different_family") is None


def test_recipe_roundtrip():
    recipe = _make_recipe()
    dumped = recipe.model_dump()
    assert dumped["recipe_id"] == "r1"
    assert dumped["intent_family"] == "retrieve_financial_document"
    assert dumped["version"] == "1.0.0"
    assert dumped["status"] == "active"
    assert dumped["steps"][0]["step_id"] == "s1"
    assert Recipe.model_validate(dumped) == recipe


def test_recipe_rejects_unknown_fields():
    with pytest.raises(Exception):
        Recipe(
            recipe_id="r1",
            intent_family="f",
            bogus_field="nope",
        )


def test_recipe_rejects_blank_required_strings():
    with pytest.raises(Exception):
        Recipe(recipe_id="   ", intent_family="f")


def test_recipe_defaults():
    recipe = Recipe(recipe_id="r1", intent_family="f")
    assert recipe.version == "1.0.0"
    assert recipe.applicability_conditions == []
    assert recipe.invariants == []
    assert recipe.steps == []
    assert recipe.skills == []
    assert recipe.adaptation_points == []
    assert recipe.checkpoints == []
    assert recipe.success_conditions == []
    assert recipe.fallbacks == []
    assert recipe.freshness_policy == {}
    assert recipe.metrics == []
    assert recipe.status == RecipeStatus.ACTIVE
    assert recipe.provenance == {}


# ----------------------------------------------------------------------
# DAG validation
# ----------------------------------------------------------------------


def test_dag_recipe_validates():
    recipe = _make_dag_recipe()
    # Validation runs on construction; reaching here means it passed.
    assert len(recipe.steps) == 4


def test_dag_topological_order_respects_dependencies():
    recipe = _make_dag_recipe()
    order = recipe.topological_order()
    assert order[0] == "s1"
    assert order.index("s2") < order.index("s4")
    assert order.index("s3") < order.index("s4")
    assert set(order) == {"s1", "s2", "s3", "s4"}


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
                    depends_on=["does_not_exist"],
                ),
            ],
        )


def test_recipe_rejects_cyclic_dependencies():
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


# ----------------------------------------------------------------------
# Store: create / version / retrieve
# ----------------------------------------------------------------------


def test_create_stores_recipe():
    store = RecipeStore()
    recipe = _make_recipe()
    store.create(recipe)
    assert store.retrieve("r1") is recipe
    assert len(store) == 1


def test_create_duplicate_version_raises():
    store = RecipeStore()
    store.create(_make_recipe())
    with pytest.raises(ValueError):
        store.create(_make_recipe())


def test_version_creates_new_revision():
    store = RecipeStore()
    store.create(_make_recipe(version="1.0.0"))
    v2 = _make_recipe(version="2.0.0")
    store.version("r1", v2)
    assert store.retrieve("r1").version == "2.0.0"
    assert store.retrieve("r1", version="1.0.0").version == "1.0.0"
    assert len(store.list_versions("r1")) == 2


def test_version_missing_recipe_raises():
    store = RecipeStore()
    with pytest.raises(KeyError):
        store.version("nope", _make_recipe(version="2.0.0"))


def test_version_mismatched_id_raises():
    store = RecipeStore()
    store.create(_make_recipe())
    with pytest.raises(ValueError):
        store.version("r1", _make_recipe(recipe_id="other", version="2.0.0"))


def test_retrieve_missing_returns_none():
    assert RecipeStore().retrieve("nope") is None


# ----------------------------------------------------------------------
# Store: deprecate / retire
# ----------------------------------------------------------------------


def test_deprecate_marks_recipe():
    store = RecipeStore()
    store.create(_make_recipe())
    recipe = store.deprecate("r1")
    assert recipe.status == RecipeStatus.DEPRECATED
    assert store.retrieve("r1").status == RecipeStatus.DEPRECATED


def test_retire_marks_recipe():
    store = RecipeStore()
    store.create(_make_recipe())
    recipe = store.retire("r1")
    assert recipe.status == RecipeStatus.RETIRED
    assert store.retrieve("r1").status == RecipeStatus.RETIRED


def test_deprecate_missing_raises():
    with pytest.raises(KeyError):
        RecipeStore().deprecate("nope")


def test_retire_missing_raises():
    with pytest.raises(KeyError):
        RecipeStore().retire("nope")


# ----------------------------------------------------------------------
# Store: execute
# ----------------------------------------------------------------------


def test_execute_runs_steps_in_dependency_order():
    store = RecipeStore()
    store.create(_make_dag_recipe())
    executed: list[str] = []

    def executor(capability_id: str, args: dict) -> str:
        executed.append(capability_id)
        return f"result:{capability_id}"

    results = store.execute("dag", executor=executor)
    # s1 must run before s2/s3, and s4 last.
    assert executed[0] == "cap_a"
    assert executed.index("cap_b") < executed.index("cap_d")
    assert executed.index("cap_c") < executed.index("cap_d")
    assert executed[-1] == "cap_d"
    assert results == {
        "s1": "result:cap_a",
        "s2": "result:cap_b",
        "s3": "result:cap_c",
        "s4": "result:cap_d",
    }


def test_execute_emits_telemetry_events():
    bus = EventBus()
    collector = ListSubscriber()
    bus.subscribe(collector)
    store = RecipeStore(bus=bus)
    store.create(_make_dag_recipe())

    store.execute("dag", trace_id="trace-1", intent_id="intent-1")

    types = [e.event_type for e in collector.events]
    assert types[0] == "recipe.started"
    assert types[-1] == "recipe.completed"
    assert "recipe.step.started" in types
    assert "tool.called" in types
    assert "tool.completed" in types
    assert all(e.trace_id == "trace-1" for e in collector.events)
    assert all(e.intent_id == "intent-1" for e in collector.events)


def test_execute_missing_recipe_raises():
    with pytest.raises(KeyError):
        RecipeStore().execute("nope")


def test_execute_retired_recipe_raises():
    store = RecipeStore()
    store.create(_make_recipe())
    store.retire("r1")
    with pytest.raises(ValueError):
        store.execute("r1")


def test_execute_failure_emits_failed_event():
    bus = EventBus()
    collector = ListSubscriber()
    bus.subscribe(collector)
    store = RecipeStore(bus=bus)
    store.create(_make_dag_recipe())

    def failing_executor(capability_id: str, args: dict):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.execute("dag", executor=failing_executor)

    types = [e.event_type for e in collector.events]
    assert types[-1] == "execution.failed"
