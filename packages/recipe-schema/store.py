"""Recipe store for Elastic Web (Phase 11).

The store is the source of truth for recipes. It provides storage and
execution structure:

- ``create``: store a new recipe.
- ``version``: create a new version of an existing recipe.
- ``retrieve``: fetch a recipe (optionally a specific version).
- ``execute``: run a recipe's steps in dependency (DAG) order.
- ``deprecate``: mark a recipe deprecated.
- ``retire``: mark a recipe retired.

Execution emits telemetry events on an :class:`EventBus` (recipe.started,
recipe.step.started, tool.called, tool.completed, recipe.completed,
execution.failed). Telemetry is local-only: the store never sends data to an
external sink. If no bus is supplied, a private in-memory bus is created so
events remain locally inspectable.

This module implements recipe STORAGE and EXECUTION STRUCTURE only. Automatic
recipe creation and optimization are out of scope.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from recipe import Recipe, RecipeStatus, RecipeStep

# An executor is any callable that runs a step's capability and returns a
# result. It receives the capability_id and the step's args.
Executor = Callable[[str, Dict[str, Any]], Any]


class RecipeStore:
    """An in-memory store of recipes keyed by recipe_id and version.

    Attributes:
        bus: The :class:`EventBus` used for execution telemetry.
    """

    def __init__(self, bus: Any = None) -> None:
        # recipes[recipe_id][version] -> Recipe
        self._recipes: Dict[str, Dict[str, Recipe]] = {}
        # Track the latest version per recipe_id.
        self._latest: Dict[str, str] = {}
        if bus is None:
            from telemetry.event_bus import EventBus

            bus = EventBus()
        self.bus = bus

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def create(self, recipe: Recipe) -> Recipe:
        """Store a new recipe.

        Args:
            recipe: The recipe to store.

        Returns:
            The stored recipe.

        Raises:
            ValueError: If a recipe with the same id and version already
                exists.
        """
        versions = self._recipes.setdefault(recipe.recipe_id, {})
        if recipe.version in versions:
            raise ValueError(
                f"recipe {recipe.recipe_id!r} version {recipe.version!r} "
                "already exists"
            )
        versions[recipe.version] = recipe
        self._latest[recipe.recipe_id] = recipe.version
        return recipe

    def version(self, recipe_id: str, new_recipe: Recipe) -> Recipe:
        """Create a new version of an existing recipe.

        The new recipe must share the same ``recipe_id`` and carry a
        different ``version``.

        Args:
            recipe_id: The id of the recipe to version.
            new_recipe: The new revision to store.

        Returns:
            The newly stored revision.

        Raises:
            KeyError: If ``recipe_id`` is not stored.
            ValueError: If ``new_recipe.recipe_id`` differs, or the version
                already exists.
        """
        if recipe_id not in self._recipes:
            raise KeyError(f"recipe not found: {recipe_id}")
        if new_recipe.recipe_id != recipe_id:
            raise ValueError(
                f"new recipe id {new_recipe.recipe_id!r} does not match "
                f"{recipe_id!r}"
            )
        return self.create(new_recipe)

    def retrieve(
        self, recipe_id: str, version: Optional[str] = None
    ) -> Optional[Recipe]:
        """Fetch a recipe.

        Args:
            recipe_id: The id of the recipe to fetch.
            version: The specific version to fetch. If ``None``, the latest
                version is returned.

        Returns:
            The recipe, or ``None`` if not found.
        """
        versions = self._recipes.get(recipe_id)
        if not versions:
            return None
        if version is None:
            version = self._latest.get(recipe_id)
        return versions.get(version)

    def list_versions(self, recipe_id: str) -> List[Recipe]:
        """Return all versions of a recipe, in insertion order."""
        return list(self._recipes.get(recipe_id, {}).values())

    def resolve(self, intent_family: str) -> Optional[Recipe]:
        """Resolve the latest active recipe for an intent family.

        Returns the recipe with the greatest version string whose
        ``intent_family`` matches and whose status is not ``RETIRED``, or
        ``None`` if absent. Existing lexical version ordering is preserved;
        this helper does not perform semantic-version parsing or promotion.
        """
        best: Optional[Recipe] = None
        for versions in self._recipes.values():
            for recipe in versions.values():
                if recipe.intent_family != intent_family:
                    continue
                if recipe.status == RecipeStatus.RETIRED:
                    continue
                if best is None or recipe.version > best.version:
                    best = recipe
        return best

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def deprecate(self, recipe_id: str) -> Recipe:
        """Mark a recipe deprecated.

        Args:
            recipe_id: The id of the recipe to deprecate.

        Returns:
            The updated recipe.

        Raises:
            KeyError: If the recipe is not stored.
        """
        recipe = self._require(recipe_id)
        recipe.status = RecipeStatus.DEPRECATED
        return recipe

    def retire(self, recipe_id: str) -> Recipe:
        """Mark a recipe retired.

        Args:
            recipe_id: The id of the recipe to retire.

        Returns:
            The updated recipe.

        Raises:
            KeyError: If the recipe is not stored.
        """
        recipe = self._require(recipe_id)
        recipe.status = RecipeStatus.RETIRED
        return recipe

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        recipe_id: str,
        executor: Optional[Executor] = None,
        trace_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a recipe's steps in dependency (DAG) order.

        Steps are run in topological order: a step runs only after all of its
        dependencies have completed. Each step is dispatched to ``executor``
        (or a default no-op executor that records the call) and telemetry
        events are emitted on the store's bus.

        Args:
            recipe_id: The id of the recipe to execute.
            executor: Callable ``(capability_id, args) -> result`` used to run
                each step. If ``None``, a default executor records the call
                and returns ``None``.
            trace_id: Correlation id for telemetry. Defaults to a fresh id.
            intent_id: Optional intent id attached to telemetry.
            version: Specific recipe version to execute. Defaults to latest.

        Returns:
            A dict mapping step_id to the executor's result for that step.

        Raises:
            KeyError: If the recipe is not stored.
        """
        recipe = self.retrieve(recipe_id, version=version)
        if recipe is None:
            raise KeyError(f"recipe not found: {recipe_id}")
        if recipe.status == RecipeStatus.RETIRED:
            raise ValueError(f"recipe is retired: {recipe_id}")

        trace_id = trace_id or uuid.uuid4().hex
        executor = executor or self._default_executor
        order = recipe.topological_order()
        step_by_id = {s.step_id: s for s in recipe.steps}

        self.bus.emit(
            "recipe.started",
            trace_id=trace_id,
            intent_id=intent_id,
            payload={
                "recipe_id": recipe.recipe_id,
                "recipe_version": recipe.version,
            },
        )

        results: Dict[str, Any] = {}
        try:
            for step_id in order:
                step = step_by_id[step_id]
                self.bus.emit(
                    "recipe.step.started",
                    trace_id=trace_id,
                    intent_id=intent_id,
                    payload={
                        "recipe_id": recipe.recipe_id,
                        "step_id": step.step_id,
                        "capability_id": step.capability_id,
                    },
                )
                self.bus.emit(
                    "tool.called",
                    trace_id=trace_id,
                    intent_id=intent_id,
                    payload={
                        "tool": step.capability_id,
                        "args": step.args,
                    },
                )
                result = executor(step.capability_id, step.args)
                results[step.step_id] = result
                self.bus.emit(
                    "tool.completed",
                    trace_id=trace_id,
                    intent_id=intent_id,
                    payload={
                        "tool": step.capability_id,
                        "status": "completed",
                    },
                )
        except Exception as exc:  # noqa: BLE001 - record any failure
            self.bus.emit(
                "execution.failed",
                trace_id=trace_id,
                intent_id=intent_id,
                payload={
                    "recipe_id": recipe.recipe_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise

        self.bus.emit(
            "recipe.completed",
            trace_id=trace_id,
            intent_id=intent_id,
            payload={
                "recipe_id": recipe.recipe_id,
                "recipe_version": recipe.version,
                "steps": order,
            },
        )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require(self, recipe_id: str) -> Recipe:
        recipe = self.retrieve(recipe_id)
        if recipe is None:
            raise KeyError(f"recipe not found: {recipe_id}")
        return recipe

    @staticmethod
    def _default_executor(capability_id: str, args: Dict[str, Any]) -> Any:
        """Default executor: record the call and return ``None``."""
        return None

    def __len__(self) -> int:
        return len(self._recipes)
