"""Compose a Recipe from capability-book metadata.

The capability book decides membership and order. This module does not
know agents, tools, or websites. A capability is eligible when its
metadata ``intent_goals`` contains the intent goal and it declares a
unique integer ``stage``. ``binds`` names earlier stages whose results
become step arguments. Sensitive capabilities are withheld, not executed.

ponytail: one goal, unique integer stages, no search over alternative plans.
Upgrade path: a planner that orders by produces/consumes types.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RECIPE = os.path.join(_PACKAGES, "recipe-schema")
if _RECIPE not in sys.path:
    sys.path.insert(0, _RECIPE)

from capability import Capability
from intent_ir import IntentIR
from recipe import Recipe, RecipeStep


def compose_recipe(
    intent: IntentIR,
    capabilities: List[Capability],
    *,
    recipe_id: str = "recipe.composed",
) -> Recipe:
    """Build one recipe for ``intent.goal`` from book metadata."""
    goal = intent.goal
    eligible: List[Capability] = []
    withheld: List[str] = []

    for cap in capabilities:
        goals = cap.metadata.get("intent_goals") or []
        if goal not in goals:
            continue
        if cap.metadata.get("sensitive") is True or cap.metadata.get("external_side_effect") is True:
            withheld.append(cap.id)
            continue
        if "stage" not in cap.metadata:
            raise ValueError(f"{cap.id} declares {goal} but has no stage")
        eligible.append(cap)

    if not eligible:
        raise ValueError(f"no capabilities in the book for goal {goal}")

    eligible.sort(key=lambda cap: int(cap.metadata["stage"]))
    stages = [int(cap.metadata["stage"]) for cap in eligible]
    if len(stages) != len(set(stages)):
        raise ValueError("duplicate stage; the book must give a total order")

    stage_to_step = {int(cap.metadata["stage"]): f"stage-{int(cap.metadata['stage'])}" for cap in eligible}
    steps: List[RecipeStep] = []
    previous: str | None = None

    for cap in eligible:
        stage = int(cap.metadata["stage"])
        binds: Dict[str, object] = cap.metadata.get("binds") or {}
        args: Dict[str, object] = {}
        for arg_name, source_stage in binds.items():
            source = int(source_stage)
            if source >= stage or source not in stage_to_step:
                raise ValueError(f"{cap.id} bind {arg_name}={source} is not an earlier stage")
            args[arg_name] = {"$from": stage_to_step[source]}
        for key in cap.inputs:
            if key in args or key not in intent.constraints:
                continue
            args[key] = intent.constraints[key]
        step_id = stage_to_step[stage]
        steps.append(
            RecipeStep(
                step_id=step_id,
                action=intent.action,
                capability_id=cap.id,
                args=args,
                depends_on=[previous] if previous else [],
            )
        )
        previous = step_id

    return Recipe(
        recipe_id=recipe_id,
        intent_family=intent.goal,
        steps=steps,
        success_conditions=list(intent.success_conditions),
        checkpoints=[f"human_approval_required:{cap_id}" for cap_id in withheld],
        provenance={"composer": "capability-book", "withheld": withheld},
    )
