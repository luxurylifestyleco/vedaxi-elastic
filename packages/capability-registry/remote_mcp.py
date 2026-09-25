"""Explicit-trust Streamable HTTP client for remote MCP servers."""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlsplit
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

MCP_PROTOCOL_VERSION = "2025-06-18"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
Transport = Callable[
    [Dict[str, Any], Dict[str, str]],
    Tuple[Optional[Dict[str, Any]], Mapping[str, str]],
]


class RemoteMCPClient:
    """Minimal MCP client. Remote endpoints must be explicitly trusted."""

    def __init__(
        self,
        endpoint: str,
        *,
        trusted: bool = False,
        headers: Optional[Mapping[str, str]] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("remote MCP endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("remote MCP endpoint cannot contain credentials or a fragment")
        if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
            raise ValueError("remote MCP endpoint must use HTTPS (localhost may use HTTP)")
        self.endpoint = endpoint
        self.trusted = trusted
        self.headers = dict(headers or {})
        self._transport = transport or self._http_transport
        self._session_id: Optional[str] = None
        self._connected = False
        self._request_id = 0

    def connect(self) -> None:
        self._require_trust()
        if self._connected:
            return
        result = self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "vedaxi-elastic", "version": "0.1.0"},
            },
            connect=False,
        )
        if "protocolVersion" not in result:
            raise RuntimeError("remote MCP server returned an invalid initialize result")
        self._transport(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            self._request_headers(),
        )
        self._connected = True

    def list_tools(self) -> List[Dict[str, Any]]:
        self.connect()
        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            page = result.get("tools")
            if not isinstance(page, list):
                raise RuntimeError("remote MCP tools/list returned no tools array")
            tools.extend(tool for tool in page if isinstance(tool, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        self.connect()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"remote MCP tool failed: {result.get('content')!r}")
        return result.get("structuredContent", result.get("content"))

    def _require_trust(self) -> None:
        if not self.trusted:
            raise PermissionError("remote MCP server is not trusted")

    def _request(
        self, method: str, params: Dict[str, Any], *, connect: bool = True
    ) -> Dict[str, Any]:
        if connect and not self._connected:
            self.connect()
        self._request_id += 1
        response, headers = self._transport(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            },
            self._request_headers(),
        )
        self._session_id = headers.get("Mcp-Session-Id", self._session_id)
        if not isinstance(response, dict):
            raise RuntimeError(f"remote MCP {method} returned no response")
        if "error" in response:
            raise RuntimeError(f"remote MCP {method} failed: {response['error']!r}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"remote MCP {method} returned an invalid result")
        return result

    def _request_headers(self) -> Dict[str, str]:
        result = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            **self.headers,
        }
        if self._session_id:
            result["Mcp-Session-Id"] = self._session_id
        return result

    def _http_transport(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[Optional[Dict[str, Any]], Mapping[str, str]]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.build_opener(_NoRedirects()).open(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return None, response.headers
            if response.headers.get_content_type() == "text/event-stream":
                raw = "\n".join(
                    line[5:].strip()
                    for line in raw.splitlines()
                    if line.startswith("data:")
                )
            return json.loads(raw), response.headers


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"remote MCP redirect refused: {newurl}")
