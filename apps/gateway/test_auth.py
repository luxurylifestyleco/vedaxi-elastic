"""Focused tests for the provider-neutral gateway bearer boundary."""

from __future__ import annotations

import os
import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from datetime import datetime, timezone

from auth import BearerAuthAdapter, SupabaseAuthAdapter  # noqa: E402
from app import create_app  # noqa: E402


def test_bearer_adapter_fails_closed_without_validator():
    assert BearerAuthAdapter().authenticate({"Authorization": "Bearer token"}) is False


def test_bearer_adapter_requires_a_strict_bearer_header_and_validated_token():
    seen = []
    adapter = BearerAuthAdapter(lambda token: seen.append(token) or token == "signed-token")

    assert adapter.authenticate({"authorization": "bearer signed-token"}) is True
    assert adapter.authenticate({"Authorization": "Basic signed-token"}) is False
    assert adapter.authenticate({"Authorization": "Bearer"}) is False
    assert adapter.authenticate({"Authorization": "Bearer signed token"}) is False
    assert seen == ["signed-token"]


def test_bearer_adapter_rejects_validator_errors_and_non_boolean_results():
    assert BearerAuthAdapter(lambda _: 1).authenticate({"Authorization": "Bearer token"}) is False

    def broken(_token):
        raise RuntimeError("validator unavailable")

    assert BearerAuthAdapter(broken).authenticate({"Authorization": "Bearer token"}) is False


def test_bearer_adapter_keeps_existing_gateway_adapter_contract():
    server = create_app(
        host="0.0.0.0",
        production=True,
        trusted_auth_adapter=BearerAuthAdapter(lambda token: token == "signed-token"),
    )
    server.server_close()


def _claims(**overrides):
    now = datetime.now(timezone.utc).timestamp()
    claims = {
        "sub": "user-1",
        "tenant_id": "tenant-1",
        "iat": now - 60,
        "exp": now + 3600,
        "iss": "https://paxzgwslnhcykauymznv.supabase.co/auth/v1",
        "aud": "authenticated",
        "elastic_scopes": ["chat:send", "support:read"],
    }
    claims.update(overrides)
    return claims


def test_supabase_adapter_resolves_server_controlled_identity():
    adapter = SupabaseAuthAdapter(
        "paxzgwslnhcykauymznv",
        decoder=lambda *_args: _claims(),
    )
    principal = adapter.resolve({"Authorization": "Bearer signed-token"})
    assert principal is not None
    assert principal.principal_id == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert principal.scopes == ("chat:send", "support:read")
    assert adapter.authenticate({"Authorization": "Bearer signed-token"}) is True


def test_supabase_adapter_accepts_server_app_metadata_tenant_only():
    adapter = SupabaseAuthAdapter(
        "paxzgwslnhcykauymznv",
        decoder=lambda *_args: _claims(tenant_id=None, app_metadata={"tenant_id": "tenant-2"}),
    )
    assert adapter.resolve({"Authorization": "Bearer signed-token"}).tenant_id == "tenant-2"


def test_supabase_adapter_rejects_expired_or_unscoped_identity():
    expired = SupabaseAuthAdapter(
        "paxzgwslnhcykauymznv",
        decoder=lambda *_args: _claims(exp=1),
    )
    assert expired.resolve({"Authorization": "Bearer signed-token"}) is None
    missing_tenant = SupabaseAuthAdapter(
        "paxzgwslnhcykauymznv",
        decoder=lambda *_args: _claims(tenant_id=None, app_metadata={}),
    )
    assert missing_tenant.resolve({"Authorization": "Bearer signed-token"}) is None


def test_supabase_adapter_rejects_revoked_tokens():
    adapter = SupabaseAuthAdapter(
        "paxzgwslnhcykauymznv",
        decoder=lambda *_args: _claims(),
        revocation_check=lambda _token, _claims: False,
    )
    assert adapter.resolve({"Authorization": "Bearer signed-token"}) is None
