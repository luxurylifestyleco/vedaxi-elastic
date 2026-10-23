"""Remote Model Context Protocol (MCP) Adapter for Elastic Web.

Extends Elastic Web's capability layer to connect with remote MCP servers over:
1. Stdio transport (JSON-RPC 2.0 over stdin/stdout of a subprocess)
2. HTTP request-response (one JSON-RPC POST, one JSON body)

Streamable HTTP (MCP 2025-03-26) and SSE are not implemented. An HTTP
server that only speaks ``text/event-stream`` will fail this client.

Reuses the existing Capability and ExecutionResult contracts from capability-registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence
import urllib.request
import urllib.error

# Ensure sibling packages are importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _p in (_PACKAGES, os.path.join(_PACKAGES, "capability-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability import Capability
from mcp_adapter import ExecutionResult


class RemoteMCPError(Exception):
    """Raised when an MCP communication or protocol error occurs."""
    pass


class RemoteMCPTimeoutError(RemoteMCPError):
    """Raised when an MCP operation times out."""
    pass


class RemoteMCPAdapter:
    """Connects to a remote MCP server via Stdio or HTTP, discovers tools as Capabilities,
    and invokes them with strict timeout and lifecycle management.
    """

    def __init__(
        self,
        command: Optional[Sequence[str]] = None,
        url: Optional[str] = None,
        provider: str = "remote-mcp",
        domain: str = "mcp",
        timeout: float = 5.0,
        env: Optional[Dict[str, str]] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        if not command and not url:
            raise ValueError("Must provide either a stdio command or an HTTP url")
        self.command = list(command) if command else None
        self.url = url
        self.provider = provider
        self.protocol = "mcp"
        self.domain = domain
        self.timeout = timeout
        self.env = env
        self._auth_token = auth_token  # Kept private, never emitted in logs

        self._process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()
        self._req_id = 0
        self._capabilities: Dict[str, Capability] = {}
        self._tools_raw: Dict[str, Dict[str, Any]] = {}
        self._execution_log: List[ExecutionResult] = []
        self._discovered = False
        self._http_initialized = False

    def __enter__(self) -> RemoteMCPAdapter:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def connect(self) -> None:
        """Initialize the transport connection."""
        if self.command and self._process is None:
            proc_env = os.environ.copy()
            if self.env:
                proc_env.update(self.env)
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=proc_env,
            )
            # Perform MCP initialization handshake
            self._rpc_call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "elastic-web-remote-mcp", "version": "0.1.0"},
            })
            self._rpc_notify("notifications/initialized", {})

    def close(self) -> None:
        """Clean up process and resources."""
        with self._process_lock:
            if self._process is not None:
                try:
                    if self._process.stdin:
                        self._process.stdin.close()
                    self._process.terminate()
                    self._process.wait(timeout=1.0)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                finally:
                    self._process = None

    # ------------------------------------------------------------------
    # JSON-RPC Low-level Transport
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _rpc_notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        if self._process:
            line = json.dumps(payload) + "\n"
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except Exception as e:
                raise RemoteMCPError(f"Failed to send notification: {e}") from e

    def _rpc_call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        if self.url:
            return self._http_call(payload)
        elif self.command:
            return self._stdio_call(payload)
        else:
            raise RemoteMCPError("No active transport configured")

    def _http_call(self, payload: Dict[str, Any]) -> Any:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        req = urllib.request.Request(self.url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                res = json.loads(raw)
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", "replace")
            raise RemoteMCPError(f"HTTP {e.code}: {raw_err}") from e
        except Exception as e:
            raise RemoteMCPError(f"HTTP request failed: {e}") from e

        if "error" in res:
            err = res["error"]
            msg = err.get("message", "Unknown RPC error")
            raise RemoteMCPError(f"RPC error ({err.get('code')}): {msg}")
        return res.get("result")

    def _stdio_call(self, payload: Dict[str, Any]) -> Any:
        if self._process is None:
            self.connect()

        with self._process_lock:
            if not self._process or self._process.poll() is not None:
                raise RemoteMCPError("Remote MCP process is not running")

            line = json.dumps(payload) + "\n"
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except Exception as e:
                raise RemoteMCPError(f"Failed writing to MCP stdin: {e}") from e

            # Read response with timeout
            resp_line: Optional[str] = None
            err_box: List[Exception] = []

            def reader():
                nonlocal resp_line
                try:
                    assert self._process is not None and self._process.stdout is not None
                    resp_line = self._process.stdout.readline()
                except Exception as ex:
                    err_box.append(ex)

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t.join(timeout=self.timeout)

            if t.is_alive():
                raise RemoteMCPTimeoutError(f"MCP call timed out after {self.timeout}s")
            if err_box:
                raise RemoteMCPError(f"Error reading MCP response: {err_box[0]}")
            if not resp_line:
                stderr_out = ""
                if self._process.stderr:
                    try:
                        stderr_out = self._process.stderr.read()[:500]
                    except Exception:
                        pass
                raise RemoteMCPError(f"Remote MCP process closed stdout unexpectedly. Stderr: {stderr_out}")

            try:
                res = json.loads(resp_line.strip())
            except Exception as e:
                raise RemoteMCPError(f"Invalid JSON from MCP server: {resp_line}") from e

            if "error" in res:
                err = res["error"]
                msg = err.get("message", "Unknown RPC error")
                raise RemoteMCPError(f"RPC error ({err.get('code')}): {msg}")
            return res.get("result")

    # ------------------------------------------------------------------
    # Capability Discovery & Normalization
    # ------------------------------------------------------------------

    def discover(self) -> List[Capability]:
        """Query remote MCP server for tools and normalize to Capabilities."""
        if self.command and self._process is None:
            self.connect()
        if self.url and not self._http_initialized:
            self._rpc_call("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "elastic-web-remote-mcp", "version": "0.1.0"},
            })
            self._http_initialized = True

        result = self._rpc_call("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []

        self._capabilities.clear()
        self._tools_raw.clear()

        for t in tools:
            name = t.get("name", "")
            description = t.get("description", "")
            input_schema = t.get("inputSchema", {})

            meta = t.get("_meta") if isinstance(t.get("_meta"), dict) else {}
            permissions = meta.get("permissions") if isinstance(meta.get("permissions"), list) else []
            cap = Capability(
                id=name,
                name=" ".join(w.capitalize() for w in name.split("_")),
                description=description,
                domain=str(meta.get("domain") or self.domain),
                inputs=self._schema_to_inputs(input_schema),
                outputs={"content": "array"},
                permissions=permissions,
                provider=self.provider,
                protocol="mcp",
                endpoint=name,
                metadata={
                    **{k: v for k, v in meta.items() if k != "permissions"},
                    "source": "remote_mcp",
                    "transport": "http-request-response" if self.url else "stdio",
                    "streamable_http": False,
                    "sse": False,
                    "tool_name": name,
                    "input_schema": input_schema,
                },
            )
            self._capabilities[name] = cap
            self._tools_raw[name] = t

        self._discovered = True
        return list(self._capabilities.values())

    @staticmethod
    def _schema_to_inputs(schema: Dict[str, Any]) -> Dict[str, Any]:
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
            inputs[prop_name] = entry
        return inputs

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def invoke(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Invoke a tool on the remote MCP server and normalize ExecutionResult."""
        if not self._discovered:
            self.discover()

        if tool_name not in self._capabilities:
            raise KeyError(f"Remote tool '{tool_name}' not found")

        schema = (self._tools_raw.get(tool_name) or {}).get("inputSchema") or {}
        try:
            _validate_inputs(schema, arguments or {})
        except RemoteMCPError as exc:
            res = ExecutionResult(
                tool_name=tool_name,
                capability_id=tool_name,
                success=False,
                result=None,
                error=str(exc),
                duration_ms=0.0,
            )
            self._execution_log.append(res)
            return res

        start = time.perf_counter()
        success = False
        value = None
        error_msg = None

        try:
            params = {
                "name": tool_name,
                "arguments": arguments or {},
            }
            rpc_res = self._rpc_call("tools/call", params)

            # Standard MCP tools/call returns {"content": [...], "isError": bool}
            if isinstance(rpc_res, dict):
                is_error = rpc_res.get("isError", False)
                content = rpc_res.get("content", [])
                text_chunks = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_chunks.append(item.get("text", ""))

                combined_text = "\n".join(text_chunks)
                # Try JSON parse if structured
                try:
                    parsed_val = json.loads(combined_text)
                except Exception:
                    parsed_val = combined_text

                if is_error:
                    success = False
                    error_msg = combined_text or "Tool reported error"
                else:
                    success = True
                    value = parsed_val
            else:
                success = True
                value = rpc_res

        except Exception as exc:
            success = False
            error_msg = f"{type(exc).__name__}: {exc}"

        duration_ms = (time.perf_counter() - start) * 1000.0

        res = ExecutionResult(
            tool_name=tool_name,
            capability_id=tool_name,
            success=success,
            result=value,
            error=error_msg,
            duration_ms=duration_ms,
        )
        self._execution_log.append(res)
        return res

    def list_capabilities(self) -> List[Capability]:
        return list(self._capabilities.values())

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        return self._capabilities.get(capability_id)


def _validate_inputs(schema: Dict[str, Any], arguments: Dict[str, Any]) -> None:
    """Reject calls that miss required fields or disagree with declared JSON types."""
    props = schema.get("properties") or {}
    missing = [name for name in (schema.get("required") or []) if name not in arguments]
    if missing:
        raise RemoteMCPError(f"input validation failed: missing {missing}")
    type_ok = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
    }
    for name, value in arguments.items():
        expected = (props.get(name) or {}).get("type")
        check = type_ok.get(expected)
        if check is not None and not check(value):
            raise RemoteMCPError(
                f"input validation failed: {name} must be {expected}"
            )
