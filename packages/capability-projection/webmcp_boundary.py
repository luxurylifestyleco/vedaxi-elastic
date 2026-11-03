"""Local WebMCP registration boundary.

This is a provider-neutral contract for the browser adapter. It deliberately
does not claim that ``document.modelContext`` is available; a real browser
adapter must call this boundary with the browser's trusted origin.
"""

from __future__ import annotations

from typing import Any, Callable, Dict
from urllib.parse import urlparse


def _origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("origin must be an absolute HTTP(S) URL")
    return f"{parsed.scheme}://{parsed.netloc}"


class WebMCPBoundary:
    """Register, invoke, and remove tools for one exact browser origin."""

    def __init__(self, trusted_origin: str):
        self.trusted_origin = _origin(trusted_origin)
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

    def _check_origin(self, origin: str) -> None:
        if _origin(origin) != self.trusted_origin:
            raise PermissionError("WebMCP origin is not trusted")

    def register(
        self,
        name: str,
        handler: Callable[[Dict[str, Any]], Any],
        *,
        origin: str,
    ) -> Dict[str, str]:
        self._check_origin(origin)
        if not name or not callable(handler):
            raise ValueError("tool name and callable handler are required")
        if name in self._handlers:
            raise ValueError(f"WebMCP tool already registered: {name}")
        self._handlers[name] = handler
        return {"name": name, "origin": self.trusted_origin, "status": "registered"}

    def invoke(self, name: str, arguments: Dict[str, Any], *, origin: str) -> Any:
        self._check_origin(origin)
        try:
            handler = self._handlers[name]
        except KeyError as exc:
            raise KeyError(f"WebMCP tool is not registered: {name}") from exc
        return handler(dict(arguments))

    def remove(self, name: str, *, origin: str) -> Dict[str, str]:
        self._check_origin(origin)
        if name not in self._handlers:
            raise KeyError(f"WebMCP tool is not registered: {name}")
        del self._handlers[name]
        return {"name": name, "origin": self.trusted_origin, "status": "removed"}

    def registered_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))
