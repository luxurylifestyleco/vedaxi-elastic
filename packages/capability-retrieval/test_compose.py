"""Capability-book composition. The planner names no protocol."""

from __future__ import annotations

import pytest

from capability import Capability
from compiler import RuleBasedCompiler
from compose import compose_recipe


def _cap(cap_id: str, **metadata) -> Capability:
    return Capability(
        id=cap_id,
        name=cap_id,
        description=f"prepare outreach sales {cap_id}",
        domain="sales",
        metadata=metadata,
    )


def test_compose_orders_by_stage_and_withholds_sensitive():
    intent = RuleBasedCompiler().compile(
        "Find suitable prospects, research their companies, prepare a personalized outreach plan, "
        "and report which prospects need human approval before contact."
    )
    recipe = compose_recipe(
        intent,
        [
            _cap("late", intent_goals=["prepare_outreach"], stage=2, binds={"left": 1}),
            _cap("send", intent_goals=["prepare_outreach"], sensitive=True, external_side_effect=True),
            _cap("early", intent_goals=["prepare_outreach"], stage=1),
            _cap("other-goal", intent_goals=["retrieve_financial_document"], stage=1),
        ],
    )
    assert [step.capability_id for step in recipe.steps] == ["early", "late"]
    assert recipe.steps[1].depends_on == ["stage-1"]
    assert recipe.steps[1].args == {"left": {"$from": "stage-1"}}
    assert recipe.checkpoints == ["human_approval_required:send"]
    assert "send" in recipe.provenance["withheld"]


def test_compose_rejects_missing_or_duplicate_stage():
    intent = RuleBasedCompiler().compile(
        "Find prospects and prepare an outreach plan before contact."
    )
    with pytest.raises(ValueError, match="no stage"):
        compose_recipe(intent, [_cap("bare", intent_goals=["prepare_outreach"])])
    with pytest.raises(ValueError, match="duplicate stage"):
        compose_recipe(
            intent,
            [
                _cap("a", intent_goals=["prepare_outreach"], stage=1),
                _cap("b", intent_goals=["prepare_outreach"], stage=1),
            ],
        )
