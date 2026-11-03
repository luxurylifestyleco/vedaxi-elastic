from datetime import datetime, timedelta, timezone

import pytest

from authorization import AuthorizationDenied, authorize, require_authorized
from execution_context import AuthKind, ExecutionContext, PrincipalKind
from outcome import Delegation


# Keep the fixture valid when the suite is run after the original design date.
NOW = datetime.now(timezone.utc)


def context(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "principal_id": "agent-b",
        "principal_kind": PrincipalKind.AGENT,
        "auth_kind": AuthKind.DELEGATED,
        "organization_id": "tenant-1",
        "delegation_id": "d2",
        "policy_epoch": 1,
        "scopes": ("records:read",),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "authorization_decision_id": "decision-1",
    }
    values.update(overrides)
    return ExecutionContext(**values)


def delegation(**overrides):
    values = {
        "delegation_id": "d1",
        "delegator_id": "human-1",
        "delegatee_id": "agent-a",
        "capabilities": ["records:read"],
        "resource_scopes": ["tenant:records"],
        "further_delegation_allowed": True,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "authorization_proof": "proof-1",
    }
    values.update(overrides)
    return Delegation(**values)


def valid_chain():
    return [
        delegation(),
        delegation(
            delegation_id="d2",
            delegator_id="agent-a",
            delegatee_id="agent-b",
            parent_delegation_id="d1",
            further_delegation_allowed=False,
            expires_at=NOW + timedelta(minutes=5),
        ),
    ]


def test_allows_action_only_through_matching_delegation_chain():
    decision = authorize(context(), capability="records:read", resource="tenant:records", delegation_chain=valid_chain(), now=NOW)
    assert decision.allowed is True
    assert decision.delegation_id == "d2"


@pytest.mark.parametrize(
    "change",
    [
        {"delegation_id": None},
        {"principal_id": "agent-other"},
    ],
)
def test_denies_missing_or_wrong_effective_delegation(change):
    decision = authorize(context(**change), capability="records:read", resource="tenant:records", delegation_chain=valid_chain(), now=NOW)
    assert decision.allowed is False


def test_denies_expired_revoked_and_out_of_scope_delegations():
    expired = valid_chain()
    expired[-1] = expired[-1].model_copy(update={"expires_at": NOW})
    assert not authorize(context(), capability="records:read", resource="tenant:records", delegation_chain=expired, now=NOW).allowed

    revoked = valid_chain()
    revoked[-1] = revoked[-1].model_copy(update={"revoked_at": NOW})
    assert not authorize(context(), capability="records:read", resource="tenant:records", delegation_chain=revoked, now=NOW).allowed

    assert not authorize(context(), capability="records:write", resource="tenant:records", delegation_chain=valid_chain(), now=NOW).allowed
    assert not authorize(context(), capability="records:read", resource="other", delegation_chain=valid_chain(), now=NOW).allowed


def test_denies_broken_parent_link_and_narrowing_violation():
    broken = valid_chain()
    broken[-1] = broken[-1].model_copy(update={"parent_delegation_id": "wrong"})
    assert not authorize(context(), capability="records:read", resource="tenant:records", delegation_chain=broken, now=NOW).allowed

    narrowed = valid_chain()
    narrowed[-1] = narrowed[-1].model_copy(update={"capabilities": ["records:write"]})
    assert not authorize(context(), capability="records:write", resource="tenant:records", delegation_chain=narrowed, now=NOW).allowed


def test_require_authorized_raises_for_denial():
    with pytest.raises(AuthorizationDenied, match="does not authorize"):
        require_authorized(context(), capability="records:write", resource="tenant:records", delegation_chain=valid_chain(), now=NOW)
