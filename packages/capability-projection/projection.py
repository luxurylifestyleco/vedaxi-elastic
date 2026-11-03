"""Pure projections from the canonical Elastic Capability model."""

from __future__ import annotations

from typing import Any, Callable, Dict

from capability import Capability


def project(capability: Capability, adapter: Callable[[Capability], Any]) -> Any:
    """Apply a protocol adapter without teaching core packages about it."""
    return adapter(capability)


def _schema(fields: Dict[str, Any], raw: Any = None) -> Dict[str, Any]:
    if isinstance(raw, dict) and raw.get("type") == "object":
        return raw
    properties: Dict[str, Any] = {}
    required = []
    for name, value in fields.items():
        if isinstance(value, str):
            properties[name] = {"type": value}
            required.append(name)
            continue
        item = dict(value) if isinstance(value, dict) else {"type": "object"}
        is_required = item.pop("required", True)
        properties[name] = item
        if is_required:
            required.append(name)
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _output_schema(capability: Capability) -> Dict[str, Any]:
    return _schema(capability.outputs, capability.metadata.get("output_schema"))


def to_mcp_tool(capability: Capability) -> Dict[str, Any]:
    """Project an Elastic Capability into an MCP tool descriptor."""
    writable = any(permission.endswith(":write") for permission in capability.permissions)
    return {
        "name": capability.id,
        "title": capability.name,
        "description": capability.description,
        "inputSchema": _schema(
            capability.inputs, capability.metadata.get("input_schema")
        ),
        "outputSchema": _output_schema(capability),
        "annotations": {"readOnlyHint": not writable},
        "_meta": {
            "elastic": {
                "provider": capability.provider,
                "protocol": capability.protocol,
                "endpoint": capability.endpoint,
                "permissions": capability.permissions,
                "provenance": capability.metadata.get("provenance")
                or capability.metadata.get("source"),
            }
        },
    }


def to_webmcp_tool(capability: Capability) -> Dict[str, Any]:
    """Project a fail-closed WebMCP browser-boundary descriptor.

    This repository does not provide a browser runtime or ``document.modelContext``
    bridge.  The descriptor is therefore metadata only and must not be treated as
    proof that registration or execution is available.
    """
    tool = to_mcp_tool(capability)
    tool["capabilityId"] = capability.id
    tool["webmcp"] = {
        "api": "document.modelContext",
        "registration": "metadata-only",
        "execution": "unavailable",
        "failClosed": True,
    }
    return tool


def to_a2a_skill(capability: Capability) -> Dict[str, Any]:
    """Project an Elastic Capability into an A2A AgentSkill."""
    tags = capability.metadata.get("tags") or [capability.domain, capability.protocol]
    return {
        "id": capability.id,
        "name": capability.name,
        "description": capability.description,
        "tags": list(dict.fromkeys(str(tag) for tag in tags)),
        "inputModes": ["application/json", "text/plain"],
        "outputModes": ["application/json"],
    }


UCP_VERSION = "2026-08-25"

# Only operations with an implemented, read-only Elastic execution path are
# eligible today. Cart, checkout, payment, fulfillment, order, and returns
# remain fail-closed until their end-to-end contracts exist.
_UCP_OPERATIONS = {
    "product_search": "dev.ucp.shopping.catalog.search",
    "catalog.search": "dev.ucp.shopping.catalog.search",
    "catalog.lookup": "dev.ucp.shopping.catalog.lookup",
}

_UCP_OPERATION_PATHS = {
    "dev.ucp.shopping.catalog.search": "search",
    "dev.ucp.shopping.catalog.lookup": "lookup",
}

_UCP_OPERATION_SPECS = {
    "dev.ucp.shopping.catalog.search": "shopping/catalog/search",
    "dev.ucp.shopping.catalog.lookup": "shopping/catalog/lookup",
}


def to_ucp_capability(capability: Capability) -> Dict[str, Any]:
    """Project an explicitly enabled, implemented capability into UCP."""
    operation = capability.metadata.get("commerce_operation")
    if (
        capability.domain != "commerce"
        or capability.metadata.get("ucp_enabled") is not True
        or operation not in _UCP_OPERATIONS
    ):
        raise ValueError(f"capability is not eligible for UCP: {capability.id}")
    name = _UCP_OPERATIONS[operation]
    version = capability.metadata.get("ucp_version", UCP_VERSION)
    spec_path = _UCP_OPERATION_SPECS[name]
    schema_name = "catalog_search" if name.endswith(".search") else "catalog_lookup"
    return {
        "name": name,
        "version": version,
        "spec": capability.metadata.get(
            "ucp_spec", f"https://ucp.dev/{version}/specification/{spec_path}"
        ),
        "schema": capability.metadata.get(
            "ucp_schema", f"https://ucp.dev/{version}/schemas/shopping/{schema_name}.json"
        ),
        "operation": operation,
        "description": capability.description,
        "inputSchema": _schema(capability.inputs),
        "outputSchema": _output_schema(capability),
        "endpoint": capability.endpoint,
        "metadata": {
            "elasticCapabilityId": capability.id,
            "provider": capability.provider,
            "permissions": capability.permissions,
            "transportOperation": _UCP_OPERATION_PATHS[name],
        },
    }
