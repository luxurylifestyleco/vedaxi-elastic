"""Custom HTTP capability client.

This is not the WebMCP specification. WebMCP (W3C Web Machine Learning CG /
Chrome) registers tools in a browser document via ``document.modelContext``
or ``<form toolname tooldescription>``. This class talks to a private
``GET /capabilities/{id}`` and ``POST /capabilities/{id}/execute`` API.

Declarative form tools live in ``declarative.py``. Do not treat a successful
call here as WebMCP conformance.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _p in (_PACKAGES, os.path.join(_PACKAGES, "capability-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability import Capability
from mcp_adapter import ExecutionResult


class WebMCPError(Exception):
    """Raised when WebMCP communication fails."""
    pass


class WebMCPAdapter:
    """Discovers and executes WebMCP capabilities over HTTP with fallback support."""

    def __init__(
        self,
        base_url: str,
        provider: str = "webmcp-service",
        domain: str = "web",
        timeout: float = 5.0,
        fallback_fn: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.protocol = "webmcp"
        self.domain = domain
        self.timeout = timeout
        self.fallback_fn = fallback_fn

        self._capabilities: Dict[str, Capability] = {}
        self._execution_log: List[ExecutionResult] = []

    def discover_capability(self, capability_id: str) -> Optional[Capability]:
        """Discover a capability manifest from GET /capabilities/{id}."""
        url = f"{self.base_url}/capabilities/{capability_id}"
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return None

        cap_id = data.get("id", capability_id)
        cap = Capability(
            id=f"webmcp.{cap_id}",
            name=data.get("name", cap_id),
            description=data.get("description", f"WebMCP capability {cap_id}"),
            domain=data.get("domain", self.domain),
            inputs=data.get("inputs", {}),
            outputs=data.get("outputs", {}),
            permissions=data.get("permissions", ["web:access"]),
            provider=self.provider,
            protocol="webmcp",
            endpoint=f"{self.base_url}{data.get('endpoint', f'/capabilities/{cap_id}/execute')}",
            metadata={
                "source": "custom-http-capability-api",
                "specification": "custom-http-capability-api",
                "webmcp_spec": False,
                "raw_id": cap_id,
                "base_url": self.base_url,
            },
        )
        self._capabilities[cap.id] = cap
        self._capabilities[cap_id] = cap
        return cap

    def invoke(self, capability_id: str, arguments: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Invoke a WebMCP capability via POST with fallback on failure."""
        cap = self._capabilities.get(capability_id)
        raw_id = cap.metadata.get("raw_id", capability_id) if cap else capability_id
        if capability_id.startswith("webmcp."):
            raw_id = capability_id[len("webmcp."):]

        url = f"{self.base_url}/capabilities/{raw_id}/execute"
        payload = {"args": arguments or {}}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

        start = time.perf_counter()
        success = False
        result_val = None
        error_msg = None
        used_fallback = False

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                result_val = body.get("result", body)
                success = True
        except Exception as exc:
            # Check fallback
            if self.fallback_fn is not None:
                try:
                    result_val = self.fallback_fn(raw_id, arguments or {})
                    success = True
                    used_fallback = True
                except Exception as fb_exc:
                    success = False
                    error_msg = f"WebMCP failed ({exc}); fallback also failed ({fb_exc})"
            else:
                success = False
                error_msg = f"WebMCP invocation failed: {exc}"

        duration_ms = (time.perf_counter() - start) * 1000.0
        exec_res = ExecutionResult(
            tool_name=capability_id,
            capability_id=capability_id,
            success=success,
            result=result_val,
            error=error_msg,
            duration_ms=duration_ms,
        )
        self._execution_log.append(exec_res)
        return exec_res

    def list_capabilities(self) -> List[Capability]:
        return list(self._capabilities.values())
