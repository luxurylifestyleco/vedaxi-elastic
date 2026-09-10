"""Phase 16 — Recipe tests.

Verifies that the recipe store (store.py, recipe.py) creates, retrieves,
versions, and executes recipes, and that execution emits telemetry events.
"""

from __future__ import annotations

import os
import sys

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("recipe-schema", "telemetry"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

from recipe import Recipe, RecipeStatus, RecipeStep  # noqa: E402
from store import RecipeStore  # noqa: E402
from telemetry.event_bus import EventBus, ListSubscriber  # noqa: E402


def _make_recipe(recipe_id="r1", version="1.0.0", steps=None) -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        intent_family="retrieve_statement",
        version=version,
        steps=steps
        or [
            RecipeStep(
                step_id="s1",
                action="retrieve",
                capability_id="get_statement",
                args={"period": "2026-08"},
            )
        ],
    )


def _make_dag_recipe() -> Recipe:
    return Recipe(
        recipe_id="dag",
        intent_family="multi_step",
        steps=[
            RecipeStep(step_id="s1", action="fetch", capability_id="cap_a"),
            RecipeStep(
                step_id="s2", action="transform", capability_id="cap_b", depends_on=["s1"]
            ),
            RecipeStep(
                step_id="s3", action="finalize", capability_id="cap_c", depends_on=["s2"]
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Create / retrieve / version
# ---------------------------------------------------------------------------


def test_create_and_retrieve():
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
    store.version("r1", _make_recipe(version="2.0.0"))
    assert store.retrieve("r1").version == "2.0.0"
    assert store.retrieve("r1", version="1.0.0").version == "1.0.0"
    assert len(store.list_versions("r1")) == 2


def test_retrieve_missing_returns_none():
    assert RecipeStore().retrieve("nope") is None


def test_deprecate_and_retire():
    store = RecipeStore()
    store.create(_make_recipe())
    assert store.deprecate("r1").status == RecipeStatus.DEPRECATED
    assert store.retire("r1").status == RecipeStatus.RETIRED


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_execute_runs_steps_in_dependency_order():
    store = RecipeStore()
    store.create(_make_dag_recipe())
    executed: list[str] = []

    def executor(capability_id, args):
        executed.append(capability_id)
        return f"result:{capability_id}"

    results = store.execute("dag", executor=executor)
    assert executed == ["cap_a", "cap_b", "cap_c"]
    assert results == {
        "s1": "result:cap_a",
        "s2": "result:cap_b",
        "s3": "result:cap_c",
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

    def failing_executor(capability_id, args):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.execute("dag", executor=failing_executor)

    types = [e.event_type for e in collector.events]
    assert types[-1] == "execution.failed"
