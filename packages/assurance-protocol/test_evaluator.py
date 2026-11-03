from datetime import datetime, timezone

import pytest

try:
    from .evaluator import evaluate_outcome
    from .outcome import OutcomeEnvelope, OutcomeStatus, VerificationResult, VerificationStatus
except ImportError:  # pragma: no cover
    from evaluator import evaluate_outcome
    from outcome import OutcomeEnvelope, OutcomeStatus, VerificationResult, VerificationStatus


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_outcome(*, recovery_policy=None):
    return OutcomeEnvelope(
        outcome_id="outcome-1",
        principal_id="principal-1",
        originating_agent_id="agent-1",
        intent={"action": "test"},
        desired_state={"state": "done"},
        completion_criteria=["criterion-a", "criterion-b"],
        recovery_policy=recovery_policy or {},
        created_at=NOW,
        updated_at=NOW,
    )


def result(status, checked, *, outcome_id="outcome-1"):
    return VerificationResult(
        verification_id=f"verification-{status.value.lower()}-{checked[0]}",
        outcome_id=outcome_id,
        execution_id="execution-1",
        status=status,
        checked=checked,
        policy_reference="policy-1",
        evidence_ids=["evidence-1"],
        verified_at=NOW,
        verifier_id="verifier-1",
        reason="test result",
    )


def test_completes_only_when_every_criterion_is_verified():
    outcome = make_outcome()
    results = [
        result(VerificationStatus.VERIFIED, ["criterion-a"]),
        result(VerificationStatus.VERIFIED, ["criterion-b"]),
    ]
    assert evaluate_outcome(outcome, results) is OutcomeStatus.COMPLETED


def test_missing_criterion_is_partial_even_with_tool_like_success_absent_from_contract():
    outcome = make_outcome()
    assert evaluate_outcome(outcome, [result(VerificationStatus.VERIFIED, ["criterion-a"])]) is OutcomeStatus.PARTIALLY_COMPLETED


@pytest.mark.parametrize("status", [VerificationStatus.INSUFFICIENT, VerificationStatus.PENDING])
def test_recoverable_non_terminal_evidence_requires_explicit_recovery_policy(status):
    outcome = make_outcome(recovery_policy={"allow_recovery": True})
    assert evaluate_outcome(outcome, [result(status, ["criterion-a"])]) is OutcomeStatus.RECOVERY_REQUIRED


def test_terminal_failure_fails_without_recovery_permission():
    assert evaluate_outcome(make_outcome(), [result(VerificationStatus.FAILED, ["criterion-a"])]) is OutcomeStatus.FAILED


def test_terminal_failure_can_route_to_recovery_when_policy_permits():
    outcome = make_outcome(recovery_policy={"recovery_permitted": True})
    assert evaluate_outcome(outcome, [result(VerificationStatus.FAILED, ["criterion-a"])]) is OutcomeStatus.RECOVERY_REQUIRED


def test_conflicting_evidence_is_disputed():
    outcome = make_outcome()
    results = [result(VerificationStatus.CONFLICTING, ["criterion-a"])]
    assert evaluate_outcome(outcome, results) is OutcomeStatus.DISPUTED


def test_disagreement_for_one_criterion_is_disputed():
    outcome = make_outcome()
    results = [
        result(VerificationStatus.VERIFIED, ["criterion-a"]),
        result(VerificationStatus.PENDING, ["criterion-a"]),
    ]
    assert evaluate_outcome(outcome, results) is OutcomeStatus.DISPUTED


def test_wrong_outcome_cannot_complete():
    outcome = make_outcome()
    assert evaluate_outcome(outcome, [result(VerificationStatus.VERIFIED, ["criterion-a"], outcome_id="other")]) is OutcomeStatus.FAILED


def test_empty_results_are_conservative():
    assert evaluate_outcome(make_outcome(), []) is OutcomeStatus.PARTIALLY_COMPLETED
    assert evaluate_outcome(make_outcome(recovery_policy={"allow_recovery": True}), []) is OutcomeStatus.RECOVERY_REQUIRED
