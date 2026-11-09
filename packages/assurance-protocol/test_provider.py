import pytest
from pytest import raises

try:
    from .provider import (
        FakeProvider,
        LocalTrustRoot,
        ProviderExecutionRequest,
        ProviderExecutorRegistry,
        ProviderOperationState,
        ProviderReceipt,
        ReceiptVerificationStatus,
        UnsupportedProviderError,
        canonical_receipt_digest,
        sign_receipt,
        verify_provider_receipt,
        verify_receipt_signature,
    )
    from .recovery import OperationIdentity
except ImportError:  # pragma: no cover
    from provider import (
        FakeProvider, LocalTrustRoot, ProviderExecutionRequest, ProviderExecutorRegistry,
        ProviderOperationState, ProviderReceipt, ReceiptVerificationStatus,
        UnsupportedProviderError, canonical_receipt_digest, sign_receipt, verify_provider_receipt,
        verify_receipt_signature,
    )
    from recovery import OperationIdentity


def request(*, key="operation-1"):
    return ProviderExecutionRequest(
        operation=OperationIdentity(
            tenant_id="tenant-1", outcome_id="outcome-1", execution_id="execution-1",
            step_id="step-1", request_digest="request-digest", operation_key=key,
        ),
        provider_id="fake-provider", protocol="test", capability_id="capability-1",
        input_digest="input-digest",
    )


def test_fake_provider_success_is_deterministic_and_replay_is_duplicate():
    provider = FakeProvider()
    first = provider.execute(request())
    replay = provider.execute(request())

    assert first.state is ProviderOperationState.SUCCEEDED
    assert replay.state is ProviderOperationState.DUPLICATE
    assert replay.provider_operation_id == first.provider_operation_id
    assert replay.receipt_digest == canonical_receipt_digest(replay)


def test_timeout_is_unknown_and_does_not_claim_failure_or_success():
    receipt = FakeProvider().timeout(request())

    assert receipt.state is ProviderOperationState.UNKNOWN
    assert receipt.output_digest is None


def test_conflicting_receipts_preserve_both_views_for_reconciliation():
    first, second = FakeProvider().conflicting_receipts(request())

    assert first.operation_key == second.operation_key
    assert first.state is ProviderOperationState.SUCCEEDED
    assert second.state is ProviderOperationState.FAILED
    assert first.receipt_digest != second.receipt_digest


def test_provider_receipt_rejects_unknown_fields():
    with raises(ValueError):
        ProviderReceipt(
            provider_id="p", issuer_id="p", operation_key="o", provider_operation_id="po",
            request_digest="d",
            state=ProviderOperationState.UNKNOWN, receipt_digest="r", detail="d",
            unexpected="x",
        )


def test_provider_mismatch_fails_closed():
    with raises(ValueError, match="provider_id"):
        FakeProvider().execute(request(key="x").model_copy(update={"provider_id": "other"}))


def test_receipt_verification_accepts_correlated_deterministic_receipt():
    req = request()
    receipt = FakeProvider().execute(req)

    result = verify_provider_receipt(req, receipt, expected_issuer_id="fake-provider")

    assert result.status is ReceiptVerificationStatus.VERIFIED
    assert result.reasons == ()


def test_receipt_verification_rejects_operation_and_request_digest_mismatch():
    req = request()
    receipt = FakeProvider().execute(req).model_copy(
        update={"operation_key": "other", "request_digest": "wrong"}
    )

    result = verify_provider_receipt(req, receipt, expected_issuer_id="fake-provider")

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert "operation_key mismatch" in result.reasons
    assert "request_digest mismatch" in result.reasons


def test_receipt_verification_rejects_issuer_and_receipt_digest_mismatch():
    req = request()
    receipt = FakeProvider().execute(req).model_copy(
        update={"issuer_id": "untrusted", "receipt_digest": "tampered"}
    )

    result = verify_provider_receipt(req, receipt, expected_issuer_id="fake-provider")

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert "issuer_id mismatch" in result.reasons
    assert "receipt_digest mismatch" in result.reasons


def test_receipt_verification_does_not_claim_signature_or_live_provider_proof():
    req = request()
    receipt = FakeProvider().execute(req)

    result = verify_provider_receipt(req, receipt, expected_issuer_id="fake-provider")

    assert result.status is ReceiptVerificationStatus.VERIFIED
    assert "signature" not in " ".join(result.reasons).lower()


def test_registry_resolves_provider_by_exact_capability_and_protocol_metadata():
    registry = ProviderExecutorRegistry()
    provider = FakeProvider()
    registry.register(
        provider_id="fake-provider", protocol="test", capability_id="capability-1",
        executor=provider,
    )

    assert registry.resolve(request()) is provider
    assert registry.execute(request()).state is ProviderOperationState.SUCCEEDED


def test_registry_selects_deterministically_by_provider_id():
    registry = ProviderExecutorRegistry()
    first = FakeProvider("provider-a")
    second = FakeProvider("provider-b")
    for provider in (second, first):
        registry.register(
            provider_id=provider.provider_id, protocol="test", capability_id="capability-1",
            executor=provider,
        )

    selected = registry.select(protocol="test", capability_id="capability-1")

    assert selected.provider_id == "provider-a"


def test_registry_fails_closed_for_unsupported_provider_or_metadata():
    registry = ProviderExecutorRegistry()
    registry.register(
        provider_id="fake-provider", protocol="test", capability_id="capability-1",
        executor=FakeProvider(),
    )

    with raises(UnsupportedProviderError, match="no executor"):
        registry.resolve(request().model_copy(update={"provider_id": "missing"}))
    with raises(UnsupportedProviderError, match="no executor"):
        registry.select(protocol="other", capability_id="capability-1")


def test_registry_rejects_duplicate_registration():
    registry = ProviderExecutorRegistry()
    kwargs = dict(
        provider_id="fake-provider", protocol="test", capability_id="capability-1",
        executor=FakeProvider(),
    )
    registry.register(**kwargs)

    with raises(ValueError, match="already exists"):
        registry.register(**kwargs)


_THROWAWAY_TRUST_KEY = b"throwaway-local-hmac-key"


def test_signed_receipt_from_matching_issuer_verifies():
    receipt = FakeProvider().execute(request())
    trust_root = LocalTrustRoot(issuer_id=receipt.issuer_id, key=_THROWAWAY_TRUST_KEY)

    result = verify_receipt_signature(
        receipt, sign_receipt(receipt, trust_root), trust_root=trust_root
    )

    assert result.status is ReceiptVerificationStatus.VERIFIED
    assert result.reasons == ()


def test_signed_receipt_rejects_request_digest_tampering():
    receipt = FakeProvider().execute(request())
    trust_root = LocalTrustRoot(issuer_id=receipt.issuer_id, key=_THROWAWAY_TRUST_KEY)
    signature = sign_receipt(receipt, trust_root)

    result = verify_receipt_signature(
        receipt.model_copy(update={"request_digest": "tampered-request"}),
        signature,
        trust_root=trust_root,
    )

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert result.reasons == ("signature mismatch",)


def test_signed_receipt_rejects_issuer_id_tampering():
    receipt = FakeProvider().execute(request())
    trust_root = LocalTrustRoot(issuer_id=receipt.issuer_id, key=_THROWAWAY_TRUST_KEY)
    signature = sign_receipt(receipt, trust_root)

    result = verify_receipt_signature(
        receipt.model_copy(update={"issuer_id": "tampered-issuer"}),
        signature,
        trust_root=trust_root,
    )

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert result.reasons == ("issuer not in trust root", "signature mismatch")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", "tampered|provider"),
        ("operation_key", "tampered|operation"),
        ("provider_operation_id", "tampered|provider-operation"),
        ("request_digest", "tampered|request"),
        ("state", ProviderOperationState.FAILED),
        ("output_digest", "tampered|output"),
        ("detail", "tampered|detail"),
    ],
)
def test_signed_receipt_rejects_security_field_tampering(field, value):
    receipt = FakeProvider().execute(request())
    trust_root = LocalTrustRoot(issuer_id=receipt.issuer_id, key=_THROWAWAY_TRUST_KEY)
    signature = sign_receipt(receipt, trust_root)

    result = verify_receipt_signature(
        receipt.model_copy(update={field: value}),
        signature,
        trust_root=trust_root,
    )

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert result.reasons == ("signature mismatch",)


def test_canonical_receipt_payload_preserves_null_empty_and_separator_values():
    receipt = FakeProvider().execute(request())

    null_output = receipt.model_copy(update={"output_digest": None})
    empty_output = receipt.model_copy(update={"output_digest": ""})
    separator_output = receipt.model_copy(update={"output_digest": "a|b,{}"})

    assert canonical_receipt_digest(null_output) != canonical_receipt_digest(empty_output)
    assert canonical_receipt_digest(empty_output) != canonical_receipt_digest(separator_output)


def test_forged_signature_is_rejected_with_signature_mismatch():
    receipt = FakeProvider().execute(request())
    trust_root = LocalTrustRoot(issuer_id=receipt.issuer_id, key=_THROWAWAY_TRUST_KEY)

    result = verify_receipt_signature(receipt, "0" * 64, trust_root=trust_root)

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert result.reasons == ("signature mismatch",)


def test_wrong_issuer_is_rejected_with_issuer_not_in_trust_root():
    receipt = FakeProvider().execute(request()).model_copy(update={"issuer_id": "other-issuer"})
    trust_root = LocalTrustRoot(issuer_id="fake-provider", key=_THROWAWAY_TRUST_KEY)

    result = verify_receipt_signature(
        receipt, sign_receipt(receipt, trust_root), trust_root=trust_root
    )

    assert result.status is ReceiptVerificationStatus.REJECTED
    assert result.reasons == ("issuer not in trust root",)
