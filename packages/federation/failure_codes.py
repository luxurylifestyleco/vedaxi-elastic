"""Failure codes for capability negotiation.

These are not interchangeable with a generic execution error. Callers use the
code to choose retry, permission, install, alternative, or impossibility.
"""

from __future__ import annotations

from enum import Enum


class FailureCode(str, Enum):
    CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
    CAPABILITY_NOT_INSTALLED = "CAPABILITY_NOT_INSTALLED"
    CAPABILITY_DISABLED = "CAPABILITY_DISABLED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    CAPABILITY_REVOKED = "CAPABILITY_REVOKED"
    DEVICE_UNSUPPORTED = "DEVICE_UNSUPPORTED"
    OS_UNSUPPORTED = "OS_UNSUPPORTED"
    PERMISSION_MISSING = "PERMISSION_MISSING"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    PLATFORM_INCOMPATIBLE = "PLATFORM_INCOMPATIBLE"


class Recovery(str, Enum):
    RETRY = "retry"
    REQUEST_PERMISSION = "request_permission"
    INSTALL = "install"
    SELECT_ALTERNATIVE = "select_alternative"
    ASK_USER = "ask_user"
    DEGRADE = "degrade"
    REPORT_IMPOSSIBILITY = "report_impossibility"


_RECOVERY = {
    FailureCode.CAPABILITY_NOT_FOUND: Recovery.REPORT_IMPOSSIBILITY,
    FailureCode.CAPABILITY_NOT_INSTALLED: Recovery.INSTALL,
    FailureCode.CAPABILITY_DISABLED: Recovery.ASK_USER,
    FailureCode.AUTHORIZATION_REQUIRED: Recovery.REQUEST_PERMISSION,
    FailureCode.AUTHORIZATION_EXPIRED: Recovery.REQUEST_PERMISSION,
    FailureCode.CAPABILITY_REVOKED: Recovery.REPORT_IMPOSSIBILITY,
    FailureCode.DEVICE_UNSUPPORTED: Recovery.SELECT_ALTERNATIVE,
    FailureCode.OS_UNSUPPORTED: Recovery.SELECT_ALTERNATIVE,
    FailureCode.PERMISSION_MISSING: Recovery.REQUEST_PERMISSION,
    FailureCode.RUNTIME_UNAVAILABLE: Recovery.RETRY,
    FailureCode.NETWORK_UNAVAILABLE: Recovery.RETRY,
    FailureCode.TOOL_UNAVAILABLE: Recovery.SELECT_ALTERNATIVE,
    FailureCode.SCHEMA_INCOMPATIBLE: Recovery.REPORT_IMPOSSIBILITY,
    FailureCode.PLATFORM_INCOMPATIBLE: Recovery.REPORT_IMPOSSIBILITY,
}


def recovery_for(code: FailureCode) -> Recovery:
    """Map a failure code to an action. Never returns a generic error."""
    if code not in _RECOVERY:
        raise KeyError(f"unmapped failure code: {code}")
    return _RECOVERY[code]
