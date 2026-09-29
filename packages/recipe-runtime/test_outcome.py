from __future__ import annotations

import os
import sys

import pytest

_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "..")
for path in (
    os.path.join(_PACKAGES_DIR, "recipe-schema"),
    os.path.join(_PACKAGES_DIR, "telemetry"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

from recipe import Recipe, RecipeStep  # noqa: E402
from runner import RecipeDAGRunner  # noqa: E402


def _recipe(outcome: str = "booking confirmed") -> Recipe:
    return Recipe(
        recipe_id="truth",
        intent_family="book_hotel",
        steps=[RecipeStep(step_id="book", action="book", capability_id="hotel.book")],
        success_conditions=[outcome],
    )


def test_provider_acknowledgement_is_not_promoted_to_confirmation():
    execution = RecipeDAGRunner().run(
        _recipe(),
        executor=lambda *_: {"status": "request_received", "request_id": "REQ-1"},
        trace_id="trace-1",
    )

    assert execution.success is True
    assert execution.outcome_claim == {
        "schema_version": "1.0",
        "requested_outcome": "booking confirmed",
        "achieved_state": "request_received",
        "verification_type": "provider_reported",
        "evidence_refs": ["trace-1"],
        "remaining_gap": "Requested outcome was not independently verified",
    }


@pytest.mark.parametrize("result", [{}, {"ok": True}])
def test_empty_provider_response_is_unknown(result):
    execution = RecipeDAGRunner().run(
        _recipe(), executor=lambda *_: result, trace_id="trace-empty"
    )

    assert execution.success is True
    assert execution.outcome_claim["verification_type"] == "unknown"
    assert execution.outcome_claim["achieved_state"] == "unknown"
    assert execution.outcome_claim["remaining_gap"] == "Provider returned no outcome evidence"


def test_failure_preserves_unknown_side_effect_state_and_disables_automatic_retry():
    execution = RecipeDAGRunner().run(
        _recipe(),
        executor=lambda *_: (_ for _ in ()).throw(TimeoutError("provider timeout")),
        trace_id="trace-2",
        raise_on_error=False,
    )

    assert execution.success is False
    assert execution["failed_stage"] == "book"
    assert execution["side_effect_state"] == "unknown"
    assert execution["retryable"] is None
    assert execution.outcome_claim["verification_type"] == "unknown"
    assert "side effects are unknown" in execution.outcome_claim["remaining_gap"]
