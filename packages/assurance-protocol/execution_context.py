"""Neutral execution context contract for public Elastic integrations.

This module carries an already-resolved authorization context across a boundary.
It does not authenticate credentials, resolve tenants, enforce RLS, or contact a
private identity system.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, model_validator


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]


class PrincipalKind(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    PROVIDER = "provider"


class AuthKind(str, Enum):
    SUPABASE_BEARER = "supabase_bearer"
    ORGANIZATION_API_KEY = "organization_api_key"
    DELEGATED = "delegated"
    CHAT_SESSION = "chat_session"


class ExecutionContext(BaseModel):
    """Immutable, tenant-agnostic context resolved by an integration adapter."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    tenant_id: Text
    principal_id: Text
    principal_kind: PrincipalKind
    auth_kind: AuthKind
    organization_id: Text
    delegation_id: Text | None = None
    policy_epoch: int
    scopes: tuple[Text, ...]
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revocation_reference: Text | None = None
    authorization_decision_id: Text

    @model_validator(mode="after")
    def fail_closed(self) -> "ExecutionContext":
        if self.tenant_id != self.organization_id:
            raise ValueError("tenant_id must match organization_id")
        if self.policy_epoch <= 0:
            raise ValueError("policy_epoch must be positive")
        if not self.scopes:
            raise ValueError("scopes must not be empty")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must follow issued_at")
        if self.expires_at <= datetime.now(timezone.utc):
            raise ValueError("execution context is expired")
        return self


class ChatSession(BaseModel):
    """Provider-neutral, authenticated and consented chat execution boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    session_id: Text
    tenant_id: Text
    principal_id: Text
    principal_kind: PrincipalKind
    authenticated_at: AwareDatetime | None = None
    consent_id: Text | None = None
    consented_scopes: tuple[Text, ...] = ()
    scopes: tuple[Text, ...]
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    policy_epoch: int = 1
    authorization_decision_id: Text

    @model_validator(mode="after")
    def validate_contract(self) -> "ChatSession":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must follow issued_at")
        if self.policy_epoch <= 0:
            raise ValueError("policy_epoch must be positive")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("revoked_at must follow issued_at")
        if self.consent_id and not set(self.scopes).issubset(self.consented_scopes):
            raise ValueError("session scopes must be covered by consent")
        return self

    def to_execution_context(self) -> ExecutionContext:
        """Project an authorized session into the existing runtime contract."""

        return ExecutionContext(
            tenant_id=self.tenant_id,
            principal_id=self.principal_id,
            principal_kind=self.principal_kind,
            auth_kind=AuthKind.CHAT_SESSION,
            organization_id=self.tenant_id,
            policy_epoch=self.policy_epoch,
            scopes=self.scopes,
            issued_at=self.issued_at,
            expires_at=self.expires_at,
            revocation_reference=self.session_id,
            authorization_decision_id=self.authorization_decision_id,
        )
