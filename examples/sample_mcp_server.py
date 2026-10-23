"""Elastic Web — sample MCP server (developer onboarding).

A minimal Model Context Protocol (MCP) server that exposes a few demo-bank
capabilities as MCP tools: ``get_statement``, ``make_payment``,
``freeze_card``, ``get_balance``.

It follows the repo's existing adapter pattern
(``packages/capability-registry/mcp_adapter.py``): the :class:`MCPAdapter`
normalizes MCP-like tools into :class:`Capability` objects and invokes
their callables. This server speaks the MCP JSON-RPC protocol over stdio
(the standard MCP transport) using only the Python standard library, so it
runs with no extra dependencies.

To swap in the official ``mcp`` SDK, replace the stdio loop below with the
SDK's ``Server`` + ``FastMCP`` wiring; the tool definitions and callables
stay the same.

Run from the repo root:

    .venv/Scripts/python.exe examples/sample_mcp_server.py

Then connect any MCP client over stdio (e.g. ``npx mcp-inspector``) and
call the four tools.
"""

from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# sys.path bootstrap so the example can import the sibling packages directly.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _path in (
    _PACKAGES,
    os.path.join(_PACKAGES, "capability-registry"),
    os.path.join(_REPO_ROOT, "apps", "demo-bank"),
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from mcp_adapter import MCPAdapter  # noqa: E402
from demo_mcp_tools import get_demo_tools  # noqa: E402

# The four demo-bank capabilities exposed as MCP tools.
TOOL_NAMES = ("get_statement", "make_payment", "freeze_card", "get_balance")


def build_adapter() -> MCPAdapter:
    """Build an MCPAdapter over the demo tool registry, filtered to the
    four capabilities we want to expose."""
    tools = [t for t in get_demo_tools() if t.name in TOOL_NAMES]
    adapter = MCPAdapter(tool_registry=tools, provider="demo-bank", protocol="mcp")
    adapter.discover()
    return adapter


def handle_request(adapter: MCPAdapter, req: dict) -> dict:
    """Handle a single MCP JSON-RPC request and return a response dict."""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "elastic-web-demo-bank", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        caps = adapter.list_capabilities()
        tools = []
        for cap in caps:
            tools.append(
                {
                    "name": cap.id,
                    "description": cap.description,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            name: {"type": meta.get("type", "string")}
                            for name, meta in cap.inputs.items()
                        },
                        "required": [
                            name for name, meta in cap.inputs.items()
                            if meta.get("required")
                        ],
                    },
                }
            )
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        result = adapter.invoke(name, arguments)
        if not result.success:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": result.error or "tool failed"},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result.result, default=str)}
                ],
                "isError": False,
            },
        }

    if method == "notifications/initialized":
        return None  # notification — no response

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> None:
    adapter = build_adapter()
    print(
        f"[sample_mcp_server] serving {len(adapter)} MCP tools over stdio: "
        + ", ".join(adapter.list_capabilities()[i].id for i in range(len(adapter))),
        file=sys.stderr,
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(adapter, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
