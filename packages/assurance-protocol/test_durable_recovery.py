from datetime import datetime, timezone

import pytest

try:
    from .durable_recovery import (
        ObservationDisposition,
        OperationIdentityConflict,
        OperationReconciliationLedger,
        ReceiptCorrelationError,
        UnknownOperation,
    )
    from .provider import FakeProvider, ProviderExecutionRequest
    from .recovery import OperationIdentity, RecoveryState, ReconciliationObservation
except ImportError:  # pragma: no cover
    from durable_recovery import (
        ObservationDisposition,
        OperationIdentityConflict,
        OperationReconciliationLedger,
        ReceiptCorrelationError,
        UnknownOperation,
    )
    from provider import FakeProvider, ProviderExecutionRequest
    from recovery import OperationIdentity, RecoveryState, ReconciliationObservation


NOW = datetime.now(timezone.utc)


def identity(*, attempt: int = 1) -> OperationIdentity:
    return OperationIdentity(
        tenant_id="tenant-a",
        outcome_id="outcome-1",
        execution_id="execution-1",
        step_id="step-1",
        request_digest="request-digest",
        operation_key="operation-1",
        attempt=attempt,
    )


def request() -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        operation=identity(),
        provider_id="fake-provider",
        protocol="test",
        capability_id="capability-1",
        input_digest="input-digest",
    )


def test_register_is_idempotent_but_rejects_identity_reuse() -> None:
    ledger = OperationReconciliationLedger()
    first = ledger.register(identity())
    assert ledger.register(identity()) == first
    with pytest.raises(OperationIdentityConflict):
        ledger.register(identity(attempt=2))


def test_observation_requires_registered_operation() -> None:
    ledger = OperationReconciliationLedger()
    provider = FakeProvider()
    receipt = provider.execute(request())
    with pytest.raises(UnknownOperation):
        ledger.observe_receipt(
            request(), receipt, expected_issuer_id="fake-provider", observed_at=NOW
        )


def test_receipt_reconciliation_is_replayable_without_duplicate_append() -> None:
    ledger = OperationReconciliationLedger()
    ledger.register(identity())
    provider = FakeProvider()
    operation_request = request()
    receipt = provider.execute(operation_request)
    record, result, disposition = ledger.observe_receipt(
        operation_request,
        receipt,
        expected_issuer_id="fake-provider",
        observed_at=NOW,
    )
    replay, replay_result, replay_disposition = ledger.observe_receipt(
        operation_request,
        receipt,
        expected_issuer_id="fake-provider",
        observed_at=NOW,
    )
    assert disposition is ObservationDisposition.ACCEPTED
    assert result.resulting_state is RecoveryState.SUCCEEDED
    assert len(record.observations) == 1
    assert replay == record
    assert replay_result == result
    assert replay_disposition is ObservationDisposition.DUPLICATE


def test_conflicting_terminal_observation_escalates() -> None:
    ledger = OperationReconciliationLedger()
    operation_identity = identity()
    ledger.register(operation_identity)
    success = ledger.observe(
        ReconciliationObservation(
            operation=operation_identity,
            provider_state=RecoveryState.SUCCEEDED,
            provider_operation_id="provider:operation-1",
            source="provider-a",
            observation_digest="digest-success",
            observed_at=NOW,
        )
    )
    record, result, disposition = ledger.observe(
        success[0].observations[0].model_copy(
            update={
                "provider_state": RecoveryState.FAILED,
                "source": "provider-b",
                "observation_digest": "digest-failure",
            }
        )
    )
    assert disposition is ObservationDisposition.CONFLICTING
    assert result.resulting_state is RecoveryState.HUMAN_ESCALATION_REQUIRED
    assert record.state is RecoveryState.HUMAN_ESCALATION_REQUIRED


def test_invalid_receipt_cannot_enter_ledger() -> None:
    ledger = OperationReconciliationLedger()
    operation_request = request()
    ledger.register(operation_request.operation)
    receipt = FakeProvider().execute(operation_request).model_copy(
        update={"issuer_id": "untrusted-issuer"}
    )
    with pytest.raises(ReceiptCorrelationError):
        ledger.observe_receipt(
            operation_request,
            receipt,
            expected_issuer_id="fake-provider",
            observed_at=NOW,
        )
