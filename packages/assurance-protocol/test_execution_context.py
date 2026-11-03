from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from execution_context import AuthKind, ExecutionContext, PrincipalKind


NOW = datetime.now(timezone.utc)


def make_context(**overrides) -> ExecutionContext:
    values = {
        "tenant_id": "tenant-1",
        "principal_id": "principal-1",
        "principal_kind": PrincipalKind.AGENT,
        "auth_kind": AuthKind.DELEGATED,
        "organization_id": "tenant-1",
        "delegation_id": "delegation-1",
        "policy_epoch": 1,
        "scopes": ("records:read",),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "revocation_reference": "revocation-1",
        "authorization_decision_id": "decision-1",
    }
    values.update(overrides)
    return ExecutionContext(**values)


def test_accepts_complete_context_and_normalizes_scope_sequence():
    context = make_context(scopes=["records:read"])
    assert context.tenant_id == context.organization_id
    assert context.scopes == ("records:read",)
    assert context.principal_kind is PrincipalKind.AGENT
    assert context.auth_kind is AuthKind.DELEGATED


def test_context_is_immutable():
    context = make_context()
    with pytest.raises(ValidationError):
        context.tenant_id = "other-tenant"
    with pytest.raises(ValidationError):
        context.scopes += ("records:write",)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tenant_id", "tenant-2", "tenant_id"),
        ("policy_epoch", 0, "policy_epoch"),
        ("scopes", (), "scopes"),
        ("principal_kind", "unknown", "principal_kind"),
        ("auth_kind", "password", "auth_kind"),
        ("expires_at", NOW - timedelta(seconds=1), "expires_at"),
    ],
)
def test_rejects_invalid_or_expired_context(field, value, message):
    with pytest.raises((ValidationError, ValueError), match=message):
        make_context(**{field: value})


def test_rejects_expiry_before_issuance():
    with pytest.raises(ValidationError, match="expires_at"):
        make_context(expires_at=NOW - timedelta(minutes=1))


def test_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="extra_field"):
        make_context(extra_field="not-allowed")
