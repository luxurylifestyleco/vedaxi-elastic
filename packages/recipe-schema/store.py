"""Recipe store for Elastic Web (Phase 11).

The store is the source of truth for recipes. It provides storage and
execution structure:

- ``create``: store a new recipe.
- ``version``: create a new version of an existing recipe.
- ``retrieve``: fetch a recipe (optionally a specific version).
- ``execute``: compatibility wrapper for the runtime DAG runner.
- ``deprecate``: mark a recipe deprecated.
- ``retire``: mark a recipe retired.

Execution emits telemetry events on an :class:`EventBus` (recipe.started,
recipe.step.started, tool.called, tool.completed, recipe.completed,
execution.failed). Telemetry is local-only: the store never sends data to an
external sink. If no bus is supplied, a private in-memory bus is created so
events remain locally inspectable.

This module implements recipe storage only. Execution is delegated to
``RecipeDAGRunner`` so the runtime has one execution authority. Automatic
recipe creation and optimization are out of scope.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from recipe import Recipe, RecipeStatus, RecipeStep

# An executor is any callable that runs a step's capability and returns a
# result. It receives the capability_id and the step's args.
Executor = Callable[[str, Dict[str, Any]], Any]

_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _compare_versions(left: str, right: str) -> int:
    """Compare SemVer values with a deterministic legacy fallback.

    Valid SemVer values sort above legacy values; two legacy values retain
    lexical ordering. This makes mixed-version resolution a total order.
    """
    left_match = _SEMVER.fullmatch(left)
    right_match = _SEMVER.fullmatch(right)
    if left_match is None or right_match is None:
        if left_match is not None or right_match is not None:
            return 1 if left_match is not None else -1
        return (left > right) - (left < right)

    left_parts = left_match.groups()
    right_parts = right_match.groups()
    release = tuple(map(int, left_parts[:3]))
    other_release = tuple(map(int, right_parts[:3]))
    if release != other_release:
        return (release > other_release) - (release < other_release)

    left_pre = left_parts[3]
    right_pre = right_parts[3]
    if left_pre is None or right_pre is None:
        return (left_pre is None) - (right_pre is None)
    for left_id, right_id in zip(left_pre.split("."), right_pre.split(".")):
        if left_id == right_id:
            continue
        if left_id.isdigit() and right_id.isdigit():
            return (int(left_id) > int(right_id)) - (int(left_id) < int(right_id))
        if left_id.isdigit() != right_id.isdigit():
            return -1 if left_id.isdigit() else 1
        return (left_id > right_id) - (left_id < right_id)
    return (len(left_pre.split(".")) > len(right_pre.split("."))) - (
        len(left_pre.split(".")) < len(right_pre.split("."))
    )


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

        Returns the recipe with the greatest semantic version whose
        ``intent_family`` matches and whose status is not ``RETIRED``, or
        ``None`` if absent. Values that are not valid semantic versions retain
        the previous lexical comparison behavior.
        """
        best: Optional[Recipe] = None
        for versions in self._recipes.values():
            for recipe in versions.values():
                if recipe.intent_family != intent_family:
                    continue
                if recipe.status == RecipeStatus.RETIRED:
                    continue
                if best is None or _compare_versions(recipe.version, best.version) > 0:
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
        """Compatibility wrapper for :class:`RecipeDAGRunner`.

        The legacy method returns only the step-result mapping. New callers
        should use ``RecipeDAGRunner.run`` and consume its full
        ``ExecutionResult``.

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

        # Local import avoids a recipe-schema -> recipe-runtime import cycle.
        try:
            from runner import RecipeDAGRunner  # type: ignore
        except ImportError:
            from recipe_runtime.runner import RecipeDAGRunner

        result = RecipeDAGRunner(executor=executor, bus=self.bus).run(
            recipe,
            executor=executor,
            trace_id=trace_id,
            intent_id=intent_id,
        )
        return result.results

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
