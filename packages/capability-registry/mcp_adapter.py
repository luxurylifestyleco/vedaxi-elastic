"""MCP Adapter for Elastic Web (Phase 7).

The adapter bridges Model Context Protocol (MCP) tools into the Elastic Web
capability model. It:

    1. Discovers MCP tools from a local tool registry (or the MCP SDK if
       importable).
    2. Normalizes each tool into a :class:`~capability.Capability` object,
       mapping tool name -> id, description -> description, input schema ->
       inputs, etc.
    3. Invokes selected tools and records execution results.
    4. Exposes :meth:`MCPAdapter.list_capabilities` to list all discovered
       capabilities.

MCP SDK integration
-------------------
The official ``mcp`` Python SDK is *not* required. If it is importable, the
adapter can discover tools from an ``mcp.server.Server``'s registered tools
via :meth:`MCPAdapter.discover_from_mcp_sdk`. Otherwise it works against a
minimal local MCP-like interface (see :mod:`demo_mcp_tools`): a tool registry
of objects exposing ``name``, ``description``, ``input_schema``, and a
``callable``. Swapping in the real SDK is a thin change because both paths
converge on the same normalized tool dict.

The adapter never modifies MCP itself — it only reads tool metadata and
invokes tool callables.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from capability import Capability

# Default provider/protocol/domain applied to normalized capabilities.
DEFAULT_PROVIDER = "mcp"
DEFAULT_PROTOCOL = "mcp"
DEFAULT_DOMAIN = "mcp"


@dataclass
class ExecutionResult:
    """The recorded outcome of a single tool invocation.

    Attributes:
        tool_name: The name of the invoked tool.
        capability_id: The id of the capability the tool was normalized to.
        success: Whether the invocation completed without error.
        result: The value returned by the tool (or ``None`` on failure).
        error: The error message on failure (or ``None`` on success).
        duration_ms: Wall-clock duration of the invocation in milliseconds.
        timestamp: Epoch seconds when the invocation completed.
    """

    tool_name: str
    capability_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation of the result."""
        return {
            "tool_name": self.tool_name,
            "capability_id": self.capability_id,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


class MCPAdapter:
    """Discovers, normalizes, and invokes MCP tools as capabilities.

    Args:
        tool_registry: An iterable of MCP-like tool objects. Each tool must
            expose ``name``, ``description``, and ``input_schema`` attributes
            (and optionally ``output_schema`` and ``callable``). If ``None``,
            the adapter tries to import the MCP SDK and discover tools from a
            server; if that fails, it falls back to the demo tool registry.
        provider: Provider label stamped on normalized capabilities.
        protocol: Protocol label stamped on normalized capabilities.
        domain: Domain label stamped on normalized capabilities.
    """

    def __init__(
        self,
        tool_registry: Optional[Sequence[Any]] = None,
        provider: str = DEFAULT_PROVIDER,
        protocol: str = DEFAULT_PROTOCOL,
        domain: str = DEFAULT_DOMAIN,
    ) -> None:
        self.provider = provider
        self.protocol = protocol
        self.domain = domain
        self._tool_registry = tool_registry
        self._tools: Dict[str, Any] = {}
        self._capabilities: Dict[str, Capability] = {}
        self._execution_log: List[ExecutionResult] = []
        self._discovered = False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> List[Capability]:
        """Discover tools and normalize them into capabilities.

        Returns:
            The list of discovered capabilities (also cached internally).
        """
        tools = self._resolve_tools()
        self._tools = {tool.name: tool for tool in tools}
        self._capabilities = {
            tool.name: self._normalize(tool) for tool in tools
        }
        self._discovered = True
        return self.list_capabilities()

    def _resolve_tools(self) -> List[Any]:
        """Return the tool objects to discover from.

        Priority: explicit registry > MCP SDK (if importable) > demo registry.
        """
        if self._tool_registry is not None:
            return list(self._tool_registry)

        sdk_tools = self._discover_from_mcp_sdk()
        if sdk_tools is not None:
            return sdk_tools

        # Fall back to the local demo registry so the adapter works offline.
        from demo_mcp_tools import get_demo_tools

        return get_demo_tools()

    def _discover_from_mcp_sdk(self) -> Optional[List[Any]]:
        """Try to discover tools from the MCP SDK, if importable.

        Returns:
            A list of tool objects, or ``None`` if the SDK is unavailable.
        """
        try:
            import mcp  # type: ignore  # noqa: F401
        except ImportError:
            return None

        # The MCP SDK is importable but we have no live server connection
        # here. Attempt to read tools from a server's registered tool list if
        # one is provided; otherwise return None so the caller falls back to
        # the offline demo registry (an empty result is not a discovery
        # success — it would leave the adapter with zero capabilities).
        server = getattr(self, "_mcp_server", None)
        if server is None:
            return None
        tools = getattr(server, "list_tools", None)
        if callable(tools):
            return list(tools())
        return []

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, tool: Any) -> Capability:
        """Normalize a single MCP tool into a :class:`Capability`.

        Mapping:
            tool.name            -> Capability.id
            tool.description     -> Capability.description
            tool.input_schema    -> Capability.inputs
            tool.output_schema   -> Capability.outputs
            tool.name            -> Capability.name (humanized)
            tool.callable        -> Capability.endpoint (tool reference)
        """
        name = getattr(tool, "name", None) or ""
        description = getattr(tool, "description", None) or ""
        input_schema = getattr(tool, "input_schema", None) or {}
        output_schema = getattr(tool, "output_schema", None) or {}

        return Capability(
            id=name,
            name=self._humanize(name),
            description=description,
            domain=self.domain,
            inputs=self._schema_to_inputs(input_schema),
            outputs=self._schema_to_outputs(output_schema),
            provider=self.provider,
            protocol=self.protocol,
            endpoint=name,  # tool reference used to invoke
            metadata={
                "source": "mcp",
                "tool_name": name,
                "input_schema": input_schema,
                "output_schema": output_schema,
            },
        )

    @staticmethod
    def _humanize(name: str) -> str:
        """Convert a snake_case tool name into a display name."""
        return " ".join(part.capitalize() for part in name.split("_"))

    @staticmethod
    def _schema_to_inputs(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten a JSON Schema into a name -> type mapping for inputs."""
        props = schema.get("properties", {})
        required = set(schema.get("required", []) or [])
        inputs: Dict[str, Any] = {}
        for prop_name, prop in props.items():
            entry: Dict[str, Any] = {
                "type": prop.get("type", "any"),
                "required": prop_name in required,
            }
            if "description" in prop:
                entry["description"] = prop["description"]
            if "default" in prop:
                entry["default"] = prop["default"]
            if "enum" in prop:
                entry["enum"] = prop["enum"]
            inputs[prop_name] = entry
        return inputs

    @staticmethod
    def _schema_to_outputs(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten a JSON Schema into a name -> type mapping for outputs."""
        props = schema.get("properties", {})
        return {name: prop.get("type", "any") for name, prop in props.items()}

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def invoke(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Invoke a discovered tool and record the execution result.

        Args:
            tool_name: The name of the tool to invoke (its capability id).
            arguments: Keyword arguments passed to the tool callable.

        Returns:
            An :class:`ExecutionResult` recording the outcome.

        Raises:
            KeyError: If the tool has not been discovered.
        """
        if not self._discovered:
            self.discover()
        tool = self._tools.get(tool_name)
        if tool is None:
            raise KeyError(f"tool not discovered: {tool_name}")

        callable_fn = getattr(tool, "callable", None)
        if callable_fn is None:
            result = ExecutionResult(
                tool_name=tool_name,
                capability_id=tool_name,
                success=False,
                error="tool has no callable",
            )
            self._execution_log.append(result)
            return result

        start = time.perf_counter()
        try:
            value = callable_fn(**(arguments or {}))
            success = True
            error = None
        except Exception as exc:  # noqa: BLE001 - record any failure
            value = None
            success = False
            error = f"{type(exc).__name__}: {exc}"
        duration_ms = (time.perf_counter() - start) * 1000.0

        result = ExecutionResult(
            tool_name=tool_name,
            capability_id=tool_name,
            success=success,
            result=value,
            error=error,
            duration_ms=duration_ms,
        )
        self._execution_log.append(result)
        return result

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_capabilities(self) -> List[Capability]:
        """Return all discovered capabilities.

        Returns:
            A list of :class:`Capability` objects in discovery order.
        """
        return list(self._capabilities.values())

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Fetch a discovered capability by id."""
        return self._capabilities.get(capability_id)

    def execution_log(self) -> List[ExecutionResult]:
        """Return the recorded execution results, in invocation order."""
        return list(self._execution_log)

    def __len__(self) -> int:
        return len(self._capabilities)
