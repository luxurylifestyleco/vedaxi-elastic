"""Protocol-neutral outcome and evidence contracts.

These contracts are deliberately policy-facing primitives. They do not execute
providers, grant authority, or turn an internal event into external proof.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Iterable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]


class OutcomeStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DISPUTED = "DISPUTED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INSUFFICIENT = "INSUFFICIENT"
    PENDING = "PENDING"
    CONFLICTING = "CONFLICTING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: str = Field(default="1.0", min_length=1)


class Delegation(Contract):
    delegation_id: Text
    delegator_id: Text
    delegatee_id: Text
    parent_delegation_id: Text | None = None
    capabilities: list[Text] = Field(min_length=1)
    resource_scopes: list[Text] = Field(min_length=1)
    constraints: dict[str, JsonValue] = Field(default_factory=dict)
    further_delegation_allowed: bool = False
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    authorization_proof: Text

    @model_validator(mode="after")
    def valid_window(self) -> "Delegation":
        if self.expires_at <= self.issued_at:
            raise ValueError("Delegation expiry must follow issuance")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("Delegation revocation cannot precede issuance")
        return self


class OutcomeEnvelope(Contract):
    outcome_id: Text
    principal_id: Text
    originating_agent_id: Text
    delegated_authority_reference: Text | None = None
    intent: dict[str, JsonValue] = Field(min_length=1)
    desired_state: dict[str, JsonValue] = Field(min_length=1)
    constraints: dict[str, JsonValue] = Field(default_factory=dict)
    deadline: AwareDatetime | None = None
    required_capabilities: list[Text] = Field(default_factory=list)
    execution_plan_reference: Text | None = None
    approval_policy: dict[str, JsonValue] = Field(default_factory=dict)
    verification_policy: dict[str, JsonValue] = Field(default_factory=dict)
    completion_criteria: list[Text] = Field(min_length=1)
    evidence_collection_policy: dict[str, JsonValue] = Field(default_factory=dict)
    recovery_policy: dict[str, JsonValue] = Field(default_factory=dict)
    current_status: OutcomeStatus = OutcomeStatus.CREATED
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_timestamps(self) -> "OutcomeEnvelope":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class EvidenceRecord(Contract):
    evidence_id: Text
    tenant_id: Text
    outcome_id: Text
    execution_id: Text
    evidence_type: str = Field(pattern="^(execution_event|agent_claim|provider_receipt|attestation|verification_result)$")
    claim: Text
    subject: Text
    issuer: Text
    source: Text
    producer: Text
    issued_at: AwareDatetime | None = None
    occurred_at: AwareDatetime | None = None
    observed_at: AwareDatetime
    received_at: AwareDatetime
    artifact_reference: Text | None = None
    content_digest: Text | None = None
    signature_reference: Text | None = None
    protocol_origin: Text
    related_event_ids: list[Text] = Field(default_factory=list)
    related_evidence_ids: list[Text] = Field(default_factory=list)
    delegation_reference: Text | None = None
    verification_status: VerificationStatus = VerificationStatus.PENDING
    assurance_level: Text | None = None
    privacy_classification: Text
    retention_policy: Text


class VerificationResult(Contract):
    verification_id: Text
    outcome_id: Text
    execution_id: Text
    status: VerificationStatus
    checked: list[Text] = Field(min_length=1)
    policy_reference: Text
    evidence_ids: list[Text] = Field(min_length=1)
    passed_checks: list[Text] = Field(default_factory=list)
    failed_checks: list[Text] = Field(default_factory=list)
    verified_at: AwareDatetime
    verifier_id: Text
    reason: Text


VALID_TRANSITIONS: dict[OutcomeStatus, frozenset[OutcomeStatus]] = {
    OutcomeStatus.CREATED: frozenset({OutcomeStatus.VALIDATING, OutcomeStatus.CANCELLED, OutcomeStatus.EXPIRED}),
    OutcomeStatus.VALIDATING: frozenset({OutcomeStatus.AUTHORIZATION_REQUIRED, OutcomeStatus.AUTHORIZED, OutcomeStatus.FAILED, OutcomeStatus.CANCELLED}),
    OutcomeStatus.AUTHORIZATION_REQUIRED: frozenset({OutcomeStatus.AUTHORIZED, OutcomeStatus.CANCELLED, OutcomeStatus.EXPIRED}),
    OutcomeStatus.AUTHORIZED: frozenset({OutcomeStatus.PLANNING, OutcomeStatus.CANCELLED, OutcomeStatus.EXPIRED}),
    OutcomeStatus.PLANNING: frozenset({OutcomeStatus.EXECUTING, OutcomeStatus.FAILED, OutcomeStatus.CANCELLED}),
    OutcomeStatus.EXECUTING: frozenset({OutcomeStatus.PARTIALLY_COMPLETED, OutcomeStatus.VERIFYING, OutcomeStatus.RECOVERY_REQUIRED, OutcomeStatus.FAILED, OutcomeStatus.CANCELLED}),
    OutcomeStatus.PARTIALLY_COMPLETED: frozenset({OutcomeStatus.VERIFYING, OutcomeStatus.RECOVERY_REQUIRED, OutcomeStatus.FAILED, OutcomeStatus.CANCELLED}),
    OutcomeStatus.RECOVERY_REQUIRED: frozenset({OutcomeStatus.EXECUTING, OutcomeStatus.PARTIALLY_COMPLETED, OutcomeStatus.FAILED, OutcomeStatus.CANCELLED, OutcomeStatus.DISPUTED}),
    OutcomeStatus.VERIFYING: frozenset({OutcomeStatus.COMPLETED, OutcomeStatus.PARTIALLY_COMPLETED, OutcomeStatus.RECOVERY_REQUIRED, OutcomeStatus.FAILED, OutcomeStatus.DISPUTED}),
    OutcomeStatus.COMPLETED: frozenset(),
    OutcomeStatus.FAILED: frozenset(),
    OutcomeStatus.CANCELLED: frozenset(),
    OutcomeStatus.EXPIRED: frozenset(),
    OutcomeStatus.DISPUTED: frozenset({OutcomeStatus.VERIFYING, OutcomeStatus.RECOVERY_REQUIRED, OutcomeStatus.FAILED}),
}


def transition_outcome(outcome: OutcomeEnvelope, new_status: OutcomeStatus, *, sufficient_evidence: bool = False) -> OutcomeEnvelope:
    """Return a new envelope only when the lifecycle transition is valid."""
    current = outcome.current_status
    if new_status not in VALID_TRANSITIONS[current]:
        raise ValueError(f"Invalid outcome transition: {current.value} -> {new_status.value}")
    if new_status is OutcomeStatus.COMPLETED and not sufficient_evidence:
        raise ValueError("Outcome cannot be completed without sufficient evidence")
    return outcome.model_copy(update={"current_status": new_status, "updated_at": datetime.now(outcome.updated_at.tzinfo)})


class EvidenceLedger:
    """Small append-only reference implementation for contract tests.

    Production persistence belongs to the existing database/event boundary.
    """

    def __init__(self) -> None:
        self._records: dict[str, EvidenceRecord] = {}

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        if record.evidence_id in self._records:
            raise ValueError(f"Evidence ID already exists: {record.evidence_id}")
        self._records[record.evidence_id] = record
        return record

    def correct(self, previous_evidence_id: str, replacement: EvidenceRecord) -> EvidenceRecord:
        if previous_evidence_id not in self._records:
            raise KeyError(previous_evidence_id)
        if previous_evidence_id not in replacement.related_evidence_ids:
            raise ValueError("Correction must reference the previous evidence record")
        return self.append(replacement)

    def get(self, evidence_id: str) -> EvidenceRecord:
        return self._records[evidence_id]

    def all(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records.values())
