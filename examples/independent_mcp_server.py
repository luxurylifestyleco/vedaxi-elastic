"""Independent MCP server. Does not import Elastic Web.

Stdio is MCP JSON-RPC 2024-11-05 over stdin/stdout.
``--http`` is one JSON-RPC POST and one JSON body on 127.0.0.1.

This is not Streamable HTTP and not SSE. A request whose Accept is only
``text/event-stream`` gets HTTP 406.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PROSPECTS = {
    "prospects": [
        {
            "name": "Ava Shah",
            "company": "Northwind Labs",
            "title": "VP Operations",
            "needs_human_approval": False,
        },
        {
            "name": "Ben Ortiz",
            "company": "Brightparcel",
            "title": "Head of Logistics",
            "needs_human_approval": True,
            "approval_reason": "existing customer",
        },
        {
            "name": "Cleo Park",
            "company": "Closed Books LLC",
            "title": "Founder",
            "needs_human_approval": True,
            "approval_reason": "no public profile",
        },
    ]
}

_TOOLS = [
    {
        "name": "find_prospects",
        "description": "Find synthetic sales prospects and prepare an outreach list. Does not contact them.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "_meta": {
            "intent_goals": ["prepare_outreach"],
            "stage": 1,
            "produces": "prospects",
            "domain": "sales",
            "permissions": ["prospects:read"],
        },
    },
    {
        "name": "echo_note",
        "description": "Echo a required note. Used to prove input validation.",
        "inputSchema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
    },
    {
        "name": "block",
        "description": "Sleep. Used to prove client timeouts. Not a product tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"seconds": {"type": "integer"}},
            "required": ["seconds"],
        },
    },
]


def handle(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id", None)
    if "id" not in req:
        return None
    params = req.get("params") or {}
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "independent-prospect-mcp", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": _TOOLS}
    elif method == "tools/call":
        result = _call(params.get("name"), params.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _call(name: str, arguments: dict) -> dict:
    if name == "find_prospects":
        return _ok(_PROSPECTS)
    if name == "echo_note":
        if "note" not in arguments:
            return _err("missing note")
        return _ok({"note": arguments["note"]})
    if name == "block":
        time.sleep(int(arguments.get("seconds") or 1))
        return _ok({"slept": True})
    return _err(f"unknown tool: {name}")


def _ok(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _err(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def serve_stdio() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        accept = self.headers.get("Accept", "")
        if "text/event-stream" in accept and "application/json" not in accept:
            body = json.dumps({
                "error": "streamable HTTP and SSE are not implemented; this server is JSON request-response only",
            }).encode("utf-8")
            self.send_response(406)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        resp = handle(req) or {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
        body = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def serve_http() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    print(f"MCP_HTTP_PORT={server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    if "--http" in sys.argv:
        serve_http()
    else:
        serve_stdio()
