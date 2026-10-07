"""Hot-path execution resolution.

The App Store is not a synchronous dependency. If a local projection is
present, this module must not open a network connection to resolve it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from failure_codes import FailureCode, recovery_for
from intersection import Decision, negotiate
from elastic_platform import platform_accepts

FORBIDDEN_PROJECTION_KEYS = frozenset(
    {
        "user_memories",
        "device_database",
        "crm",
        "analytics",
        "developer_records",
        "credentials",
        "execution_history",
        "provider_secrets",
    }
)


class HotPathViolation(RuntimeError):
    """Raised when execution tries to depend on the control plane."""


@dataclass
class ExecutionOutcome:
    executed: bool
    decision: Decision
    result: Any = None

    def to_dict(self) -> Dict[str, Any]:
        payload = self.decision.to_dict()
        payload["executed"] = self.executed
        if self.executed:
            payload["result"] = self.result
        return payload


def assert_projection_is_minimum(projection: Dict[str, Any]) -> None:
    present = FORBIDDEN_PROJECTION_KEYS.intersection(projection.keys())
    if present:
        raise HotPathViolation(
            "projection carries control-plane or private data: " + ", ".join(sorted(present))
        )


def execute_locally(
    capability_id: str,
    projection: Dict[str, Any],
    executor: Optional[Callable[[str, Dict[str, Any]], Any]],
    args: Optional[Dict[str, Any]] = None,
    *,
    store_client: Any = None,
) -> ExecutionOutcome:
    """Resolve and maybe execute from the local projection only.

    ``store_client`` must be None. Passing one is a contract violation, not a
    fallback. There is no code path that calls it.
    """
    if store_client is not None:
        raise HotPathViolation("app store client is not allowed on the execution path")
    assert_projection_is_minimum(projection)
    meta = str(projection.get("meta_schema_version") or "1.0")
    contract = str(projection.get("execution_contract_version") or "1.0")
    decision = negotiate(
        capability_id,
        projection,
        platform_accepts_contract=platform_accepts(meta, contract),
    )
    if not decision.executable:
        return ExecutionOutcome(executed=False, decision=decision)
    if executor is None:
        missing = Decision(
            executable=False,
            code=FailureCode.TOOL_UNAVAILABLE,
            reason="no execution adapter is registered for this capability",
            recovery=recovery_for(FailureCode.TOOL_UNAVAILABLE),
            capability_id=capability_id,
        )
        return ExecutionOutcome(executed=False, decision=missing)
    result = executor(capability_id, args or {})
    return ExecutionOutcome(executed=True, decision=decision, result=result)
