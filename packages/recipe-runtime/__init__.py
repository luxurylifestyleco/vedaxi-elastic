"""Recipe Runtime execution package for Elastic Web."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure sibling recipe-schema is importable
_SCHEMA_DIR = str(Path(__file__).resolve().parent.parent / "recipe-schema")
if _SCHEMA_DIR not in sys.path:
    sys.path.insert(0, _SCHEMA_DIR)

try:
    from recipe_schema import Recipe, RecipeStep, RecipeStatus, RecipeStore, Executor
except ImportError:
    try:
        from .recipe import Recipe, RecipeStep, RecipeStatus  # type: ignore
        from .store import RecipeStore, Executor  # type: ignore
    except (ImportError, ValueError):
        from recipe import Recipe, RecipeStep, RecipeStatus  # type: ignore
        from store import RecipeStore, Executor  # type: ignore


def execute_recipe(
    store: RecipeStore,
    recipe_id: str,
    args: Optional[Dict[str, Any]] = None,
    executor: Optional[Executor] = None,
    trace_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a recipe from the store with the given executor and args.

    Args:
        store: The RecipeStore instance containing the recipe.
        recipe_id: Identifier of the recipe to run.
        args: Input parameters passed to recipe steps.
        executor: Callable that executes individual capability actions.
        trace_id: Correlation id for telemetry.
        intent_id: Optional intent id attached to telemetry.
        version: Specific recipe version to execute (defaults to latest active).

    Returns:
        Dict mapping step_id to step execution result.
    """
    return store.execute(
        recipe_id=recipe_id,
        executor=executor,
        trace_id=trace_id,
        intent_id=intent_id,
        version=version,
    )


__all__ = [
    "Recipe",
    "RecipeStep",
    "RecipeStatus",
    "RecipeStore",
    "Executor",
    "execute_recipe",
]
