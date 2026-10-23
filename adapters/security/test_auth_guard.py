"""Tests for AuthorizationGuard (invocation-time permission and safety enforcement)."""

from __future__ import annotations

import os
import sys
import time
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
for _p in [
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "adapters"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.security.auth_guard import (
    AuthorizationGuard,
    SecurityPrincipal,
    UnauthorizedError,
    CredentialsExpiredError,
    PermissionDeniedError,
    SensitiveActionDeniedError,
)
from capability import Capability


@pytest.fixture
def read_cap():
    return Capability(
        id="get_balance",
        name="Get Balance",
        description="Read account balance",
        domain="accounts",
        permissions=["accounts:read"],
    )


@pytest.fixture
def sensitive_cap():
    return Capability(
        id="make_payment",
        name="Make Payment",
        description="Transfer money to payee",
        domain="payments",
        permissions=["payments:write"],
    )


def test_unauthenticated_protected_call_fails(read_cap):
    guard = AuthorizationGuard()
    with pytest.raises(UnauthorizedError) as exc_info:
        guard.check(read_cap, principal=None)
    assert "requires authentication" in str(exc_info.value)


def test_expired_token_fails(read_cap):
    guard = AuthorizationGuard()
    expired_user = SecurityPrincipal(
        subject="user_old",
        granted_permissions={"accounts:read"},
        expires_at=time.time() - 10.0,
    )
    with pytest.raises(CredentialsExpiredError):
        guard.check(read_cap, principal=expired_user)


def test_missing_permission_fails(read_cap):
    guard = AuthorizationGuard()
    unauthorized_user = SecurityPrincipal(
        subject="user_limited",
        granted_permissions={"profile:read"},  # Missing accounts:read
    )
    with pytest.raises(PermissionDeniedError) as exc_info:
        guard.check(read_cap, principal=unauthorized_user)
    assert "Missing permissions" in str(exc_info.value)


def test_granted_permission_succeeds(read_cap):
    guard = AuthorizationGuard()
    valid_user = SecurityPrincipal(
        subject="user_valid",
        granted_permissions={"accounts:read"},
    )
    # Should not raise
    guard.check(read_cap, principal=valid_user)


def test_caller_flag_and_bypass_do_not_approve(sensitive_cap):
    guard = AuthorizationGuard()
    user_with_write = SecurityPrincipal(
        subject="user_financier",
        granted_permissions={"payments:write", "approval:bypass"},
    )
    with pytest.raises(SensitiveActionDeniedError):
        guard.check(sensitive_cap, principal=user_with_write, explicit_approval=True)


def test_cross_tenant_is_denied(read_cap):
    guard = AuthorizationGuard()
    foreign = SecurityPrincipal(
        subject="other_tenant",
        tenant_id="tenant-b",
        granted_permissions={"accounts:read"},
    )
    bound = read_cap.model_copy(update={"metadata": {"tenant_id": "tenant-a"}})
    with pytest.raises(PermissionDeniedError, match="Cross-tenant"):
        guard.check(bound, principal=foreign)


def test_admin_flag_does_not_bypass(sensitive_cap):
    guard = AuthorizationGuard()
    admin_user = SecurityPrincipal(subject="admin_user", is_admin=True)
    with pytest.raises(PermissionDeniedError):
        guard.check(sensitive_cap, principal=admin_user, explicit_approval=False)
