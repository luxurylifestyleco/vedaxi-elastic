from datetime import datetime, timezone

import pytest

from outcome import EvidenceRecord, VerificationStatus
from execution_context import AuthKind, ExecutionContext, PrincipalKind
from verification import (
    AdapterCheck,
    AdapterCheckStatus,
    NormalizedClaim,
    VerificationContext,
    VerificationEngine,
)


NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


def evidence(evidence_id: str, *, claim: str = "records exist", subject: str = "records", status=VerificationStatus.PENDING, related_events=None):
    return EvidenceRecord(
        evidence_id=evidence_id,
        tenant_id="tenant-1",
        outcome_id="o1",
        execution_id="x1",
        evidence_type="provider_receipt",
        claim=claim,
        subject=subject,
        issuer="provider",
        source="provider-db",
        producer="provider",
        observed_at=NOW,
        received_at=NOW,
        protocol_origin="rest",
        related_event_ids=related_events or [],
        verification_status=status,
        privacy_classification="tenant-private",
        retention_policy="default",
    )


def context(**kwargs):
    return VerificationContext(
        outcome_id="o1",
        execution_id="x1",
        policy_reference="policy-v1",
        verifier_id="verifier-1",
        verified_at=NOW,
        **kwargs,
    )


def execution_context(**kwargs):
    return ExecutionContext(
        tenant_id="tenant-1",
        principal_id="principal-1",
        principal_kind=PrincipalKind.HUMAN,
        auth_kind=AuthKind.DELEGATED,
        organization_id="tenant-1",
        policy_epoch=1,
        scopes=("records:read",),
        issued_at=NOW,
        expires_at=NOW.replace(year=2027),
        authorization_decision_id="decision-1",
        **kwargs,
    )


class ProviderAdapter:
    adapter_id = "provider-receipt-v1"

    def supports(self, record):
        return record.evidence_type == "provider_receipt"

    def check(self, record, _context):
        return AdapterCheck(adapter_id=self.adapter_id, evidence_id=record.evidence_id, status=AdapterCheckStatus.PASS, reason="provider receipt shape accepted")


def engine():
    return VerificationEngine([ProviderAdapter()])


def test_all_checks_pass_verifies():
    result = engine().verify([evidence("e1")], context(), verification_id="v1")
    assert result.status is VerificationStatus.VERIFIED
    assert result.evidence_ids == ["e1"]


def test_missing_adapter_is_insufficient_not_verified():
    result = VerificationEngine().verify([evidence("e1")], context())
    assert result.status is VerificationStatus.INSUFFICIENT


def test_correlation_rejects_mismatched_outcome_and_unknown_references():
    record = evidence("e1")
    mismatched = record.model_copy(update={"outcome_id": "other"})
    result = engine().verify([mismatched], context())
    assert result.status is VerificationStatus.FAILED
    assert "mismatched outcome_id" in result.failed_checks[0]

    referenced = record.model_copy(update={"related_evidence_ids": ["missing"]})
    result = engine().verify([referenced], context())
    assert result.status is VerificationStatus.FAILED
    assert any("unknown evidence" in item for item in result.failed_checks)


def test_context_free_verification_preserves_existing_behavior():
    result = engine().verify([evidence("e1")], context())
    assert result.status is VerificationStatus.VERIFIED


def test_execution_context_rejects_mismatched_evidence_tenant():
    result = engine().verify(
        [evidence("e1").model_copy(update={"tenant_id": "tenant-2"})],
        context(execution_context=execution_context()),
    )
    assert result.status is VerificationStatus.FAILED
    assert "mismatched tenant_id" in result.failed_checks[0]


def test_duplicate_id_and_semantic_duplicate_are_detected():
    result = engine().verify([evidence("e1"), evidence("e1")], context())
    assert result.status is VerificationStatus.FAILED

    result = engine().verify([evidence("e1"), evidence("e2")], context())
    assert result.status is VerificationStatus.CONFLICTING
    assert "semantic duplicate" in result.failed_checks[0]


def test_explicit_normalized_claim_conflict_is_conflicting():
    result = engine().verify(
        [evidence("e1", claim="provider says one"), evidence("e2", claim="provider says two")],
        context(normalized_claims={
            "e1": NormalizedClaim(key="record_count", value=1),
            "e2": NormalizedClaim(key="record_count", value=2),
        }),
    )
    assert result.status is VerificationStatus.CONFLICTING
    assert any("conflicting normalized claim" in item for item in result.failed_checks)


@pytest.mark.parametrize(
    ("record_status", "context_field", "expected"),
    [
        (VerificationStatus.EXPIRED, "expired_evidence_ids", VerificationStatus.EXPIRED),
        (VerificationStatus.PENDING, "revoked_evidence_ids", VerificationStatus.REVOKED),
    ],
)
def test_expiry_and_revocation_fail_closed(record_status, context_field, expected):
    result = engine().verify([evidence("e1", status=record_status)], context(**{context_field: {"e1"}}))
    assert result.status is expected


def test_related_events_require_known_event_set():
    result = engine().verify([evidence("e1", related_events=["event-1"])], context())
    assert result.status is VerificationStatus.FAILED
    assert "no known event set" in result.failed_checks[0]


def test_signature_reference_does_not_claim_cryptographic_verification():
    record = evidence("e1").model_copy(update={"signature_reference": "sig-1"})
    result = engine().verify([record], context())
    assert result.status is VerificationStatus.INSUFFICIENT
    assert "signature not verified" in result.failed_checks[0]
