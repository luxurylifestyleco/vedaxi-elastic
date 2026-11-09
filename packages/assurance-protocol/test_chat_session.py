from datetime import datetime, timedelta, timezone

import pytest

from authorization import authorize_chat_session
from execution_context import ChatSession, PrincipalKind


NOW = datetime.now(timezone.utc)


def session(**overrides) -> ChatSession:
    values = {
        "session_id": "chat-1",
        "tenant_id": "tenant-1",
        "principal_id": "principal-1",
        "principal_kind": PrincipalKind.HUMAN,
        "authenticated_at": NOW,
        "consent_id": "consent-1",
        "consented_scopes": ("support:read", "support:write"),
        "scopes": ("support:read",),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "authorization_decision_id": "decision-1",
    }
    values.update(overrides)
    return ChatSession(**values)


def authorize(**overrides):
    values = {
        "tenant_id": "tenant-1",
        "principal_id": "principal-1",
        "requested_scopes": ("support:read",),
        "now": NOW,
    }
    values.update(overrides)
    return authorize_chat_session(session(), **values)


@pytest.mark.parametrize(
    "change",
    [
        {"authenticated_at": None},
        {"consent_id": None},
        {"consent_id": None, "consented_scopes": ()},
    ],
)
def test_denies_missing_authentication_or_consent(change):
    decision = authorize_chat_session(session(**change), tenant_id="tenant-1", principal_id="principal-1", requested_scopes=("support:read",), now=NOW)
    assert not decision.allowed


def test_denies_expired_or_revoked_session():
    assert not authorize_chat_session(session(issued_at=NOW - timedelta(minutes=1), expires_at=NOW - timedelta(seconds=1)), tenant_id="tenant-1", principal_id="principal-1", requested_scopes=("support:read",), now=NOW).allowed
    assert not authorize_chat_session(session(revoked_at=NOW), tenant_id="tenant-1", principal_id="principal-1", requested_scopes=("support:read",), now=NOW).allowed


@pytest.mark.parametrize("field", ["tenant_id", "principal_id"])
def test_denies_binding_mismatch(field):
    request = {"tenant_id": "tenant-1", "principal_id": "principal-1", "requested_scopes": ("support:read",), "now": NOW}
    request[field] = "other"
    assert not authorize_chat_session(session(), **request).allowed


def test_denies_scope_outside_session_or_consent():
    assert not authorize(requested_scopes=("support:write",)).allowed
    assert not authorize(requested_scopes=("billing:read",)).allowed


def test_projects_authorized_session_to_execution_context():
    assert authorize().allowed
    context = session().to_execution_context()
    assert context.auth_kind.value == "chat_session"
    assert context.tenant_id == "tenant-1"
