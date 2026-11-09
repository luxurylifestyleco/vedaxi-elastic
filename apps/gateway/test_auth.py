"""Focused tests for the provider-neutral gateway bearer boundary."""

from __future__ import annotations

import os
import sys

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from auth import BearerAuthAdapter  # noqa: E402
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
