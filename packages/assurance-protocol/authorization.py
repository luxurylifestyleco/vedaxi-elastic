"""Local authorization and delegation enforcement for runtime adapters.

This guard consumes already-authenticated contracts.  It does not authenticate
credentials, resolve tenants, contact an identity provider, or persist a
decision.  Missing or inconsistent authority is denied rather than inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

try:  # Supports package imports and the repository's direct test imports.
    from .execution_context import AuthKind, ExecutionContext
    from .outcome import Delegation
except ImportError:  # pragma: no cover - exercised by direct pytest collection
    from execution_context import AuthKind, ExecutionContext
    from outcome import Delegation


class AuthorizationDenied(ValueError):
    """Raised when the supplied runtime authority cannot authorize an action."""


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    authorization_decision_id: str
    delegation_id: str | None = None


def authorize(
    context: ExecutionContext,
    *,
    capability: str,
    resource: str,
    delegation_chain: Sequence[Delegation] = (),
    now: datetime | None = None,
) -> AuthorizationDecision:
    """Authorize one runtime action, failing closed on every mismatch.

    ``delegation_chain`` is ordered from the original delegator to the
    effective delegatee.  Delegated contexts require a complete chain whose
    leaf matches the context principal and delegation ID.  Each child may only
    retain capabilities/resources granted by its parent.
    """

    moment = now or datetime.now(timezone.utc)
    _require_non_empty("capability", capability)
    _require_non_empty("resource", resource)

    if moment < context.issued_at or moment >= context.expires_at:
        return _deny(context, "execution context is outside its validity window")
    if context.auth_kind is AuthKind.DELEGATED:
        if not delegation_chain:
            return _deny(context, "delegated authorization requires a delegation chain")
        leaf = delegation_chain[-1]
        if context.delegation_id != leaf.delegation_id:
            return _deny(context, "execution context delegation does not match the chain leaf")
        if leaf.delegatee_id != context.principal_id:
            return _deny(context, "delegation delegatee does not match the execution principal")
        if not _chain_is_valid(delegation_chain, capability, resource, moment):
            return _deny(context, "delegation chain does not authorize the requested action")
    elif delegation_chain or context.delegation_id is not None:
        return _deny(context, "non-delegated authorization cannot carry delegation state")
    elif capability not in context.scopes:
        return _deny(context, "execution context scope does not authorize the capability")

    return AuthorizationDecision(
        allowed=True,
        reason="authorization granted",
        authorization_decision_id=context.authorization_decision_id,
        delegation_id=context.delegation_id,
    )


def require_authorized(
    context: ExecutionContext,
    *,
    capability: str,
    resource: str,
    delegation_chain: Sequence[Delegation] = (),
    now: datetime | None = None,
) -> AuthorizationDecision:
    """Return the allow decision or raise ``AuthorizationDenied``."""

    decision = authorize(
        context,
        capability=capability,
        resource=resource,
        delegation_chain=delegation_chain,
        now=now,
    )
    if not decision.allowed:
        raise AuthorizationDenied(decision.reason)
    return decision


def _chain_is_valid(
    chain: Sequence[Delegation], capability: str, resource: str, now: datetime
) -> bool:
    for index, delegation in enumerate(chain):
        if now < delegation.issued_at or now >= delegation.expires_at:
            return False
        if delegation.revoked_at is not None and now >= delegation.revoked_at:
            return False
        if capability not in delegation.capabilities or resource not in delegation.resource_scopes:
            return False
        if index and (
            chain[index - 1].delegation_id != delegation.parent_delegation_id
            or chain[index - 1].delegatee_id != delegation.delegator_id
            or not chain[index - 1].further_delegation_allowed
            or not set(delegation.capabilities).issubset(chain[index - 1].capabilities)
            or not set(delegation.resource_scopes).issubset(chain[index - 1].resource_scopes)
        ):
            return False
    return True


def _deny(context: ExecutionContext, reason: str) -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=False,
        reason=reason,
        authorization_decision_id=context.authorization_decision_id,
        delegation_id=context.delegation_id,
    )


def _require_non_empty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AuthorizationDenied(f"{name} is required")
