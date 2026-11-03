"""Fail-closed, protocol-neutral AP2/payment boundary.

This module defines the minimum data boundary for a future AP2 adapter.  It
does not authorize, charge, settle, call a provider, verify signatures, or
claim payment completion.  Until an approved adapter and issuer trust policy
are supplied, every request remains ``UNVERIFIED``.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

try:
    from .recovery import OperationIdentity
except ImportError:  # pragma: no cover
    from recovery import OperationIdentity


class AP2Decision(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


class AP2BoundaryStatus(str, Enum):
    """Evidence boundary for a surface of the local AP2 integration."""

    LOCAL = "LOCAL"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


class AP2IntegrationBoundary(BaseModel):
    """The complete local AP2 boundary; no field is a claim of live payment."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    contract_version: Literal["1.0"] = "1.0"
    local_contracts: tuple[str, ...] = (
        "mandate_validation",
        "request_binding",
        "receipt_shape",
        "fail_closed_evaluation",
    )
    live_payment_execution: AP2BoundaryStatus = AP2BoundaryStatus.EXTERNAL
    provider_authentication: AP2BoundaryStatus = AP2BoundaryStatus.UNKNOWN
    receipt_signature_verification: AP2BoundaryStatus = AP2BoundaryStatus.UNKNOWN
    payment_completion: AP2BoundaryStatus = AP2BoundaryStatus.UNKNOWN
    external_calls_enabled: bool = False


def ap2_integration_boundary() -> AP2IntegrationBoundary:
    """Return the static local contract boundary for AP2 integration."""

    return AP2IntegrationBoundary()


class AP2PaymentState(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    UNKNOWN = "UNKNOWN"


class AP2Mandate(BaseModel):
    """Shape of an authorization mandate; not proof that it is valid."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    mandate_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    max_amount_minor: int = Field(gt=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    authorization_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def expires_after_issue(self) -> "AP2Mandate":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self


class AP2PaymentRequest(BaseModel):
    """Provider-neutral payment intent bound to an operation and mandate."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    operation: OperationIdentity
    mandate: AP2Mandate
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    merchant_id: str = Field(min_length=1)
    request_digest: str = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_mandate_limits(self) -> "AP2PaymentRequest":
        if self.currency != self.mandate.currency:
            raise ValueError("payment currency does not match mandate")
        if self.merchant_id != self.mandate.merchant_id:
            raise ValueError("payment merchant does not match mandate")
        if self.amount_minor > self.mandate.max_amount_minor:
            raise ValueError("payment exceeds mandate limit")
        return self


class AP2PaymentReceipt(BaseModel):
    """Receipt shape only; issuer and signature authenticity remain external."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    provider_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    mandate_id: str = Field(min_length=1)
    provider_operation_id: str = Field(min_length=1)
    state: AP2PaymentState
    receipt_digest: str = Field(min_length=1)
    observed_at: AwareDatetime


class AP2Evaluation(BaseModel):
    """Fail-closed evaluation; ``UNVERIFIED`` is never payment completion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    decision: AP2Decision
    authoritative: bool = False
    reasons: tuple[str, ...] = ()


def evaluate_ap2_payment(
    request: AP2PaymentRequest,
    receipt: AP2PaymentReceipt | None = None,
    *,
    issuer_trust_configured: bool = False,
    signature_verified: bool = False,
) -> AP2Evaluation:
    """Evaluate only locally supplied facts and fail closed by default.

    A receipt with matching identifiers is still insufficient without an
    approved issuer trust configuration and independent signature verification.
    """

    if receipt is None:
        return AP2Evaluation(
            decision=AP2Decision.UNVERIFIED,
            reasons=("no AP2 provider receipt supplied",),
        )

    reasons: list[str] = []
    if receipt.operation_key != request.operation.operation_key:
        reasons.append("operation_key mismatch")
    if receipt.mandate_id != request.mandate.mandate_id:
        reasons.append("mandate_id mismatch")
    if receipt.issuer_id != request.mandate.issuer_id:
        reasons.append("issuer_id mismatch")
    if receipt.state is not AP2PaymentState.SETTLED:
        reasons.append(f"payment state is {receipt.state.value}, not SETTLED")
    if not issuer_trust_configured:
        reasons.append("AP2 issuer trust configuration is absent")
    if not signature_verified:
        reasons.append("AP2 receipt signature is not independently verified")
    if reasons:
        return AP2Evaluation(decision=AP2Decision.UNVERIFIED, reasons=tuple(reasons))
    return AP2Evaluation(
        decision=AP2Decision.UNVERIFIED,
        reasons=("AP2 adapter authorization policy is not implemented",),
    )


def reject_unconfigured_ap2() -> AP2Evaluation:
    """Return the explicit default when no AP2 adapter is registered."""

    return AP2Evaluation(
        decision=AP2Decision.REJECTED,
        reasons=("AP2 payment boundary is not configured",),
    )
