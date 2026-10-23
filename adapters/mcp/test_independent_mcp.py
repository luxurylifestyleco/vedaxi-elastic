"""Remote MCP against a server that does not import the adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
for _p in (
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "adapters"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.mcp.remote_mcp import RemoteMCPAdapter

_SCRIPT = os.path.join(_REPO_ROOT, "examples", "independent_mcp_server.py")


def test_stdio_discovery_validation_timeout_and_cleanup():
    adapter = RemoteMCPAdapter(command=[sys.executable, _SCRIPT], timeout=5.0)
    try:
        caps = adapter.discover()
        by_id = {cap.id: cap for cap in caps}
        assert by_id["find_prospects"].metadata["transport"] == "stdio"
        assert by_id["find_prospects"].metadata["streamable_http"] is False
        assert by_id["find_prospects"].metadata["sse"] is False

        found = adapter.invoke("find_prospects", {})
        assert found.success is True
        names = [row["name"] for row in found.result["prospects"]]
        assert names == ["Ava Shah", "Ben Ortiz", "Cleo Park"]

        bad = adapter.invoke("echo_note", {})
        assert bad.success is False
        assert "input validation failed" in (bad.error or "")

        typed = adapter.invoke("echo_note", {"note": 3})
        assert typed.success is False
        assert "must be string" in (typed.error or "")

        echoed = adapter.invoke("echo_note", {"note": "ok"})
        assert echoed.success is True
        assert echoed.result["note"] == "ok"

        adapter.timeout = 0.4
        hung = adapter.invoke("block", {"seconds": 5})
        assert hung.success is False
        assert "Timeout" in (hung.error or "")
    finally:
        adapter.close()
    assert adapter._process is None


@pytest.fixture
def http_mcp():
    proc = subprocess.Popen(
        [sys.executable, _SCRIPT, "--http"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line.startswith("MCP_HTTP_PORT="):
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(f"no port line {line!r} {err!r}")
    port = int(line.split("=", 1)[1].strip())
    try:
        yield f"http://127.0.0.1:{port}/", proc
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_http_request_response_not_sse(http_mcp):
    url, proc = http_mcp
    adapter = RemoteMCPAdapter(url=url, timeout=0.4)
    caps = adapter.discover()
    transport = {cap.id: cap.metadata["transport"] for cap in caps}
    assert transport["find_prospects"] == "http-request-response"
    assert all(cap.metadata["streamable_http"] is False for cap in caps)
    assert all(cap.metadata["sse"] is False for cap in caps)

    found = adapter.invoke("find_prospects", {})
    assert found.success is True
    assert found.result["prospects"][0]["company"] == "Northwind Labs"

    refused = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(refused, timeout=5)
    assert exc.value.code == 406
    assert proc.poll() is None
