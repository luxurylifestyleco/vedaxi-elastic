"""Invocation-time Authorization & Security Guard for Elastic Web.

Enforces capability permission boundaries at invocation time for:
- Local tools (demo bank)
- Remote MCP tools
- A2A delegated agents
- WebMCP endpoints

Reuses the `permissions` field declared on Capability models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

import sys
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _p in (_PACKAGES, os.path.join(_PACKAGES, "capability-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability import Capability


class SecurityError(Exception):
    """Base exception for security and authorization failures."""
    pass


class UnauthorizedError(SecurityError):
    """Raised when authentication is required but missing or invalid."""
    pass


class CredentialsExpiredError(SecurityError):
    """Raised when the provided credentials or session token have expired."""
    pass


class PermissionDeniedError(SecurityError):
    """Raised when the caller lacks the required permissions for a capability."""
    pass


class SensitiveActionDeniedError(SecurityError):
    """Raised when a sensitive or external side-effect action lacks explicit approval."""
    pass


class UnverifiedCredentialError(SecurityError):
    """Raised when a caller presents a credential the gateway did not issue."""
    pass


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class CrudAction(str, Enum):
    """The four resource operations controlled by the gateway policy."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class PolicyDecision:
    """Typed local policy result. No model call."""
    decision: Decision
    reason: str
    policy_version: str = "phase1-local"


@dataclass
class SecurityPrincipal:
    """Represents the caller's identity and granted security claims."""
    subject: str
    granted_permissions: Set[str] = field(default_factory=set)
    token: Optional[str] = None
    expires_at: Optional[float] = None
    is_admin: bool = False
    tenant_id: Optional[str] = None

    def is_expired(self) -> bool:
        if self.expires_at is not None:
            return time.time() > self.expires_at
        return False


class AuthorizationGuard:
    """Enforces authorization checks on Capability execution."""

    def __init__(self, default_principal: Optional[SecurityPrincipal] = None) -> None:
        self.default_principal = default_principal

    def check(
        self,
        capability: Capability,
        principal: Optional[SecurityPrincipal] = None,
        explicit_approval: bool = False,
    ) -> None:
        """Verify that the caller has sufficient permissions to invoke the capability.

        Args:
            capability: The target Capability to be invoked.
            principal: The authenticated caller identity (or default_principal).
            explicit_approval: Flag indicating human/policy approval for sensitive side effects.

        Raises:
            UnauthorizedError: If capability requires permissions but no principal is provided.
            CredentialsExpiredError: If principal's token or session is expired.
            PermissionDeniedError: If principal lacks any required permission.
            SensitiveActionDeniedError: If capability is marked sensitive/external without approval.
        """
        outcome = self.decide(capability, principal=principal, explicit_approval=explicit_approval)
        if outcome.decision == Decision.ALLOW:
            return
        if outcome.reason == "expired":
            subject = (principal or self.default_principal).subject
            raise CredentialsExpiredError(f"Security token for subject '{subject}' has expired")
        if outcome.decision == Decision.REQUIRE_APPROVAL:
            raise SensitiveActionDeniedError(
                f"Capability '{capability.id}' involves sensitive side effects or external mutations. Explicit approval required."
            )
        if outcome.reason == "invalid_crud_policy":
            raise PermissionDeniedError(
                f"Capability '{capability.id}' has an invalid CRUD policy declaration"
            )
        if outcome.reason == "unauthenticated":
            raise UnauthorizedError(
                f"Capability '{capability.id}' requires authentication with permissions: {sorted(capability.permissions or [])}"
            )
        caller = principal or self.default_principal
        subject = caller.subject if caller else "anonymous"
        if outcome.reason == "cross_tenant":
            raise PermissionDeniedError(
                f"Subject '{subject}' denied invocation of '{capability.id}'. Cross-tenant resource."
            )
        raise PermissionDeniedError(
            f"Subject '{subject}' denied invocation of '{capability.id}'. Missing permissions: {sorted(set(capability.permissions or []) - (caller.granted_permissions if caller else set()))}"
        )

    def decide(
        self,
        capability: Capability,
        principal: Optional[SecurityPrincipal] = None,
        explicit_approval: bool = False,
    ) -> PolicyDecision:
        """Return ALLOW, DENY, or REQUIRE_APPROVAL. Caller text is not an input."""
        caller = principal or self.default_principal
        required = set(capability.permissions or [])
        crud_permission, crud_error = self._crud_permission(capability)
        if crud_error:
            return PolicyDecision(Decision.DENY, crud_error)
        sensitive = self._is_sensitive(capability)
        target_tenant = (capability.metadata or {}).get("tenant_id")

        if caller is None and (required or sensitive or target_tenant):
            return PolicyDecision(Decision.DENY, "unauthenticated")
        if caller is None:
            return PolicyDecision(Decision.ALLOW, "public")
        if caller.is_expired():
            return PolicyDecision(Decision.DENY, "expired")
        if target_tenant and caller.tenant_id != target_tenant:
            return PolicyDecision(Decision.DENY, "cross_tenant")
        missing = {
            permission
            for permission in required
            if not self._has_required_permission(
                permission, caller.granted_permissions, crud_permission
            )
        }
        if crud_permission and not self._has_crud_permission(
            crud_permission, caller.granted_permissions
        ):
            missing.add(crud_permission)
        if missing:
            return PolicyDecision(Decision.DENY, "missing_permission")
        # A caller boolean and a permission string are not approval evidence.
        if sensitive:
            return PolicyDecision(Decision.REQUIRE_APPROVAL, "approval_required")
        return PolicyDecision(Decision.ALLOW, "permitted")

    @staticmethod
    def _crud_permission(capability: Capability) -> tuple[Optional[str], Optional[str]]:
        """Resolve explicit CRUD metadata without trusting caller input.

        ``metadata.crud_action`` is an operator-authored policy declaration.
        The resource defaults to the first domain segment, so existing
        manifests can opt in without adding a second capability schema.
        """
        metadata = getattr(capability, "metadata", {}) or {}
        action = metadata.get("crud_action")
        if action is None:
            return None, None
        if not isinstance(action, str) or action not in {item.value for item in CrudAction}:
            return None, "invalid_crud_policy"
        resource = metadata.get("crud_resource") or str(getattr(capability, "domain", "")).split("/", 1)[0]
        if not isinstance(resource, str) or not resource.strip() or ":" in resource:
            return None, "invalid_crud_policy"
        return f"{resource.strip()}:{action}", None

    @staticmethod
    def _has_crud_permission(required: str, granted: Set[str]) -> bool:
        resource, action = required.rsplit(":", 1)
        if required in granted:
            return True
        # Compatibility for the existing resource:write vocabulary. It is
        # deliberately mutation-only; it can never grant read access.
        return action != CrudAction.READ.value and f"{resource}:write" in granted

    @staticmethod
    def _has_required_permission(
        required: str, granted: Set[str], crud_permission: Optional[str]
    ) -> bool:
        """Match ordinary grants while allowing exact CRUD migration safely.

        A trusted CRUD declaration may replace a legacy ``resource:write``
        requirement only for its own matching mutation. It never broadens a
        read grant or satisfies an unrelated permission.
        """
        if required in granted:
            return True
        if not crud_permission or not required.endswith(":write"):
            return False
        resource, action = crud_permission.rsplit(":", 1)
        return action != CrudAction.READ.value and required == f"{resource}:write" and crud_permission in granted

    @staticmethod
    def _is_sensitive(capability: Capability) -> bool:
        """Identify if capability has external side effects or high risk."""
        domain = getattr(capability, "domain", "")
        cap_id = getattr(capability, "id", "").lower()
        meta = getattr(capability, "metadata", {}) or {}

        if meta.get("sensitive") is True or meta.get("external_side_effect") is True:
            return True

        if meta.get("crud_action") == CrudAction.DELETE.value:
            return True

        # Specific high-risk financial domains/actions
        if domain in ("payments", "transfers") or "freeze" in cap_id or "delete" in cap_id or "pay" in cap_id:
            return True

        return False
