from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from outcome import EvidenceLedger, EvidenceRecord, OutcomeEnvelope, OutcomeStatus, Delegation, transition_outcome


NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


def make_outcome() -> OutcomeEnvelope:
    return OutcomeEnvelope(
        outcome_id="o1", principal_id="human-1", originating_agent_id="agent-a",
        intent={"goal": "find records"}, desired_state={"records": 1},
        completion_criteria=["records-found"], created_at=NOW, updated_at=NOW,
    )


def make_evidence(evidence_id="e1", related=None) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id, tenant_id="tenant-1", outcome_id="o1", execution_id="x1", evidence_type="provider_receipt",
        claim="records exist", subject="records", issuer="provider", source="provider-db",
        producer="provider", observed_at=NOW, received_at=NOW, protocol_origin="rest",
        related_evidence_ids=related or [], privacy_classification="tenant-private", retention_policy="default",
    )


def test_lifecycle_requires_evidence_for_completion():
    outcome = make_outcome()
    outcome = transition_outcome(outcome, OutcomeStatus.VALIDATING)
    outcome = transition_outcome(outcome, OutcomeStatus.AUTHORIZED)
    outcome = transition_outcome(outcome, OutcomeStatus.PLANNING)
    outcome = transition_outcome(outcome, OutcomeStatus.EXECUTING)
    outcome = transition_outcome(outcome, OutcomeStatus.VERIFYING)
    with pytest.raises(ValueError, match="sufficient evidence"):
        transition_outcome(outcome, OutcomeStatus.COMPLETED)
    assert transition_outcome(outcome, OutcomeStatus.COMPLETED, sufficient_evidence=True).current_status is OutcomeStatus.COMPLETED


def test_ledger_is_append_only_and_corrections_are_linked():
    ledger = EvidenceLedger()
    ledger.append(make_evidence())
    with pytest.raises(ValueError, match="already exists"):
        ledger.append(make_evidence())
    with pytest.raises(ValueError, match="previous evidence"):
        ledger.correct("e1", make_evidence("e2"))
    ledger.correct("e1", make_evidence("e2", ["e1"]))
    assert [item.evidence_id for item in ledger.all()] == ["e1", "e2"]


def test_delegation_rejects_invalid_window():
    with pytest.raises(ValidationError):
        Delegation(
            delegation_id="d1", delegator_id="human-1", delegatee_id="agent-a", capabilities=["search"],
            resource_scopes=["records:read"], issued_at=NOW, expires_at=NOW,
            authorization_proof="proof",
        )
