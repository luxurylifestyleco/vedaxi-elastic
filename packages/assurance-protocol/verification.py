"""Pure in-memory verification for the outcome/evidence contracts.

This module validates correlation and explicit evidence relationships.  It does
not fetch artifacts, verify signatures, authenticate issuers, or call providers.
Those capabilities remain outside this bounded contract-level slice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Iterable, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

try:  # Supports both package imports and the repository's direct test imports.
    from .outcome import EvidenceRecord, VerificationResult, VerificationStatus
    from .execution_context import ExecutionContext
except ImportError:  # pragma: no cover - exercised by direct pytest collection
    from outcome import EvidenceRecord, VerificationResult, VerificationStatus
    from execution_context import ExecutionContext


class AdapterCheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT = "insufficient"
    PENDING = "pending"


class NormalizedClaim(BaseModel):
    """Explicit normalized claim data supplied by a trusted policy layer.

    The engine never derives this structure from free-form evidence prose.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    key: str = Field(min_length=1, max_length=512)
    value: object


class VerificationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    outcome_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    policy_reference: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    required_evidence_ids: list[str] = Field(default_factory=list)
    known_event_ids: set[str] | None = None
    normalized_claims: dict[str, NormalizedClaim] = Field(default_factory=dict)
    expired_evidence_ids: set[str] = Field(default_factory=set)
    revoked_evidence_ids: set[str] = Field(default_factory=set)
    signature_verified_evidence_ids: set[str] = Field(default_factory=set)
    execution_context: ExecutionContext | None = None


class AdapterCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    adapter_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    status: AdapterCheckStatus
    reason: str = Field(min_length=1)


class VerificationAdapter(Protocol):
    """A deterministic, side-effect-free check for one evidence type."""

    adapter_id: str

    def supports(self, evidence: EvidenceRecord) -> bool:
        ...

    def check(self, evidence: EvidenceRecord, context: VerificationContext) -> AdapterCheck:
        ...


def _fingerprint(evidence: EvidenceRecord) -> str:
    """Return a stable fingerprint for semantic duplicate detection."""

    payload = {
        "outcome_id": evidence.outcome_id,
        "execution_id": evidence.execution_id,
        "evidence_type": evidence.evidence_type,
        "issuer": evidence.issuer,
        "claim": evidence.claim,
        "subject": evidence.subject,
        "content_digest": evidence.content_digest,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


class VerificationEngine:
    """Evaluate a bounded evidence set without external I/O or persistence."""

    def __init__(self, adapters: Sequence[VerificationAdapter] = ()) -> None:
        self._adapters = tuple(adapters)

    def verify(
        self,
        evidence: Iterable[EvidenceRecord],
        context: VerificationContext,
        *,
        verification_id: str = "verification-1",
    ) -> VerificationResult:
        records = tuple(evidence)
        if not records:
            raise ValueError("At least one evidence record is required")

        evidence_ids = [record.evidence_id for record in records]
        if len(evidence_ids) != len(set(evidence_ids)):
            return self._result(
                verification_id,
                context,
                evidence_ids,
                VerificationStatus.FAILED,
                ["duplicate evidence_id in verification input"],
                "Evidence input contains duplicate IDs",
            )

        correlation_errors = self._correlation_errors(records, context)
        if correlation_errors:
            return self._result(
                verification_id, context, evidence_ids, VerificationStatus.FAILED,
                correlation_errors, "Evidence correlation failed",
            )

        fingerprints: dict[str, str] = {}
        duplicate_errors: list[str] = []
        for record in records:
            fingerprint = _fingerprint(record)
            previous = fingerprints.get(fingerprint)
            if previous is not None:
                duplicate_errors.append(f"semantic duplicate: {previous} and {record.evidence_id}")
            else:
                fingerprints[fingerprint] = record.evidence_id
        if duplicate_errors:
            return self._result(
                verification_id, context, evidence_ids, VerificationStatus.CONFLICTING,
                duplicate_errors, "Semantic duplicate evidence detected",
            )

        conflict_errors = self._claim_conflicts(records, context.normalized_claims)
        if conflict_errors:
            return self._result(
                verification_id, context, evidence_ids, VerificationStatus.CONFLICTING,
                conflict_errors, "Explicit normalized claims conflict",
            )

        for record in records:
            if record.evidence_id in context.revoked_evidence_ids or record.verification_status is VerificationStatus.REVOKED:
                return self._result(
                    verification_id, context, evidence_ids, VerificationStatus.REVOKED,
                    [f"evidence {record.evidence_id} is revoked"], "Revoked evidence present",
                )
            if record.evidence_id in context.expired_evidence_ids or record.verification_status is VerificationStatus.EXPIRED:
                return self._result(
                    verification_id, context, evidence_ids, VerificationStatus.EXPIRED,
                    [f"evidence {record.evidence_id} is expired"], "Expired evidence present",
                )

        unsigned_references = [
            record.evidence_id
            for record in records
            if record.signature_reference
            and record.evidence_id not in context.signature_verified_evidence_ids
        ]
        if unsigned_references:
            return self._result(
                verification_id,
                context,
                evidence_ids,
                VerificationStatus.INSUFFICIENT,
                [f"signature not verified for evidence {item}" for item in unsigned_references],
                "Evidence contains an unverified signature reference",
            )

        checks: list[AdapterCheck] = []
        missing_adapters: list[str] = []
        for record in records:
            applicable = [adapter for adapter in self._adapters if adapter.supports(record)]
            if not applicable:
                missing_adapters.append(record.evidence_id)
                continue
            checks.extend(adapter.check(record, context) for adapter in applicable)

        if missing_adapters:
            return self._result(
                verification_id, context, evidence_ids, VerificationStatus.INSUFFICIENT,
                [f"no verification adapter for evidence {item}" for item in missing_adapters],
                "Required verification adapter is missing",
            )

        failed = [check.reason for check in checks if check.status is AdapterCheckStatus.FAIL]
        if failed:
            return self._result(verification_id, context, evidence_ids, VerificationStatus.FAILED, failed, "Adapter verification failed")
        if any(check.status is AdapterCheckStatus.PENDING for check in checks):
            return self._result(verification_id, context, evidence_ids, VerificationStatus.PENDING, [check.reason for check in checks], "Adapter verification is pending")
        if any(check.status is AdapterCheckStatus.INSUFFICIENT for check in checks):
            return self._result(verification_id, context, evidence_ids, VerificationStatus.INSUFFICIENT, [check.reason for check in checks], "Adapter verification is insufficient")

        return self._result(
            verification_id, context, evidence_ids, VerificationStatus.VERIFIED,
            [check.reason for check in checks], "All supplied verification checks passed",
        )

    @staticmethod
    def _correlation_errors(records: Sequence[EvidenceRecord], context: VerificationContext) -> list[str]:
        errors: list[str] = []
        ids = {record.evidence_id for record in records}
        if not set(context.required_evidence_ids).issubset(ids):
            missing = sorted(set(context.required_evidence_ids) - ids)
            errors.append(f"required evidence missing: {', '.join(missing)}")
        for record in records:
            if context.execution_context is not None and record.tenant_id != context.execution_context.tenant_id:
                errors.append(f"evidence {record.evidence_id} has mismatched tenant_id")
            if record.outcome_id != context.outcome_id:
                errors.append(f"evidence {record.evidence_id} has mismatched outcome_id")
            if record.execution_id != context.execution_id:
                errors.append(f"evidence {record.evidence_id} has mismatched execution_id")
            unknown_refs = sorted(set(record.related_evidence_ids) - ids)
            if unknown_refs:
                errors.append(f"evidence {record.evidence_id} references unknown evidence: {', '.join(unknown_refs)}")
            if record.related_event_ids and context.known_event_ids is None:
                errors.append(f"evidence {record.evidence_id} has events but no known event set")
            elif context.known_event_ids is not None:
                unknown_events = sorted(set(record.related_event_ids) - context.known_event_ids)
                if unknown_events:
                    errors.append(f"evidence {record.evidence_id} references unknown events: {', '.join(unknown_events)}")
        return errors

    @staticmethod
    def _claim_conflicts(
        records: Sequence[EvidenceRecord], claims: Mapping[str, NormalizedClaim]
    ) -> list[str]:
        seen: dict[tuple[str, str], tuple[object, str]] = {}
        errors: list[str] = []
        for record in records:
            claim = claims.get(record.evidence_id)
            if claim is None:
                continue
            key = (record.subject, claim.key)
            prior = seen.get(key)
            if prior is not None and prior[0] != claim.value:
                errors.append(f"conflicting normalized claim {claim.key} for subject {record.subject}: {prior[1]} and {record.evidence_id}")
            else:
                seen[key] = (claim.value, record.evidence_id)
        return errors

    @staticmethod
    def _result(
        verification_id: str,
        context: VerificationContext,
        evidence_ids: list[str],
        status: VerificationStatus,
        failures: list[str],
        reason: str,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=verification_id,
            outcome_id=context.outcome_id,
            execution_id=context.execution_id,
            status=status,
            checked=["correlation", "duplicate", "conflict", "expiry", "revocation", "adapter"],
            policy_reference=context.policy_reference,
            evidence_ids=evidence_ids,
            passed_checks=[] if failures else ["correlation", "duplicate", "conflict", "expiry", "revocation", "adapter"],
            failed_checks=failures,
            verified_at=context.verified_at,
            verifier_id=context.verifier_id,
            reason=reason,
        )
