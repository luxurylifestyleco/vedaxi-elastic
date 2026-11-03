"""Durable-shaped provider operation identity and reconciliation boundary.

This module is intentionally in-memory.  It preserves immutable operation
identity, receipt/observation history, duplicate handling, and conflict
escalation so a durable adapter can later replace the storage implementation
without changing the decision contract.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

try:
    from .provider import (
        ProviderExecutionRequest,
        ProviderOperationState,
        ProviderReceipt,
        verify_provider_receipt,
        ReceiptVerificationStatus,
    )
    from .recovery import (
        OperationIdentity,
        ReconciliationObservation,
        ReconciliationResult,
        RecoveryState,
        reconcile_observation,
    )
except ImportError:  # pragma: no cover
    from provider import (
        ProviderExecutionRequest,
        ProviderOperationState,
        ProviderReceipt,
        verify_provider_receipt,
        ReceiptVerificationStatus,
    )
    from recovery import (
        OperationIdentity,
        ReconciliationObservation,
        ReconciliationResult,
        RecoveryState,
        reconcile_observation,
    )


class ObservationDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICTING = "CONFLICTING"


class OperationIdentityConflict(Exception):
    """The operation key was reused for a different immutable identity."""


class UnknownOperation(Exception):
    """An observation arrived before its operation was registered."""


class ReceiptCorrelationError(Exception):
    """A receipt cannot be attached to the registered operation."""


class DurableOperationRecord(BaseModel):
    """Snapshot of one operation and its append-only reconciliation facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: OperationIdentity
    state: RecoveryState = RecoveryState.READY
    provider_operation_id: str | None = Field(default=None, min_length=1)
    observations: tuple[ReconciliationObservation, ...] = ()
    results: tuple[ReconciliationResult, ...] = ()


class OperationReconciliationLedger:
    """Bounded local ledger for identity-safe reconciliation.

    It has no database, network, retry, or provider side effects.  The word
    durable refers to the immutable snapshot/event shape, not persistence.
    """

    def __init__(self) -> None:
        self._records: dict[str, DurableOperationRecord] = {}

    def register(self, identity: OperationIdentity) -> DurableOperationRecord:
        existing = self._records.get(identity.operation_key)
        if existing is not None:
            if existing.identity != identity:
                raise OperationIdentityConflict(
                    f"operation key reused with different identity: {identity.operation_key}"
                )
            return existing
        record = DurableOperationRecord(identity=identity)
        self._records[identity.operation_key] = record
        return record

    def get(self, operation_key: str) -> DurableOperationRecord | None:
        return self._records.get(operation_key)

    def observe(
        self, observation: ReconciliationObservation
    ) -> tuple[DurableOperationRecord, ReconciliationResult, ObservationDisposition]:
        record = self._records.get(observation.operation.operation_key)
        if record is None:
            raise UnknownOperation(observation.operation.operation_key)
        if record.identity != observation.operation:
            raise OperationIdentityConflict(
                f"observation identity mismatch: {observation.operation.operation_key}"
            )
        duplicate = next(
            (index for index, item in enumerate(record.observations)
             if item.observation_digest == observation.observation_digest),
            None,
        )
        if duplicate is not None:
            return record, record.results[duplicate], ObservationDisposition.DUPLICATE

        conflict = any(
            item.provider_state in {RecoveryState.SUCCEEDED, RecoveryState.FAILED}
            and observation.provider_state in {RecoveryState.SUCCEEDED, RecoveryState.FAILED}
            and item.provider_state != observation.provider_state
            for item in record.observations
        )
        result = reconcile_observation(
            observation,
            current_state=record.state,
        )
        if conflict:
            result = reconcile_observation(
                observation.model_copy(update={"evidence_conflict": True}),
                current_state=record.state,
            )
        next_record = record.model_copy(
            update={
                "state": result.resulting_state,
                "provider_operation_id": observation.provider_operation_id
                or record.provider_operation_id,
                "observations": record.observations + (observation,),
                "results": record.results + (result,),
            }
        )
        self._records[observation.operation.operation_key] = next_record
        disposition = (
            ObservationDisposition.CONFLICTING if conflict else ObservationDisposition.ACCEPTED
        )
        return next_record, result, disposition

    def observe_receipt(
        self,
        request: ProviderExecutionRequest,
        receipt: ProviderReceipt,
        *,
        expected_issuer_id: str,
        observed_at,
    ) -> tuple[DurableOperationRecord, ReconciliationResult, ObservationDisposition]:
        """Attach a locally correlated receipt; no signature trust is implied."""
        verification = verify_provider_receipt(
            request, receipt, expected_issuer_id=expected_issuer_id
        )
        if verification.status is not ReceiptVerificationStatus.VERIFIED:
            raise ReceiptCorrelationError("; ".join(verification.reasons))
        state = {
            ProviderOperationState.SUCCEEDED: RecoveryState.SUCCEEDED,
            ProviderOperationState.FAILED: RecoveryState.FAILED,
            ProviderOperationState.UNKNOWN: RecoveryState.UNCERTAIN,
            ProviderOperationState.DUPLICATE: RecoveryState.UNCERTAIN,
            ProviderOperationState.CONFLICTING: RecoveryState.UNCERTAIN,
        }[receipt.state]
        observation = ReconciliationObservation(
            operation=request.operation,
            provider_state=state,
            provider_operation_id=receipt.provider_operation_id,
            source=f"provider-receipt:{receipt.provider_id}",
            observation_digest=receipt.receipt_digest,
            observed_at=observed_at,
        )
        return self.observe(observation)
