"""Formal invariant: a capability is executable only at the intersection.

PLATFORM ∩ ECOSYSTEM ∩ INSTALLATION ∩ DEVICE ∩ CURRENT_RUNTIME

Missing any factor is a specific failure, not a generic error. This module
does not own device state, user memory, or the ecosystem registry. It evaluates
a projection it was given.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from failure_codes import FailureCode, Recovery, recovery_for


@dataclass
class Decision:
    executable: bool
    code: Optional[FailureCode] = None
    reason: str = ""
    alternative: Optional[str] = None
    recovery: Optional[Recovery] = None
    capability_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executable": self.executable,
            "capability_id": self.capability_id,
            "failure": None if self.code is None else self.code.value,
            "reason": self.reason,
            "alternative": self.alternative,
            "recovery": None if self.recovery is None else self.recovery.value,
        }


def _fail(
    capability_id: str,
    code: FailureCode,
    reason: str,
    alternative: Optional[str] = None,
) -> Decision:
    return Decision(
        executable=False,
        code=code,
        reason=reason,
        alternative=alternative,
        recovery=recovery_for(code) if alternative is None else Recovery.SELECT_ALTERNATIVE,
        capability_id=capability_id,
    )


def _states(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw = entry.get("states")
    return raw if isinstance(raw, dict) else {}


def negotiate(
    capability_id: str,
    projection: Dict[str, Any],
    *,
    platform_accepts_contract: bool,
    allow_alternative: bool = True,
) -> Decision:
    """Evaluate intersection for one capability. Does not call a store."""
    if not isinstance(projection, dict):
        return _fail(capability_id, FailureCode.SCHEMA_INCOMPATIBLE, "projection must be an object")
    if not platform_accepts_contract:
        return _fail(
            capability_id,
            FailureCode.PLATFORM_INCOMPATIBLE,
            "Elastic Web platform does not accept this meta-schema or execution contract",
        )

    entries = projection.get("entries")
    if not isinstance(entries, list):
        return _fail(capability_id, FailureCode.SCHEMA_INCOMPATIBLE, "projection.entries must be a list")

    by_id: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("capability_id"), str):
            by_id[entry["capability_id"]] = entry

    entry = by_id.get(capability_id)
    if entry is None:
        return _fail(
            capability_id,
            FailureCode.CAPABILITY_NOT_FOUND,
            "capability is not in the local projection",
        )

    states = _states(entry)
    if states.get("EXISTS") is not True and entry.get("ecosystem_attested") is not True:
        return _fail(
            capability_id,
            FailureCode.CAPABILITY_NOT_FOUND,
            "capability is not attested in the ecosystem projection",
        )
    if states.get("INSTALLED") is not True:
        return _fail(
            capability_id,
            FailureCode.CAPABILITY_NOT_INSTALLED,
            "capability is not installed on this device",
        )
    if states.get("ENABLED") is not True:
        return _fail(capability_id, FailureCode.CAPABILITY_DISABLED, "capability is installed but disabled")
    if entry.get("revoked") is True or states.get("AUTHORIZED") == "revoked":
        return _fail(capability_id, FailureCode.CAPABILITY_REVOKED, "capability authorization was revoked")
    if states.get("AUTHORIZED") == "expired":
        return _fail(capability_id, FailureCode.AUTHORIZATION_EXPIRED, "authorization expired")
    if states.get("AUTHORIZED") is not True:
        return _fail(capability_id, FailureCode.AUTHORIZATION_REQUIRED, "capability is not authorized")
    if states.get("SUPPORTED") is not True:
        reason = entry.get("unsupported_reason") or "device or OS cannot execute this capability"
        code = (
            FailureCode.OS_UNSUPPORTED
            if entry.get("os_unsupported") is True
            else FailureCode.DEVICE_UNSUPPORTED
        )
        alternative = _alternative(capability_id, by_id) if allow_alternative else None
        return _fail(capability_id, code, reason, alternative)
    runtime = projection.get("runtime") if isinstance(projection.get("runtime"), dict) else {}
    if runtime.get("network") is False and entry.get("requires_network") is True:
        return _fail(
            capability_id,
            FailureCode.NETWORK_UNAVAILABLE,
            "network is required and unavailable",
        )
    missing = entry.get("missing_permissions") or []
    if missing:
        return _fail(
            capability_id,
            FailureCode.PERMISSION_MISSING,
            "missing permissions: " + ", ".join(str(item) for item in missing),
        )
    if states.get("AVAILABLE") is not True or runtime.get("execution_state") == "restricted":
        return _fail(
            capability_id,
            FailureCode.RUNTIME_UNAVAILABLE,
            "runtime cannot execute this capability now",
        )
    if states.get("EXECUTABLE") is not True:
        return _fail(
            capability_id,
            FailureCode.RUNTIME_UNAVAILABLE,
            "capability is not executable in the current runtime",
        )
    return Decision(executable=True, capability_id=capability_id, reason="intersection holds")


def _alternative(capability_id: str, by_id: Dict[str, Dict[str, Any]]) -> Optional[str]:
    family = capability_id.split(".")[0]
    for other_id, entry in by_id.items():
        if other_id == capability_id or not other_id.startswith(family + "."):
            continue
        states = _states(entry)
        if (
            states.get("INSTALLED")
            and states.get("ENABLED")
            and states.get("AUTHORIZED") is True
            and states.get("SUPPORTED")
            and states.get("AVAILABLE")
            and states.get("EXECUTABLE")
        ):
            return other_id
    return None
