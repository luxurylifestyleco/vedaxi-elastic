"""Federation adapter contracts.

Adapters move a projection across a plane boundary. They do not merge
databases. Each adapter declares version, schemas, timeout, and correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class AdapterContract:
    name: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    failure_schema: Dict[str, Any]
    timeout_ms: int
    compatibility: str
    correlation_id: str
    observability: str = "correlation_id"

    def validate(self) -> None:
        if self.timeout_ms <= 0:
            raise ValueError(f"{self.name} timeout_ms must be positive")
        if not self.correlation_id.strip():
            raise ValueError(f"{self.name} correlation_id is required")
        for label, schema in (
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
            ("failure_schema", self.failure_schema),
        ):
            if not isinstance(schema, dict) or not schema:
                raise ValueError(f"{self.name} {label} must be a non-empty object")


def _object_schema(title: str) -> Dict[str, Any]:
    return {"title": title, "type": "object"}


def standard_adapters(correlation_id: str) -> Dict[str, AdapterContract]:
    """The required adapter set. Implementations live in the owning plane."""
    names = (
        "CapabilityAdapter",
        "AuthorizationAdapter",
        "InstallationAdapter",
        "DeviceExecutionAdapter",
        "ToolExecutionAdapter",
        "SchemaAdapter",
        "PlatformCompatibilityAdapter",
    )
    out: Dict[str, AdapterContract] = {}
    for name in names:
        contract = AdapterContract(
            name=name,
            version="1.0.0",
            input_schema=_object_schema(f"{name}Input"),
            output_schema=_object_schema(f"{name}Output"),
            failure_schema={
                "title": f"{name}Failure",
                "type": "object",
                "required": ["failure", "reason"],
            },
            timeout_ms=5000,
            compatibility=">=1.0,<2.0",
            correlation_id=correlation_id,
        )
        contract.validate()
        out[name] = contract
    return out
