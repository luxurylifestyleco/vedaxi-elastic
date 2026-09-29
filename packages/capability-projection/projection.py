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
    """Project serializable WebMCP metadata; the browser supplies execute()."""
    tool = to_mcp_tool(capability)
    tool["capabilityId"] = capability.id
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


_UCP_OPERATIONS = {
    "product_search": "dev.ucp.shopping.catalog.search",
    "catalog.search": "dev.ucp.shopping.catalog.search",
    "cart": "dev.ucp.shopping.cart",
    "checkout": "dev.ucp.shopping.checkout",
    "fulfillment": "dev.ucp.shopping.fulfillment",
    "order": "dev.ucp.shopping.order",
    "returns": "dev.ucp.shopping.order",
    "return": "dev.ucp.shopping.order",
}


def to_ucp_capability(capability: Capability) -> Dict[str, Any]:
    """Project explicitly tagged commerce capabilities into UCP operations."""
    operation = capability.metadata.get("commerce_operation")
    if capability.domain != "commerce" or operation not in _UCP_OPERATIONS:
        raise ValueError(f"capability is not eligible for UCP: {capability.id}")
    consequential = operation in {"checkout", "order", "returns", "return"}
    return {
        "name": _UCP_OPERATIONS[operation],
        "version": capability.metadata.get("ucp_version", "2026-04-08"),
        "operation": operation,
        "description": capability.description,
        "inputSchema": _schema(capability.inputs),
        "outputSchema": _output_schema(capability),
        "endpoint": capability.endpoint,
        "requiresHumanConfirmation": consequential,
        "metadata": {
            "elasticCapabilityId": capability.id,
            "provider": capability.provider,
            "permissions": capability.permissions,
        },
    }
