"""Live Chrome WebMCP install check. Not HTML scraping. Not the HTTP adapter."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (
    _REPO_ROOT,
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "adapters"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.webmcp.browser_client import BrowserWebMCPClient, resolve_chrome


def _spawn_page():
    script = os.path.join(_REPO_ROOT, "examples", "webmcp_browser_page.py")
    proc = subprocess.Popen(
        [sys.executable, script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line.startswith("WEBMCP_PAGE_PORT="):
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(f"expected WEBMCP_PAGE_PORT=, got {line!r} stderr={err!r}")
    return proc, int(line.split("=", 1)[1].strip())


def test_browser_webmcp_discovers_and_invokes_document_tools():
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.skip("GitHub Actions has no headed WebMCP session; local Chrome is the proof")
    if resolve_chrome() is None:
        pytest.skip("headed Chrome is not on this machine; WebMCP is not claimed")
    page = None
    client = None
    try:
        page, port = _spawn_page()
        client = BrowserWebMCPClient(f"http://127.0.0.1:{port}/")
        caps = client.discover()
        by_name = {cap.name: cap for cap in caps}
        assert "note_company" in by_name, f"imperative tool missing from toolsAdded: {sorted(by_name)}"
        assert "lookup_company" in by_name, f"declarative tool missing from toolsAdded: {sorted(by_name)}"
        note = by_name["note_company"]
        lookup = by_name["lookup_company"]
        assert note.metadata["webmcp_spec"] is True
        assert note.metadata["specification"] == "webmcp-browser"
        assert lookup.metadata["webmcp_spec"] is True
        assert lookup.metadata["specification"] == "webmcp-browser"
        assert note.metadata["surface"] == "imperative"
        assert lookup.metadata["surface"] == "declarative"
        noted = client.invoke(note.id, {"company": "Northwind Labs"})
        assert noted.success is True, noted.error
        assert noted.result["company_id"] == "NTE-001"
        assert noted.result["note"] == "synthetic"
        looked = client.invoke(lookup.id, {"company": "BrightParcel"})
        assert looked.success is True, looked.error
        assert looked.result["token"] == "ew-webmcp-lookup-ok"
        assert looked.result["handled_by"] == "webmcp_browser_page_lookup"
        assert looked.result["company"] == "BrightParcel"
    finally:
        if client is not None:
            client.close()
        if page is not None:
            page.kill()
            try:
                page.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
