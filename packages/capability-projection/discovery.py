"""Generated protocol discovery from registry contents and enabled endpoints."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from capability import Capability

try:
    from .projection import UCP_VERSION, to_a2a_skill, to_ucp_capability
except ImportError:  # source-tree imports used by this repository's tests
    from projection import UCP_VERSION, to_a2a_skill, to_ucp_capability


def agent_card(
    capabilities: Iterable[Capability], base_url: str, version: str = "0.1.0"
) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    return {
        "name": "Vedaxi Elastic",
        "description": "Intent-driven access to registered Elastic capabilities.",
        "supportedInterfaces": [
            {
                "url": f"{base}/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            },
            {
                # A2A HTTP+JSON clients append the binding paths to this base.
                "url": base,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            },
        ],
        "provider": {"organization": "Vedaxi", "url": base},
        "version": version,
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [to_a2a_skill(capability) for capability in capabilities],
    }


def enabled_protocols(
    capabilities: Iterable[Capability],
    base_url: str,
    webmcp_url: Optional[str] = None,
) -> Dict[str, list[Dict[str, str]]]:
    caps = list(capabilities)
    base = base_url.rstrip("/")
    protocols: Dict[str, list[Dict[str, str]]] = {
        "mcp": [{"url": f"{base}/mcp", "transport": "streamable-http"}],
        "a2a": [{"url": f"{base}/.well-known/agent-card.json"}],
    }
    if webmcp_url:
        # This is an explicit metadata endpoint, not evidence of browser
        # registration or execution support.
        protocols["webmcp"] = [
            {
                "url": webmcp_url,
                "transport": "browser-boundary",
                "status": "metadata-only",
                "execution": "unavailable",
            }
        ]
    if any(_is_ucp(capability) for capability in caps):
        protocols["ucp"] = [{"url": f"{base}/.well-known/ucp"}]
    return protocols


def agents_json(
    capabilities: Iterable[Capability],
    base_url: str,
    webmcp_url: Optional[str] = None,
) -> Dict[str, Any]:
    caps = list(capabilities)
    return {
        "$schema": "https://agents-txt.com/schema/agents-json/v1.0.json",
        "version": "1.0",
        "standard": "https://agents-txt.com",
        "site": {
            "name": "Vedaxi Elastic",
            "url": base_url.rstrip("/"),
            "description": "Canonical Elastic capabilities exposed through enabled protocols.",
        },
        **enabled_protocols(caps, base_url, webmcp_url),
    }


def agents_txt(
    capabilities: Iterable[Capability],
    base_url: str,
    webmcp_url: Optional[str] = None,
) -> str:
    base = base_url.rstrip("/")
    protocols = enabled_protocols(capabilities, base, webmcp_url)
    lines = [
        "# agents.txt",
        "# Standard: https://agents-txt.com",
        f"# JSON: {base}/agents.json",
        "",
    ]
    labels = {"mcp": "MCP", "a2a": "A2A", "webmcp": "WebMCP", "ucp": "UCP"}
    for name in ("mcp", "a2a", "webmcp", "ucp"):
        for endpoint in protocols.get(name, []):
            lines.append(f"{labels[name]}: {endpoint['url']}")
    return "\n".join(lines) + "\n"


def ucp_profile(capabilities: Iterable[Capability], base_url: str) -> Dict[str, Any]:
    capabilities = list(capabilities)
    projected = [
        to_ucp_capability(capability)
        for capability in capabilities
        if _is_ucp(capability)
    ]
    service_endpoints = {
        str(capability.metadata["ucp_service_endpoint"]).rstrip("/")
        for capability in capabilities
        if _is_ucp(capability)
    }
    if len(service_endpoints) > 1:
        raise ValueError("UCP capabilities must share one service endpoint")
    service_endpoint = next(iter(service_endpoints), "")
    return {
        "ucp": {
            "version": UCP_VERSION,
            "services": {
                "dev.ucp.shopping": [
                    {
                        "version": UCP_VERSION,
                        "spec": f"https://ucp.dev/{UCP_VERSION}/specification/overview/",
                        "transport": "rest",
                        "endpoint": service_endpoint,
                        "schema": f"https://ucp.dev/{UCP_VERSION}/services/shopping/rest.openapi.json",
                    }
                ],
            },
            "capabilities": {
                item["name"]: [
                    {
                        "version": item["version"],
                        "spec": item["spec"],
                        "schema": item["schema"],
                    }
                ]
                for item in projected
            },
            "payment_handlers": {},
        },
        "url": base_url.rstrip("/"),
    }


def negotiate_ucp_capabilities(
    business_profile: Dict[str, Any], platform_profile: Dict[str, Any]
) -> Dict[str, Any]:
    """Return an exact-version capability intersection without network I/O."""
    business_ucp = business_profile.get("ucp")
    platform_ucp = platform_profile.get("ucp")
    if not isinstance(business_ucp, dict) or not isinstance(platform_ucp, dict):
        raise ValueError("both profiles must contain a ucp object")
    for profile in (business_ucp, platform_ucp):
        if not isinstance(profile.get("version"), str):
            raise ValueError("ucp.version is required")
        if not isinstance(profile.get("services"), dict):
            raise ValueError("ucp.services is required")
        if not isinstance(profile.get("payment_handlers"), dict):
            raise ValueError("ucp.payment_handlers is required")
    if business_ucp["version"] != platform_ucp["version"]:
        raise ValueError("no exact UCP protocol version intersection")
    business_caps = business_ucp.get("capabilities", {})
    platform_caps = platform_ucp.get("capabilities", {})
    if not isinstance(business_caps, dict) or not isinstance(platform_caps, dict):
        raise ValueError("ucp.capabilities must be an object when present")
    active: Dict[str, list[Dict[str, Any]]] = {}
    for name in sorted(set(business_caps) & set(platform_caps)):
        if not isinstance(business_caps[name], list) or not isinstance(platform_caps[name], list):
            raise ValueError(f"capability versions must be arrays: {name}")
        business_versions = {
            item.get("version") for item in business_caps[name] if isinstance(item, dict)
        }
        platform_versions = {
            item.get("version") for item in platform_caps[name] if isinstance(item, dict)
        }
        shared = sorted(
            value
            for value in business_versions & platform_versions
            if isinstance(value, str)
        )
        if shared:
            active[name] = [{"version": shared[-1]}]
    return {"ucp": {"version": business_ucp["version"], "capabilities": active}}


def _is_ucp(capability: Capability) -> bool:
    if not isinstance(capability.metadata.get("ucp_service_endpoint"), str):
        return False
    try:
        to_ucp_capability(capability)
    except ValueError:
        return False
    return True
