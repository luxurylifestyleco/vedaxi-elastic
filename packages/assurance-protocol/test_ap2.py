from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from assurance_protocol.ap2 import (
    AP2BoundaryStatus,
    AP2Decision,
    AP2Mandate,
    AP2PaymentReceipt,
    AP2PaymentRequest,
    AP2PaymentState,
    ap2_integration_boundary,
    evaluate_ap2_payment,
    reject_unconfigured_ap2,
)
from assurance_protocol.recovery import OperationIdentity


NOW = datetime.now(timezone.utc)


def operation() -> OperationIdentity:
    return OperationIdentity(
        tenant_id="tenant-1",
        outcome_id="outcome-1",
        execution_id="execution-1",
        step_id="payment-1",
        request_digest="request-digest",
        operation_key="operation-1",
    )


def mandate() -> AP2Mandate:
    return AP2Mandate(
        mandate_id="mandate-1",
        issuer_id="issuer-1",
        merchant_id="merchant-1",
        currency="USD",
        max_amount_minor=5000,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        authorization_reference="auth-ref-1",
    )


def request() -> AP2PaymentRequest:
    return AP2PaymentRequest(
        operation=operation(),
        mandate=mandate(),
        amount_minor=1200,
        currency="USD",
        merchant_id="merchant-1",
        request_digest="payment-request-digest",
    )


def receipt(**overrides: object) -> AP2PaymentReceipt:
    values: dict[str, object] = {
        "provider_id": "provider-1",
        "issuer_id": "issuer-1",
        "operation_key": "operation-1",
        "mandate_id": "mandate-1",
        "provider_operation_id": "provider-op-1",
        "state": AP2PaymentState.SETTLED,
        "receipt_digest": "receipt-digest",
        "observed_at": NOW,
    }
    values.update(overrides)
    return AP2PaymentReceipt(**values)


def test_default_boundary_rejects_without_adapter():
    result = reject_unconfigured_ap2()
    assert result.decision is AP2Decision.REJECTED
    assert result.authoritative is False


def test_integration_boundary_marks_live_provider_behavior_external_and_unknown():
    boundary = ap2_integration_boundary()

    assert boundary.live_payment_execution is AP2BoundaryStatus.EXTERNAL
    assert boundary.provider_authentication is AP2BoundaryStatus.UNKNOWN
    assert boundary.receipt_signature_verification is AP2BoundaryStatus.UNKNOWN
    assert boundary.payment_completion is AP2BoundaryStatus.UNKNOWN
    assert boundary.external_calls_enabled is False
    assert set(boundary.local_contracts) == {
        "mandate_validation",
        "request_binding",
        "receipt_shape",
        "fail_closed_evaluation",
    }


def test_even_complete_local_inputs_never_claim_live_payment_completion():
    result = evaluate_ap2_payment(
        request(),
        receipt(),
        issuer_trust_configured=True,
        signature_verified=True,
    )

    assert result.decision is AP2Decision.UNVERIFIED
    assert result.authoritative is False
    assert "not implemented" in result.reasons[0]


def test_missing_receipt_is_unverified():
    result = evaluate_ap2_payment(request())
    assert result.decision is AP2Decision.UNVERIFIED
    assert result.authoritative is False


def test_matching_receipt_stays_unverified_without_trust_and_signature():
    result = evaluate_ap2_payment(request(), receipt())
    assert result.decision is AP2Decision.UNVERIFIED
    assert "issuer trust" in " ".join(result.reasons)
    assert "signature" in " ".join(result.reasons)


def test_mismatched_receipt_fails_closed():
    result = evaluate_ap2_payment(request(), receipt(operation_key="other-operation"))
    assert result.decision is AP2Decision.UNVERIFIED
    assert "operation_key mismatch" in result.reasons


def test_non_settled_receipt_is_not_payment_completion():
    result = evaluate_ap2_payment(request(), receipt(state=AP2PaymentState.AUTHORIZED))
    assert result.decision is AP2Decision.UNVERIFIED
    assert result.authoritative is False


def test_mandate_limits_and_identity_are_enforced():
    with pytest.raises(ValidationError, match="payment exceeds mandate limit"):
        AP2PaymentRequest(
            operation=operation(), mandate=mandate(), amount_minor=5001,
            currency="USD", merchant_id="merchant-1", request_digest="digest",
        )
    with pytest.raises(ValidationError, match="payment merchant"):
        AP2PaymentRequest(
            operation=operation(), mandate=mandate(), amount_minor=1,
            currency="USD", merchant_id="other-merchant", request_digest="digest",
        )


def test_expired_ordering_is_rejected():
    with pytest.raises(ValidationError, match="expires_at must be after"):
        AP2Mandate(
            mandate_id="mandate-1", issuer_id="issuer-1", merchant_id="merchant-1",
            currency="USD", max_amount_minor=1, issued_at=NOW,
            expires_at=NOW, authorization_reference="auth-ref-1",
        )
