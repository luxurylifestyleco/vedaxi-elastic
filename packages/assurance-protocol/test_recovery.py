from datetime import datetime, timezone

import pytest

try:
    from .recovery import (
        EventDisposition,
        EventLedger,
        OperationIdentity,
        RecoveryDecision,
        RecoveryEvent,
        ReconciliationObservation,
        RecoveryState,
        RetryPolicy,
        cancellation_decision,
        reconcile_observation,
        reconciliation_decision,
    )
except ImportError:  # pragma: no cover
    from recovery import (
        EventDisposition,
        EventLedger,
        OperationIdentity,
        RecoveryDecision,
        RecoveryEvent,
        ReconciliationObservation,
        RecoveryState,
        RetryPolicy,
        cancellation_decision,
        reconcile_observation,
        reconciliation_decision,
    )


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def operation(*, attempt=1, key="op-1"):
    return OperationIdentity(
        tenant_id="tenant-1", outcome_id="outcome-1", execution_id="execution-1",
        step_id="step-1", request_digest="sha256:request", operation_key=key, attempt=attempt,
    )


def event(event_id="event-1", *, state=RecoveryState.RUNNING, digest="sha256:event", key="op-1", dispatched=False):
    return RecoveryEvent(
        event_id=event_id, operation=operation(key=key), state=state,
        content_digest=digest, occurred_at=NOW, provider_dispatched=dispatched,
    )


def test_retry_is_bounded_and_known_transient_failure_is_safe():
    policy = RetryPolicy(max_attempts=3, retryable_failures=frozenset({"timeout"}))
    assert policy.decision(operation(attempt=1), failure="timeout") is RecoveryDecision.RETRY_SAFE
    assert policy.decision(operation(attempt=3), failure="timeout") is RecoveryDecision.DO_NOT_RETRY


def test_uncertain_irreversible_operation_requires_reconciliation():
    policy = RetryPolicy(max_attempts=3, retryable_failures=frozenset({"timeout"}), irreversible=True)
    assert policy.decision(operation(), failure="timeout", provider_state_known=False) is RecoveryDecision.RECONCILE_FIRST
    assert policy.decision(operation(), failure="timeout", provider_state_known=False, reconciliation_complete=True) is RecoveryDecision.RETRY_SAFE


def test_non_retryable_and_irreversible_failures_do_not_retry():
    policy = RetryPolicy(max_attempts=3, retryable_failures=frozenset({"timeout"}), irreversible=True)
    assert policy.decision(operation(), failure="rejected") is RecoveryDecision.DO_NOT_RETRY
    assert policy.decision(operation(), failure="timeout", compensation_available=False) is RecoveryDecision.DO_NOT_RETRY


def test_same_event_id_and_digest_is_duplicate_noop():
    ledger, disposition = EventLedger().record(event())
    same, duplicate = ledger.record(event())
    assert disposition is EventDisposition.ACCEPTED
    assert duplicate is EventDisposition.DUPLICATE
    assert same == ledger


def test_same_event_id_with_new_content_is_conflict():
    ledger, _ = EventLedger().record(event())
    unchanged, disposition = ledger.record(event(digest="sha256:other"))
    assert disposition is EventDisposition.CONFLICTING
    assert unchanged == ledger


def test_late_event_after_terminal_state_requires_recovery():
    ledger, _ = EventLedger().record(event(state=RecoveryState.SUCCEEDED))
    _, disposition = ledger.record(event(event_id="event-2", state=RecoveryState.FAILED))
    assert disposition is EventDisposition.RECOVERY_REQUIRED


def test_cancellation_before_and_after_dispatch_are_distinct():
    assert cancellation_decision(state=RecoveryState.RUNNING, provider_dispatched=False) is RecoveryState.CANCELLED
    assert cancellation_decision(state=RecoveryState.RUNNING, provider_dispatched=True) is RecoveryState.CANCEL_REQUESTED


def test_reconciliation_never_retries_without_provider_state():
    assert reconciliation_decision(state=RecoveryState.UNCERTAIN, provider_state=None) is RecoveryDecision.ESCALATE_HUMAN
    assert reconciliation_decision(state=RecoveryState.UNCERTAIN, provider_state=RecoveryState.SUCCEEDED) is RecoveryDecision.DO_NOT_RETRY
    assert reconciliation_decision(state=RecoveryState.UNCERTAIN, provider_state=RecoveryState.FAILED) is RecoveryDecision.RETRY_SAFE


def test_conflicting_reconciliation_escalates():
    assert reconciliation_decision(
        state=RecoveryState.RECOVERY_REQUIRED,
        provider_state=RecoveryState.SUCCEEDED,
        evidence_conflict=True,
    ) is RecoveryDecision.ESCALATE_HUMAN


def observation(*, provider_state=None, conflict=False):
    return ReconciliationObservation(
        operation=operation(), provider_state=provider_state,
        provider_operation_id="provider-op-1", source="provider-status",
        observation_digest="sha256:observation", observed_at=NOW,
        evidence_conflict=conflict,
    )


def test_reconciliation_result_is_fail_closed_when_provider_state_is_unknown():
    result = reconcile_observation(observation())
    assert result.decision is RecoveryDecision.ESCALATE_HUMAN
    assert result.resulting_state is RecoveryState.HUMAN_ESCALATION_REQUIRED
    assert result.authoritative is False


def test_reconciliation_result_preserves_terminal_provider_state_without_retrying():
    result = reconcile_observation(observation(provider_state=RecoveryState.SUCCEEDED))
    assert result.decision is RecoveryDecision.DO_NOT_RETRY
    assert result.resulting_state is RecoveryState.SUCCEEDED
    assert result.authoritative is True


def test_reconciliation_result_exposes_retry_decision_without_executing_it():
    result = reconcile_observation(observation(provider_state=RecoveryState.FAILED))
    assert result.decision is RecoveryDecision.RETRY_SAFE
    assert result.resulting_state is RecoveryState.FAILED
    assert result.authoritative is True


def test_conflicting_observation_never_becomes_authoritative():
    result = reconcile_observation(observation(provider_state=RecoveryState.SUCCEEDED, conflict=True))
    assert result.decision is RecoveryDecision.ESCALATE_HUMAN
    assert result.resulting_state is RecoveryState.HUMAN_ESCALATION_REQUIRED
    assert result.authoritative is False


def test_models_reject_invalid_attempt_and_unknown_fields():
    with pytest.raises(ValueError):
        operation(attempt=0)
    with pytest.raises(ValueError):
        OperationIdentity(**operation().model_dump(), unexpected="x")

