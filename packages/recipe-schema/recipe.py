"""Recipe data model for Elastic Web (Phase 11).

A recipe is a declarative, versioned execution plan that maps an intent
family to an ordered set of steps. This module defines the Pydantic v2
schema for recipes and their steps.

Scope: this covers recipe STORAGE and EXECUTION STRUCTURE only. Automatic
recipe creation and optimization are explicitly out of scope and are not
implemented here — a recipe is authored and stored as-is, and its steps are
executed in dependency (DAG) order.

Uses Pydantic v2.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecipeStatus(str, Enum):
    """Lifecycle status of a recipe."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class RecipeStep(BaseModel):
    """A single step in a recipe's execution DAG.

    Attributes:
        step_id: Unique id of the step within the recipe.
        action: The verb describing what the step does.
        capability_id: The capability that executes this step.
        args: Arguments passed to the capability.
        depends_on: Ids of steps that must complete before this one.
        checkpoints: Named checkpoints to verify after the step runs.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="Unique id of the step within the recipe.")
    action: str = Field(description="Verb describing what the step does.")
    capability_id: str = Field(
        description="The capability that executes this step."
    )
    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the capability.",
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="Ids of steps that must complete before this one.",
    )
    checkpoints: List[str] = Field(
        default_factory=list,
        description="Named checkpoints to verify after the step runs.",
    )

    @field_validator("step_id", "action", "capability_id")
    @classmethod
    def _required_strings_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v.strip()


class Recipe(BaseModel):
    """A declarative, versioned execution plan for an intent family.

    Attributes:
        recipe_id: Stable unique identifier for the recipe.
        intent_family: The family of intents this recipe serves.
        version: Semantic version of this recipe revision.
        applicability_conditions: Conditions under which the recipe applies.
        invariants: Conditions that must hold throughout execution.
        steps: Ordered list of :class:`RecipeStep` objects forming a DAG.
        skills: Skills the recipe draws on.
        adaptation_points: Points where execution may adapt.
        checkpoints: Recipe-level checkpoints.
        success_conditions: Conditions for the recipe to be considered
            successful.
        fallbacks: Fallback strategies if a step fails.
        freshness_policy: Policy governing how fresh the recipe's data must be.
        metrics: Metrics to collect during execution.
        status: Lifecycle status of the recipe.
        provenance: Origin/history of the recipe.
    """

    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(description="Stable unique identifier for the recipe.")
    intent_family: str = Field(
        description="The family of intents this recipe serves."
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version of this recipe revision.",
    )
    applicability_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions under which the recipe applies.",
    )
    invariants: List[str] = Field(
        default_factory=list,
        description="Conditions that must hold throughout execution.",
    )
    steps: List[RecipeStep] = Field(
        default_factory=list,
        description="Ordered list of RecipeStep objects forming a DAG.",
    )
    skills: List[str] = Field(
        default_factory=list,
        description="Skills the recipe draws on.",
    )
    adaptation_points: List[str] = Field(
        default_factory=list,
        description="Points where execution may adapt.",
    )
    checkpoints: List[str] = Field(
        default_factory=list,
        description="Recipe-level checkpoints.",
    )
    success_conditions: List[str] = Field(
        default_factory=list,
        description="Conditions for the recipe to be considered successful.",
    )
    fallbacks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Fallback strategies if a step fails.",
    )
    freshness_policy: Dict[str, Any] = Field(
        default_factory=dict,
        description="Policy governing data freshness.",
    )
    metrics: List[str] = Field(
        default_factory=list,
        description="Metrics to collect during execution.",
    )
    status: RecipeStatus = Field(
        default=RecipeStatus.ACTIVE,
        description="Lifecycle status of the recipe.",
    )
    provenance: Dict[str, Any] = Field(
        default_factory=dict,
        description="Origin/history of the recipe.",
    )

    @field_validator("recipe_id", "intent_family")
    @classmethod
    def _required_strings_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v.strip()

    @model_validator(mode="after")
    def _validate_dag(self) -> "Recipe":
        """Validate that steps form a valid DAG.

        Every ``depends_on`` reference must point to an existing step, and
        the dependency graph must be acyclic. Raises ``ValueError`` otherwise.
        """
        step_ids = {s.step_id for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(
                        f"step {step.step_id!r} depends on unknown step {dep!r}"
                    )
        self.topological_order()
        return self

    def topological_order(self) -> List[str]:
        """Return step_ids in dependency order (Kahn's algorithm).

        Returns:
            A list of step_ids such that every step appears after all of its
            dependencies.

        Raises:
            ValueError: If the steps contain a cycle.
        """
        indegree: Dict[str, int] = {s.step_id: 0 for s in self.steps}
        dependents: Dict[str, List[str]] = {s.step_id: [] for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                indegree[step.step_id] += 1
                dependents[dep].append(step.step_id)

        ready = [sid for sid, deg in indegree.items() if deg == 0]
        order: List[str] = []
        while ready:
            sid = ready.pop(0)
            order.append(sid)
            for dependent in dependents[sid]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)

        if len(order) != len(self.steps):
            raise ValueError("recipe steps contain a cycle")
        return order

    @classmethod
    def new_id(cls) -> str:
        """Generate a fresh recipe_id (UUID4 hex)."""
        return uuid.uuid4().hex
