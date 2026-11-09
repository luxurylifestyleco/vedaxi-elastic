from __future__ import annotations

import os
import sys

_PACKAGES_DIR = os.path.dirname(os.path.dirname(__file__))
_SCHEMA_DIR = os.path.join(_PACKAGES_DIR, "recipe-schema")
for _path in (_PACKAGES_DIR, _SCHEMA_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from recipe import Recipe, RecipeStep  # noqa: E402
from runner import ExecutionResult, RecipeDAGRunner  # noqa: E402
from store import RecipeStore  # noqa: E402


def test_store_execute_delegates_to_recipe_dag_runner(monkeypatch):
    store = RecipeStore()
    recipe = Recipe(
        recipe_id="authority-test",
        intent_family="test",
        steps=[RecipeStep(step_id="step", action="run", capability_id="cap")],
    )
    store.create(recipe)
    calls = []

    def fake_run(self, recipe_arg, **kwargs):
        calls.append((recipe_arg.recipe_id, kwargs))
        return ExecutionResult(
            recipe_id=recipe_arg.recipe_id,
            intent_family=recipe_arg.intent_family,
            results={"step": "ok"},
            metrics={},
        )

    monkeypatch.setattr(RecipeDAGRunner, "run", fake_run)

    assert store.execute("authority-test") == {"step": "ok"}
    assert calls == [("authority-test", {"executor": None, "trace_id": None, "intent_id": None})]
