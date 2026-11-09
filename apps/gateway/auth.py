"""Provider-neutral authentication adapter for the gateway transport boundary."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any


_BEARER_TOKEN = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")


class BearerAuthAdapter:
    """Keep bearer parsing at the gateway and delegate trust to a validator.

    The validator must independently verify the token (for example, its
    signature, issuer, audience, expiry, and revocation state). Without one,
    this adapter rejects every request.
    """

    def __init__(self, validator: Callable[[str], bool] | None = None) -> None:
        self._validator = validator

    def authenticate(self, headers: Mapping[str, Any]) -> bool:
        token = self._token(headers)
        if token is None or not callable(self._validator):
            return False
        try:
            return self._validator(token) is True
        except Exception:  # noqa: BLE001 - authentication must fail closed.
            return False

    @staticmethod
    def _token(headers: Mapping[str, Any]) -> str | None:
        authorization = next(
            (value for name, value in headers.items() if name.casefold() == "authorization"),
            None,
        )
        if not isinstance(authorization, str):
            return None
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not _BEARER_TOKEN.fullmatch(token):
            return None
        return token


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Identity resolved from a verified Supabase Auth access token."""

    principal_id: str
    tenant_id: str
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    auth_kind: str = "SUPABASE_BEARER"
    principal_kind: str = "human"


class SupabaseAuthAdapter:
    """Verify Supabase Auth JWTs and resolve their server-controlled identity."""

    def __init__(
        self,
        project_ref: str,
        *,
        jwks_client: Any = None,
        decoder: Callable[..., Mapping[str, Any]] | None = None,
        revocation_check: Callable[[str, Mapping[str, Any]], bool] | None = None,
        algorithms: tuple[str, ...] = ("ES256", "RS256", "EdDSA"),
    ) -> None:
        if not isinstance(project_ref, str) or not project_ref.strip():
            raise ValueError("Supabase project reference is required")
        self.issuer = f"https://{project_ref}.supabase.co/auth/v1"
        self.audience = "authenticated"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._jwks_client = jwks_client
        self._decoder = decoder
        self._revocation_check = revocation_check
        self._algorithms = algorithms

    @classmethod
    def from_env(cls) -> "SupabaseAuthAdapter":
        project_ref = os.environ.get("SUPABASE_PROJECT_REF")
        if not project_ref:
            raise RuntimeError("SUPABASE_PROJECT_REF is required for Supabase authentication")
        return cls(project_ref)

    def resolve(self, headers: Mapping[str, Any]) -> AuthenticatedPrincipal | None:
        token = BearerAuthAdapter._token(headers)
        if token is None:
            return None
        try:
            claims = self._decode(token)
            if self._revocation_check is not None and not self._revocation_check(token, claims):
                return None
            principal_id = claims.get("sub")
            tenant_id = claims.get("tenant_id")
            app_metadata = claims.get("app_metadata")
            if not isinstance(tenant_id, str) and isinstance(app_metadata, Mapping):
                tenant_id = app_metadata.get("tenant_id")
            if not isinstance(principal_id, str) or not principal_id.strip():
                return None
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                return None
            issued_at = _claim_time(claims.get("iat"))
            expires_at = _claim_time(claims.get("exp"))
            if issued_at is None or expires_at is None or expires_at <= datetime.now(timezone.utc):
                return None
            raw_scopes = claims.get("elastic_scopes", claims.get("scopes", claims.get("scope", [])))
            if isinstance(raw_scopes, str):
                scopes = tuple(scope for scope in raw_scopes.split() if scope)
            elif isinstance(raw_scopes, (list, tuple)) and all(isinstance(scope, str) for scope in raw_scopes):
                scopes = tuple(scope for scope in raw_scopes if scope)
            else:
                return None
            return AuthenticatedPrincipal(principal_id, tenant_id, scopes, issued_at, expires_at)
        except Exception:  # noqa: BLE001 - authentication must fail closed.
            return None

    def authenticate(self, headers: Mapping[str, Any]) -> bool:
        return self.resolve(headers) is not None

    def _decode(self, token: str) -> Mapping[str, Any]:
        if self._decoder is not None:
            return self._decoder(
                token,
                self.issuer,
                self.audience,
                self._algorithms,
            )
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError as exc:
            raise RuntimeError("PyJWT[crypto] is required for Supabase authentication") from exc
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.jwks_url)
        signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=list(self._algorithms),
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )


def _claim_time(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)
