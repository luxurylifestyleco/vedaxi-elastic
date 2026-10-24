"""Browser-document WebMCP client (Chrome CDP).

This is the W3C/Chrome WebMCP surface: tools the document exposes via
``document.modelContext.registerTool`` and ``<form toolname tooldescription>``.
It is not the private HTTP client in ``webmcp_adapter.py`` and not HTML scraping.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _p in (_PACKAGES, os.path.join(_PACKAGES, "capability-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability import Capability
from mcp_adapter import ExecutionResult

_CHROME_DEFAULT = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class BrowserWebMCPError(Exception):
    """Raised when Chrome or the WebMCP CDP domain fails."""


class BrowserWebMCPClient:
    """Launch headed Chrome, discover document tools over CDP, invoke them."""

    def __init__(
        self,
        page_url: str,
        chrome_path: Optional[str] = None,
        timeout: float = 30.0,
        provider: str = "webmcp-browser",
    ) -> None:
        self.page_url = page_url
        self.chrome_path = chrome_path or os.environ.get("CHROME_PATH") or _CHROME_DEFAULT
        self.timeout = timeout
        self.provider = provider
        self._proc: Optional[subprocess.Popen] = None
        self._user_data_dir: Optional[str] = None
        self._cdp: Optional[_Cdp] = None
        self._capabilities: Dict[str, Capability] = {}
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def discover(self) -> List[Capability]:
        self._ensure_browser()
        deadline = time.time() + self.timeout
        self._cdp.send("Page.enable")
        self._cdp.send("Page.navigate", {"url": self.page_url})
        self._cdp.wait_event("Page.loadEventFired", deadline)
        try:
            self._cdp.send("WebMCP.enable")
        except Exception as exc:
            raise BrowserWebMCPError(f"WebMCP.enable failed: {exc}") from exc
        self._wait_for_tools(deadline)
        if not self._capabilities:
            raise BrowserWebMCPError("WebMCP.enable succeeded but no tools arrived via toolsAdded")
        return list(self._capabilities.values())

    def invoke(self, capability_id: str, arguments: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        cap, tool = self._lookup(capability_id)
        start = time.perf_counter()
        try:
            result_body = self._cdp.send(
                "WebMCP.invokeTool",
                {
                    "frameId": tool["frameId"],
                    "toolName": tool["name"],
                    "input": arguments or {},
                },
            )
            invocation_id = result_body["invocationId"]
            ev = self._cdp.wait_event(
                "WebMCP.toolResponded",
                time.time() + self.timeout,
                match=lambda p: p.get("invocationId") == invocation_id,
            )
            status = ev.get("status")
            output = ev.get("output")
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    pass
            if status != "Completed":
                return ExecutionResult(
                    tool_name=cap.id,
                    capability_id=cap.id,
                    success=False,
                    result=output,
                    error=ev.get("errorText") or f"WebMCP invocation status={status}",
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )
            return ExecutionResult(
                tool_name=cap.id,
                capability_id=cap.id,
                success=True,
                result=output,
                error=None,
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:
            return ExecutionResult(
                tool_name=cap.id,
                capability_id=cap.id,
                success=False,
                result=None,
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )

    def close(self) -> None:
        cdp, proc, user_dir = self._cdp, self._proc, self._user_data_dir
        self._cdp = None
        self._proc = None
        self._user_data_dir = None
        if cdp is not None:
            try:
                cdp.send("Browser.close", timeout=2.0)
            except Exception:
                pass
            cdp.close()
        _kill_chrome(proc)
        if user_dir and os.path.isdir(user_dir):
            shutil.rmtree(user_dir, ignore_errors=True)

    def list_capabilities(self) -> List[Capability]:
        return list(self._capabilities.values())

    def __enter__(self) -> "BrowserWebMCPClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_browser(self) -> None:
        if self._cdp is not None:
            return
        if not os.path.isfile(self.chrome_path):
            raise BrowserWebMCPError(f"Chrome not found: {self.chrome_path}")
        self._user_data_dir = tempfile.mkdtemp(prefix="elastic-webmcp-")
        args = [
            self.chrome_path,
            f"--user-data-dir={self._user_data_dir}",
            "--enable-features=WebMCP,WebMCPTesting",
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "about:blank",
        ]
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            port, ws_path = _wait_devtools_port(self._user_data_dir, self.timeout)
            page_ws = _page_websocket_url(port, timeout=self.timeout)
            if page_ws:
                host, ws_port, path = _split_ws(page_ws)
            else:
                host, ws_port, path = "127.0.0.1", port, ws_path
            self._cdp = _Cdp(host, ws_port, path)
            self._cdp.on("WebMCP.toolsAdded", self._on_tools_added)
            self._cdp.on("WebMCP.toolsRemoved", self._on_tools_removed)
        except Exception:
            self.close()
            raise

    def _wait_for_tools(self, deadline: float) -> None:
        settled_from = None
        while time.time() < deadline:
            with self._lock:
                if self._capabilities:
                    if settled_from is None:
                        settled_from = time.time()
                    elif time.time() - settled_from >= 2.0:
                        return
            try:
                self._cdp.wait_event("WebMCP.toolsAdded", min(deadline, time.time() + 0.25))
                settled_from = time.time()
            except BrowserWebMCPError:
                continue
        with self._lock:
            if not self._capabilities:
                raise BrowserWebMCPError("timed out waiting for WebMCP.toolsAdded")

    def _on_tools_added(self, params: Dict[str, Any]) -> None:
        with self._lock:
            for tool in params.get("tools") or []:
                cap = _capability_from_cdp_tool(tool, self.provider, self.page_url)
                self._capabilities[cap.id] = cap
                self._tools[cap.id] = tool
                self._tools[tool["name"]] = tool

    def _on_tools_removed(self, params: Dict[str, Any]) -> None:
        with self._lock:
            for tool in params.get("tools") or []:
                name = tool.get("name")
                cap_id = f"webmcp.{name}"
                self._capabilities.pop(cap_id, None)
                self._tools.pop(cap_id, None)
                self._tools.pop(name, None)

    def _lookup(self, capability_id: str):
        cap = self._capabilities.get(capability_id)
        if cap is None and f"webmcp.{capability_id}" in self._capabilities:
            cap = self._capabilities[f"webmcp.{capability_id}"]
        if cap is None:
            raise KeyError(f"browser WebMCP tool not found: {capability_id}")
        return cap, self._tools[cap.id]


def _capability_from_cdp_tool(tool: Dict[str, Any], provider: str, page_url: str) -> Capability:
    name = tool["name"]
    schema = tool.get("inputSchema") or {}
    declarative = tool.get("backendNodeId") is not None
    return Capability(
        id=f"webmcp.{name}",
        name=name,
        description=tool.get("description") or name,
        domain="web",
        inputs=schema.get("properties") or {},
        permissions=["web:access"],
        provider=provider,
        protocol="webmcp",
        endpoint=page_url,
        metadata={
            "specification": "webmcp-browser",
            "webmcp_spec": True,
            "surface": "declarative" if declarative else "imperative",
            "protocol": "webmcp",
            "frameId": tool.get("frameId"),
            "backendNodeId": tool.get("backendNodeId"),
        },
    )


def _wait_devtools_port(user_data_dir: str, timeout: float):
    path = os.path.join(user_data_dir, "DevToolsActivePort")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(path):
            try:
                lines = open(path, encoding="utf-8").read().splitlines()
            except OSError:
                lines = []
            if lines and lines[0].strip().isdigit():
                port = int(lines[0].strip())
                ws_path = lines[1].strip() if len(lines) > 1 else "/devtools/browser"
                if not ws_path.startswith("/"):
                    ws_path = "/" + ws_path
                return port, ws_path
        time.sleep(0.05)
    raise BrowserWebMCPError(f"Chrome did not write DevToolsActivePort under {user_data_dir}")


def _page_websocket_url(port: int, timeout: float) -> Optional[str]:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json/list"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(0.05)
            continue
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return target["webSocketDebuggerUrl"]
        time.sleep(0.05)
    return None


def _split_ws(ws_url: str):
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return host, port, path


def _kill_chrome(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class _Cdp:
    def __init__(self, host: str, port: int, path: str) -> None:
        self._ws = _WebSocket(host, port, path)
        self._next_id = 1
        self._pending: Dict[int, tuple[threading.Event, dict]] = {}
        self._events: List[Dict[str, Any]] = []
        self._handlers: Dict[str, Any] = {}
        self._cv = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def on(self, method: str, handler: Any) -> None:
        self._handlers[method] = handler

    def send(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        msg_id = self._next_id
        self._next_id += 1
        event = threading.Event()
        holder: dict = {}
        with self._cv:
            self._pending[msg_id] = (event, holder)
        payload: Dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        self._ws.send_text(json.dumps(payload))
        if not event.wait(timeout or 30.0):
            raise BrowserWebMCPError(f"CDP timeout: {method}")
        if "error" in holder:
            raise BrowserWebMCPError(f"{method} failed: {holder['error']}")
        return holder.get("result") or {}

    def wait_event(self, method: str, deadline: float, match: Optional[Any] = None) -> Dict[str, Any]:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise BrowserWebMCPError(f"timed out waiting for {method}")
            with self._cv:
                for i, ev in enumerate(self._events):
                    if ev.get("method") != method:
                        continue
                    params = ev.get("params") or {}
                    if match is None or match(params):
                        self._events.pop(i)
                        return params
                self._cv.wait(timeout=min(remaining, 0.25))

    def close(self) -> None:
        self._closed = True
        self._ws.close()

    def _read_loop(self) -> None:
        while not self._closed:
            try:
                raw = self._ws.recv_text()
            except Exception:
                break
            if not raw:
                continue
            msg = json.loads(raw)
            if "id" in msg:
                with self._cv:
                    pending = self._pending.pop(msg["id"], None)
                if pending is not None:
                    event, holder = pending
                    if "error" in msg:
                        holder["error"] = msg["error"]
                    else:
                        holder["result"] = msg.get("result") or {}
                    event.set()
                continue
            method = msg.get("method")
            params = msg.get("params") or {}
            handler = self._handlers.get(method)
            if handler is not None:
                handler(params)
            with self._cv:
                self._events.append(msg)
                self._cv.notify_all()


class _WebSocket:
    def __init__(self, host: str, port: int, path: str) -> None:
        self._sock = socket.create_connection((host, port), timeout=10)
        self._sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(req.encode("ascii"))
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise BrowserWebMCPError("CDP websocket handshake closed")
            header += chunk
        head, rest = header.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise BrowserWebMCPError(f"CDP websocket handshake failed: {status!r}")
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        if expected.encode("ascii") not in head:
            raise BrowserWebMCPError("CDP websocket accept mismatch")
        self._buf = rest
        self._send_lock = threading.Lock()

    def send_text(self, text: str) -> None:
        self._send_raw(0x1, text.encode("utf-8"))

    def recv_text(self) -> str:
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x8:
                return ""
            if opcode == 0x9:
                self._send_raw(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8")

    def close(self) -> None:
        try:
            self._send_raw(0x8, b"")
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass

    def _send_raw(self, opcode: int, payload: bytes) -> None:
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self._sock.sendall(header + masked)

    def _recv_frame(self):
        hdr = self._recv_exact(2)
        b1, b2 = hdr[0], hdr[1]
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(n)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(max(n - len(self._buf), 4096))
            if not chunk:
                raise BrowserWebMCPError("CDP websocket closed")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data
