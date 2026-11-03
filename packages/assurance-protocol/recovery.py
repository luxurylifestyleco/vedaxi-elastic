"""Pure recovery and idempotency contracts.

This module models decisions around an operation whose provider state may be
unknown.  It does not execute, retry, cancel, reconcile, or persist anything.
Callers must supply the facts used by the deterministic decision functions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class RecoveryState(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    HUMAN_ESCALATION_REQUIRED = "HUMAN_ESCALATION_REQUIRED"


class RecoveryDecision(str, Enum):
    RETRY_SAFE = "RETRY_SAFE"
    RECONCILE_FIRST = "RECONCILE_FIRST"
    DO_NOT_RETRY = "DO_NOT_RETRY"
    CANCELLED = "CANCELLED"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"


class EventDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICTING = "CONFLICTING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class RecoveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class OperationIdentity(RecoveryContract):
    tenant_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    request_digest: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)


class RetryPolicy(RecoveryContract):
    max_attempts: int = Field(default=1, ge=1)
    retryable_failures: frozenset[str] = frozenset()
    irreversible: bool = False
    reconciliation_required_after_uncertain: bool = True

    def decision(
        self,
        operation: OperationIdentity,
        *,
        failure: str,
        provider_state_known: bool = True,
        reconciliation_complete: bool = False,
        compensation_available: bool = False,
    ) -> RecoveryDecision:
        """Choose the next safe action without performing it.

        Unknown provider state always wins over retryability.  An irreversible
        operation can never be retried blindly, even if a failure is listed as
        retryable.
        """
        if not provider_state_known:
            if reconciliation_complete:
                return self._known_state_decision(operation, failure)
            return (
                RecoveryDecision.RECONCILE_FIRST
                if self.reconciliation_required_after_uncertain
                else RecoveryDecision.DO_NOT_RETRY
            )
        if self.irreversible and not compensation_available and failure in self.retryable_failures:
            return RecoveryDecision.DO_NOT_RETRY
        return self._known_state_decision(operation, failure)

    def _known_state_decision(self, operation: OperationIdentity, failure: str) -> RecoveryDecision:
        if failure not in self.retryable_failures:
            return RecoveryDecision.DO_NOT_RETRY
        if operation.attempt >= self.max_attempts:
            return RecoveryDecision.DO_NOT_RETRY
        return RecoveryDecision.RETRY_SAFE


class RecoveryEvent(RecoveryContract):
    event_id: str = Field(min_length=1)
    operation: OperationIdentity
    state: RecoveryState
    content_digest: str = Field(min_length=1)
    occurred_at: AwareDatetime
    provider_dispatched: bool = False


class ReconciliationObservation(RecoveryContract):
    """Facts supplied by an external reconciler; this model performs no lookup."""

    operation: OperationIdentity
    provider_state: RecoveryState | None = None
    provider_operation_id: str | None = Field(default=None, min_length=1)
    source: str = Field(min_length=1)
    observation_digest: str = Field(min_length=1)
    observed_at: AwareDatetime
    evidence_conflict: bool = False


class ReconciliationResult(RecoveryContract):
    """Deterministic reconciliation output, suitable for a durable boundary."""

    operation_key: str = Field(min_length=1)
    decision: RecoveryDecision
    resulting_state: RecoveryState
    provider_state: RecoveryState | None = None
    provider_operation_id: str | None = Field(default=None, min_length=1)
    source: str = Field(min_length=1)
    observation_digest: str = Field(min_length=1)
    authoritative: bool = False
    reason: str = Field(min_length=1)


class EventLedger(RecoveryContract):
    """In-memory event identity rules; no external side effects."""

    events: tuple[RecoveryEvent, ...] = ()

    def record(self, event: RecoveryEvent) -> tuple["EventLedger", EventDisposition]:
        existing = next((item for item in self.events if item.event_id == event.event_id), None)
        if existing is not None:
            if existing.content_digest == event.content_digest:
                return self, EventDisposition.DUPLICATE
            return self, EventDisposition.CONFLICTING
        if self._late_terminal_conflict(event):
            return self, EventDisposition.RECOVERY_REQUIRED
        return self.model_copy(update={"events": self.events + (event,)}), EventDisposition.ACCEPTED

    def _late_terminal_conflict(self, event: RecoveryEvent) -> bool:
        prior = [item for item in self.events if item.operation.operation_key == event.operation.operation_key]
        if not prior:
            return False
        terminal = {RecoveryState.SUCCEEDED, RecoveryState.CANCELLED}
        return any(item.state in terminal for item in prior) and event.state not in terminal


def cancellation_decision(*, state: RecoveryState, provider_dispatched: bool) -> RecoveryState:
    """Return the truthful cancellation state; dispatch makes cancellation uncertain."""
    if state in {RecoveryState.SUCCEEDED, RecoveryState.FAILED, RecoveryState.CANCELLED}:
        return state
    return RecoveryState.CANCEL_REQUESTED if provider_dispatched else RecoveryState.CANCELLED


def reconciliation_decision(
    *,
    state: RecoveryState,
    provider_state: RecoveryState | None,
    evidence_conflict: bool = False,
) -> RecoveryDecision:
    """Resolve an uncertain operation from independently supplied state facts."""
    if evidence_conflict:
        return RecoveryDecision.ESCALATE_HUMAN
    if state is not RecoveryState.UNCERTAIN and state is not RecoveryState.RECOVERY_REQUIRED:
        return RecoveryDecision.DO_NOT_RETRY
    if provider_state is None:
        return RecoveryDecision.ESCALATE_HUMAN
    if provider_state is RecoveryState.SUCCEEDED:
        return RecoveryDecision.DO_NOT_RETRY
    if provider_state is RecoveryState.FAILED:
        return RecoveryDecision.RETRY_SAFE
    return RecoveryDecision.ESCALATE_HUMAN


def reconcile_observation(
    observation: ReconciliationObservation,
    *,
    current_state: RecoveryState = RecoveryState.UNCERTAIN,
) -> ReconciliationResult:
    """Convert supplied reconciliation facts into an idempotent boundary result.

    This function deliberately does not fetch provider state, retry, cancel, or
    persist anything.  Missing state and conflicting evidence remain human-
    escalation outcomes rather than being interpreted as success or permission
    to retry.
    """
    decision = reconciliation_decision(
        state=current_state,
        provider_state=observation.provider_state,
        evidence_conflict=observation.evidence_conflict,
    )
    if observation.evidence_conflict:
        resulting_state = RecoveryState.HUMAN_ESCALATION_REQUIRED
        reason = "conflicting reconciliation evidence"
    elif observation.provider_state is None:
        resulting_state = RecoveryState.HUMAN_ESCALATION_REQUIRED
        reason = "provider state is unknown"
    elif observation.provider_state is RecoveryState.SUCCEEDED:
        resulting_state = RecoveryState.SUCCEEDED
        reason = "provider reported terminal success"
    elif observation.provider_state is RecoveryState.FAILED:
        resulting_state = RecoveryState.FAILED
        reason = "provider reported terminal failure"
    else:
        resulting_state = RecoveryState.HUMAN_ESCALATION_REQUIRED
        reason = "provider state is non-terminal"
    return ReconciliationResult(
        operation_key=observation.operation.operation_key,
        decision=decision,
        resulting_state=resulting_state,
        provider_state=observation.provider_state,
        provider_operation_id=observation.provider_operation_id,
        source=observation.source,
        observation_digest=observation.observation_digest,
        authoritative=observation.provider_state in {RecoveryState.SUCCEEDED, RecoveryState.FAILED}
        and not observation.evidence_conflict,
        reason=reason,
    )

