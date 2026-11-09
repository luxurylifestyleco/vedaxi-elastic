"""Protocol-neutral provider execution contracts and deterministic fakes.

This module models the boundary between the runtime and a provider.  It does
not perform network I/O or claim that a fake receipt is external proof.
Correlation checks do not verify signatures.  A local HMAC trust root can.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

try:
    from .recovery import OperationIdentity
except ImportError:  # pragma: no cover
    from recovery import OperationIdentity


class ProviderOperationState(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    DUPLICATE = "DUPLICATE"
    CONFLICTING = "CONFLICTING"


class ReceiptVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ProviderExecutionRequest(BaseModel):
    """A provider-neutral request; dispatch remains the caller's concern."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    operation: OperationIdentity
    provider_id: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    input_digest: str = Field(min_length=1)


class ProviderReceipt(BaseModel):
    """A provider result-shaped receipt, not an authenticated attestation."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    provider_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    provider_operation_id: str = Field(min_length=1)
    request_digest: str = Field(min_length=1)
    state: ProviderOperationState
    output_digest: str | None = None
    receipt_digest: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ReceiptVerificationResult(BaseModel):
    """Deterministic contract validation, not cryptographic attestation."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    status: ReceiptVerificationStatus
    reasons: tuple[str, ...] = ()


def canonical_receipt_digest(receipt: ProviderReceipt) -> str:
    """Return the deterministic digest representation used by local tests.

    This is an equality-bound contract value, not a signature or a proof of
    issuer identity.  A real adapter must replace this with an approved
    provider-specific digest and signature policy.
    """

    return json.dumps(
        {
            "issuer_id": receipt.issuer_id,
            "operation_key": receipt.operation_key,
            "output_digest": receipt.output_digest,
            "provider_id": receipt.provider_id,
            "provider_operation_id": receipt.provider_operation_id,
            "request_digest": receipt.request_digest,
            "state": receipt.state.value,
            "detail": receipt.detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def verify_provider_receipt(
    request: ProviderExecutionRequest,
    receipt: ProviderReceipt,
    *,
    expected_issuer_id: str,
) -> ReceiptVerificationResult:
    """Validate local receipt correlation and digest/issuer consistency.

    The result deliberately does not verify signatures, keys, TLS, or a live
    provider.  Callers must not treat ``VERIFIED`` as external attestation.
    """

    reasons: list[str] = []
    if receipt.provider_id != request.provider_id:
        reasons.append("provider_id mismatch")
    if receipt.operation_key != request.operation.operation_key:
        reasons.append("operation_key mismatch")
    if receipt.request_digest != request.operation.request_digest:
        reasons.append("request_digest mismatch")
    if receipt.issuer_id != expected_issuer_id:
        reasons.append("issuer_id mismatch")
    if receipt.receipt_digest != canonical_receipt_digest(receipt):
        reasons.append("receipt_digest mismatch")
    if not receipt.provider_operation_id.startswith(f"{request.provider_id}:"):
        reasons.append("provider_operation_id correlation mismatch")
    return ReceiptVerificationResult(
        status=(ReceiptVerificationStatus.VERIFIED if not reasons else ReceiptVerificationStatus.REJECTED),
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class LocalTrustRoot:
    """A named local verification key. Not a payment credential and not a network issuer."""

    issuer_id: str
    key: bytes


def sign_receipt(receipt: ProviderReceipt, trust_root: LocalTrustRoot) -> str:
    """Sign the canonical receipt digest with the local trust root."""

    return hmac.new(
        trust_root.key,
        canonical_receipt_digest(receipt).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_receipt_signature(
    receipt: ProviderReceipt,
    signature: str,
    *,
    trust_root: LocalTrustRoot,
) -> ReceiptVerificationResult:
    """Verify an HMAC signature against one local trust root.

    A match is local trust-root proof only. It is not a live provider attestation
    and it does not authorize a payment.
    """

    reasons: list[str] = []
    if receipt.issuer_id != trust_root.issuer_id:
        reasons.append("issuer not in trust root")
    expected = sign_receipt(receipt, trust_root)
    if not hmac.compare_digest(signature, expected):
        reasons.append("signature mismatch")
    return ReceiptVerificationResult(
        status=(ReceiptVerificationStatus.VERIFIED if not reasons else ReceiptVerificationStatus.REJECTED),
        reasons=tuple(reasons),
    )


class ProviderExecutor(Protocol):
    """Side-effect boundary for a provider implementation."""

    def execute(self, request: ProviderExecutionRequest) -> ProviderReceipt:
        ...


class UnsupportedProviderError(LookupError):
    """Raised when no registered executor supports the requested metadata."""


@dataclass(frozen=True)
class ProviderRegistration:
    """A provider executor bound to an exact protocol/capability pair."""

    provider_id: str
    protocol: str
    capability_id: str
    executor: ProviderExecutor


class ProviderExecutorRegistry:
    """Deterministic, in-memory provider executor lookup.

    This is a dispatch contract only. It does not perform health checks,
    fallback after unknown provider state, network I/O, or trust verification.
    """

    def __init__(self) -> None:
        self._registrations: dict[tuple[str, str, str], ProviderRegistration] = {}

    def register(
        self,
        *,
        provider_id: str,
        protocol: str,
        capability_id: str,
        executor: ProviderExecutor,
    ) -> ProviderRegistration:
        if not provider_id or not protocol or not capability_id:
            raise ValueError("provider_id, protocol, and capability_id are required")
        key = (provider_id, protocol, capability_id)
        if key in self._registrations:
            raise ValueError(f"provider registration already exists: {key!r}")
        registration = ProviderRegistration(provider_id, protocol, capability_id, executor)
        self._registrations[key] = registration
        return registration

    def select(
        self,
        *,
        capability_id: str,
        protocol: str,
        provider_id: str | None = None,
    ) -> ProviderRegistration:
        """Select an executor using exact metadata and stable provider ordering."""

        matches = [
            registration
            for registration in self._registrations.values()
            if registration.capability_id == capability_id
            and registration.protocol == protocol
            and (provider_id is None or registration.provider_id == provider_id)
        ]
        if not matches:
            requested = provider_id or "any provider"
            raise UnsupportedProviderError(
                f"no executor for provider={requested!r}, protocol={protocol!r}, "
                f"capability={capability_id!r}"
            )
        return sorted(matches, key=lambda registration: registration.provider_id)[0]

    def resolve(self, request: ProviderExecutionRequest) -> ProviderExecutor:
        """Resolve the exact executor required by a provider request."""

        return self.select(
            provider_id=request.provider_id,
            protocol=request.protocol,
            capability_id=request.capability_id,
        ).executor

    def execute(self, request: ProviderExecutionRequest) -> ProviderReceipt:
        """Dispatch through the registered executor, failing closed on absence."""

        return self.resolve(request).execute(request)


class FakeProvider:
    """Deterministic fake for local contract tests only."""

    def __init__(self, provider_id: str = "fake-provider") -> None:
        self.provider_id = provider_id
        self._operations: dict[str, ProviderReceipt] = {}

    def execute(self, request: ProviderExecutionRequest) -> ProviderReceipt:
        if request.provider_id != self.provider_id:
            raise ValueError("request provider_id does not match fake provider")
        previous = self._operations.get(request.operation.operation_key)
        if previous is not None:
            duplicate = previous.model_copy(
                update={
                    "state": ProviderOperationState.DUPLICATE,
                    "detail": "operation key already executed",
                }
            )
            return duplicate.model_copy(update={"receipt_digest": canonical_receipt_digest(duplicate)})
        receipt = ProviderReceipt(
            provider_id=self.provider_id,
            issuer_id=self.provider_id,
            operation_key=request.operation.operation_key,
            provider_operation_id=f"{self.provider_id}:{request.operation.operation_key}",
            request_digest=request.operation.request_digest,
            state=ProviderOperationState.SUCCEEDED,
            output_digest=f"output:{request.input_digest}",
            receipt_digest="pending",
            detail="deterministic fake success",
        )
        receipt = receipt.model_copy(update={"receipt_digest": canonical_receipt_digest(receipt)})
        self._operations[request.operation.operation_key] = receipt
        return receipt

    def timeout(self, request: ProviderExecutionRequest) -> ProviderReceipt:
        """Return unknown state without recording a terminal success."""
        receipt = ProviderReceipt(
            provider_id=self.provider_id,
            issuer_id=self.provider_id,
            operation_key=request.operation.operation_key,
            provider_operation_id=f"{self.provider_id}:{request.operation.operation_key}",
            request_digest=request.operation.request_digest,
            state=ProviderOperationState.UNKNOWN,
            receipt_digest="pending",
            detail="provider state is unknown after timeout",
        )
        return receipt.model_copy(update={"receipt_digest": canonical_receipt_digest(receipt)})

    def conflicting_receipts(self, request: ProviderExecutionRequest) -> tuple[ProviderReceipt, ProviderReceipt]:
        """Return two incompatible receipts for reconciliation tests."""
        base = dict(
            provider_id=self.provider_id,
            issuer_id=self.provider_id,
            operation_key=request.operation.operation_key,
            provider_operation_id=f"{self.provider_id}:{request.operation.operation_key}",
            request_digest=request.operation.request_digest,
        )
        first = ProviderReceipt(
            **base, state=ProviderOperationState.SUCCEEDED,
            output_digest="output:a", receipt_digest="pending", detail="success view",
        )
        second = ProviderReceipt(
            **base, state=ProviderOperationState.FAILED,
            receipt_digest="pending", detail="failure view",
        )
        return (
            first.model_copy(update={"receipt_digest": canonical_receipt_digest(first)}),
            second.model_copy(update={"receipt_digest": canonical_receipt_digest(second)}),
        )
