"""Versioned assurance interchange contracts, not runtime enforcement or attestations.

Envelopes bind existing intent/capability/step IDs without changing their schemas.
A valid document is a claim: consumers must authenticate issuers, enforce grants,
verify evidence, and atomically persist checkpoints themselves.
"""
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Digest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    schema_version: Literal['1.0'] = '1.0'


class AcceptanceTest(Contract):
    test_id: Text
    evaluator: Text
    # JSON Pointer into the end-state document; the evaluator defines semantics.
    target: Annotated[str, StringConstraints(pattern=r'^(|/.*)$')]
    expected: JsonValue


class Budget(Contract):
    max_cost: float | None = Field(default=None, ge=0)
    currency: Annotated[str, StringConstraints(pattern=r'^[A-Z]{3}$')] | None = None
    max_duration_ms: int = Field(strict=True, gt=0)
    max_tool_calls: int = Field(strict=True, ge=0)


class ApprovalPolicy(Contract):
    mode: Literal['each_action', 'bounded_grant']
    approver: Text
    # These are policy requirements, never evidence that approval occurred.
    required_for: list[Literal['external_write', 'disclosure', 'payment', 'privilege_change']] = Field(min_length=1)


class AssuranceIntent(Contract):
    intent_id: Text
    goal: Text
    desired_end_state: dict[str, JsonValue] = Field(min_length=1)
    constraints: dict[str, JsonValue] = Field(default_factory=dict)
    budget: Budget
    max_risk: Literal['low', 'medium', 'high']
    approval_policy: ApprovalPolicy
    acceptance_tests: list[AcceptanceTest] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_tests(self):
        ids = [test.test_id for test in self.acceptance_tests]
        if len(ids) != len(set(ids)):
            raise ValueError('Acceptance test IDs must be unique')
        return self


class CapabilityTrustClaim(Contract):
    capability_id: Text
    capability_version: Text
    publisher: Text
    issuer: Text
    claim: Text
    # No intrinsic trusted/verified boolean: verification is consumer policy.
    evidence_refs: list[Text] = Field(min_length=1)
    subject_sha256: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    signature_ref: Text

    @model_validator(mode='after')
    def ordered_validity(self):
        if self.expires_at <= self.issued_at:
            raise ValueError('Claim expiry must follow issuance')
        return self


class PermissionGrant(Contract):
    grant_id: Text
    intent_id: Text
    principal: Text
    issuer: Text
    capability_id: Text
    capability_version: Text
    action: Text
    resource: Text
    input_sha256: Digest
    budget: Budget
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    approval_receipt_ref: Text
    signature_ref: Text

    @model_validator(mode='after')
    def ordered_validity(self):
        if self.expires_at <= self.issued_at:
            raise ValueError('Grant expiry must follow issuance')
        return self


class PermissionReceipt(Contract):
    receipt_id: Text
    grant_id: Text
    intent_id: Text
    step_id: Text
    request_sha256: Digest
    decision: Literal['allow', 'deny']
    reason: Text
    policy_version: Text
    evaluator: Text
    evaluated_at: AwareDatetime
    evidence_refs: list[Text] = Field(min_length=1)
    signature_ref: Text


class StepCheckpoint(Contract):
    execution_id: Text
    intent_id: Text
    step_id: Text
    capability_id: Text
    capability_version: Text
    idempotency_key: Text
    input_sha256: Digest
    state: Literal['prepared', 'started', 'completed', 'failed', 'indeterminate']
    attempt: int = Field(strict=True, ge=1)
    recorded_at: AwareDatetime
    permission_receipt_ref: Text
    prior_checkpoint_sha256: Digest | None = None
    output_sha256: Digest | None = None
    evidence_receipt_ref: Text | None = None

    @model_validator(mode='after')
    def completed_has_evidence(self):
        if self.state == 'completed' and (self.output_sha256 is None or self.evidence_receipt_ref is None):
            raise ValueError('Completed checkpoints require output digest and evidence receipt')
        return self


class AcceptanceResult(Contract):
    test_id: Text
    status: Literal['pass', 'fail', 'unknown']
    evaluator: Text
    evidence_refs: list[Text] = Field(min_length=1)


class EvidenceReceipt(Contract):
    receipt_id: Text
    intent_id: Text
    execution_id: Text
    step_id: Text
    input_sha256: Digest
    output_sha256: Digest
    checkpoint_sha256: Digest
    issuer: Text
    recorded_at: AwareDatetime
    status: Literal['pass', 'fail', 'unknown']
    acceptance_results: list[AcceptanceResult] = Field(min_length=1)
    source_refs: list[Text] = Field(min_length=1)
    signature_ref: Text | None = None
    verification_scope: Literal['internal', 'provider_receipt', 'independent'] = 'internal'

    @model_validator(mode='after')
    def consistent_results(self):
        ids = [item.test_id for item in self.acceptance_results]
        if len(ids) != len(set(ids)):
            raise ValueError('Acceptance result IDs must be unique')
        statuses = {item.status for item in self.acceptance_results}
        aggregate = 'fail' if 'fail' in statuses else 'unknown' if 'unknown' in statuses else 'pass'
        if self.status != aggregate:
            raise ValueError('Receipt status must aggregate its acceptance results')
        return self


class AssuranceDocument(Contract):
    """Schema-generation envelope: one explicitly named contract per document."""
    document: AssuranceIntent | CapabilityTrustClaim | PermissionGrant | PermissionReceipt | StepCheckpoint | EvidenceReceipt