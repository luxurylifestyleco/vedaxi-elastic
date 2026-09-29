"""Generated protocol discovery from registry contents and enabled endpoints."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from capability import Capability

try:
    from .projection import to_a2a_skill, to_ucp_capability
except ImportError:  # source-tree imports used by this repository's tests
    from projection import to_a2a_skill, to_ucp_capability


def agent_card(
    capabilities: Iterable[Capability], base_url: str, version: str = "0.1.0"
) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    return {
        "name": "Vedaxi Elastic",
        "description": "Intent-driven access to registered Elastic capabilities.",
        "supportedInterfaces": [
            {
                "url": f"{base}/message:send",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ],
        "provider": {"organization": "Vedaxi", "url": base},
        "version": version,
        "capabilities": {"streaming": False, "pushNotifications": False},
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
        protocols["webmcp"] = [{"url": webmcp_url}]
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
    projected = []
    for capability in capabilities:
        if _is_ucp(capability):
            projected.append(to_ucp_capability(capability))
    return {"ucp": {"version": "2026-04-08"}, "url": base_url.rstrip("/"), "capabilities": projected}


def _is_ucp(capability: Capability) -> bool:
    try:
        to_ucp_capability(capability)
    except ValueError:
        return False
    return True
