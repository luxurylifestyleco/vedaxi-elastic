"""Tests for RemoteMCPAdapter (Stdio and HTTP MCP transports)."""

from __future__ import annotations

import os
import sys
import time
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
for _p in [
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "adapters"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.mcp.remote_mcp import RemoteMCPAdapter, RemoteMCPTimeoutError, RemoteMCPError
from capability import Capability


@pytest.fixture
def sample_server_cmd():
    server_script = os.path.join(_REPO_ROOT, "examples", "sample_mcp_server.py")
    if not os.path.exists(server_script):
        # Also check Mastermind or create a local copy if needed
        mastermind_script = r"C:\Users\m_jor\Documents\Vedaxi-Elastic-Web-Mastermind\examples\sample_mcp_server.py"
        if os.path.exists(mastermind_script):
            server_script = mastermind_script
    return [sys.executable, server_script]


def test_remote_mcp_stdio_discovery_and_invocation(sample_server_cmd):
    """Test connecting to sample MCP server via stdio, discovering capabilities, and invoking."""
    adapter = RemoteMCPAdapter(command=sample_server_cmd, timeout=5.0)
    try:
        caps = adapter.discover()
        assert len(caps) >= 4
        cap_ids = {c.id for c in caps}
        assert "get_balance" in cap_ids
        assert "make_payment" in cap_ids

        # Check normalization
        balance_cap = adapter.get_capability("get_balance")
        assert isinstance(balance_cap, Capability)
        assert balance_cap.protocol == "mcp"
        assert balance_cap.provider == "remote-mcp"
        assert "account_id" in balance_cap.inputs

        # Invoke tool
        res = adapter.invoke("get_balance", {"account_id": "ACC-1001"})
        assert res.success is True
        assert res.result is not None
        assert "available_balance" in res.result or "account_id" in res.result
        assert res.duration_ms > 0
    finally:
        adapter.close()


def test_remote_mcp_tool_not_found(sample_server_cmd):
    adapter = RemoteMCPAdapter(command=sample_server_cmd, timeout=5.0)
    try:
        adapter.discover()
        with pytest.raises(KeyError):
            adapter.invoke("non_existent_tool", {})
    finally:
        adapter.close()


def test_remote_mcp_context_manager(sample_server_cmd):
    with RemoteMCPAdapter(command=sample_server_cmd, timeout=5.0) as adapter:
        caps = adapter.discover()
        assert len(caps) > 0
    # Process should be closed after context exit
    assert adapter._process is None
