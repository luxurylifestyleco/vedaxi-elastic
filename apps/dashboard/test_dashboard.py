"""Tests for the Elastic Web dashboard HTTP server."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

_DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD_APP_PATH = Path(_DASHBOARD_DIR) / "app.py"

_spec = importlib.util.spec_from_file_location("dashboard_app", _DASHBOARD_APP_PATH)
_dashboard_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dashboard_mod)
create_app = _dashboard_mod.create_app


def test_keyword_fallback_preserves_unknown_values_as_uncertainty():
    intent = _dashboard_mod._compile_intent("Please pay my bill", strict=False)
    assert intent.state.value == "DISCOVERY"
    assert intent.original_expression == "Please pay my bill"
    assert intent.constraints == {}
    assert intent.uncertainty["missing"] == ["payee", "amount"]

# Ensure we never leak 'app' into sys.modules
sys.modules.pop("app", None)


@pytest.fixture(scope="module")
def server():
    srv = create_app(host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    srv.shutdown()
    srv.server_close()
    sys.modules.pop("app", None)


def test_health_endpoint(server: str):
    url = f"{server}/health"
    with urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data.get("status") == "ok"


def test_dashboard_html_served(server: str):
    url = f"{server}/dashboard"
    with urlopen(url) as response:
        assert response.status == 200
        content = response.read().decode("utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Elastic Web" in content


def test_api_capabilities(server: str):
    url = f"{server}/api/capabilities"
    with urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "capabilities" in data
        assert len(data["capabilities"]) >= 50
        assert data.get("total") == 64


def test_api_recipes(server: str):
    url = f"{server}/api/recipes"
    with urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "recipes" in data
        assert len(data["recipes"]) >= 3


def test_api_intent_compile(server: str):
    url = f"{server}/api/intent/compile"
    req = Request(
        url,
        data=json.dumps({"text": "Get my August bank statement"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "intent_family" in data or "goal" in data


def test_api_topology(server: str):
    url = f"{server}/api/topology"
    with urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 7
        districts = {n.get("district") for n in data["nodes"]}
        assert "banking" in districts
        assert "education" in districts
        assert "travel" in districts


def test_api_assurance_is_explicitly_unknown_without_authoritative_store(server: str):
    url = f"{server}/api/assurance?tenant_id=caller-supplied-value"
    with urlopen(url) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))

    assert data["authority"] == "UNKNOWN"
    assert data["authoritative"] is False
    assert data["tenant_id"] == "UNKNOWN"
    assert data["total"] == 0
    assert data["outcomes"] == []
    assert data["evidence"] == []
    assert data["verification"] == []
    assert data["recovery"] == []


def test_security_headers_and_cors_are_safe_by_default(server: str):
    request = Request(f"{server}/health", headers={"Origin": "https://untrusted.example"})
    with urlopen(request) as response:
        headers = response.headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "Access-Control-Allow-Origin" not in headers


def test_cors_requires_explicit_origin_allowlist(monkeypatch, server: str):
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", "https://dashboard.example")
    request = Request(f"{server}/health", headers={"Origin": "https://dashboard.example"})
    with urlopen(request) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "https://dashboard.example"

    request = Request(f"{server}/health", headers={"Origin": "https://untrusted.example"})
    with urlopen(request) as response:
        assert "Access-Control-Allow-Origin" not in response.headers


def test_execute_is_allowed_on_loopback(server: str):
    request = Request(
        f"{server}/api/execute",
        data=json.dumps({"capability_id": "get_balance"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        assert response.status == 200


def test_execute_requires_bearer_token_when_bound_externally(monkeypatch):
    monkeypatch.delenv("DASHBOARD_EXECUTION_TOKEN", raising=False)
    srv = create_app(host="0.0.0.0", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        port = srv.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/api/execute",
            data=json.dumps({"capability_id": "get_balance"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request)
        assert exc_info.value.code == 401
        assert exc_info.value.headers["WWW-Authenticate"] == 'Bearer realm="dashboard-execution"'
    finally:
        srv.shutdown()
        srv.server_close()


def test_execute_accepts_configured_bearer_token_when_bound_externally(monkeypatch):
    monkeypatch.setenv("DASHBOARD_EXECUTION_TOKEN", "local-test-token")
    srv = create_app(host="0.0.0.0", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        port = srv.server_address[1]
        request = Request(
            f"http://127.0.0.1:{port}/api/execute",
            data=json.dumps({"capability_id": "get_balance"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer local-test-token",
            },
        )
        with urlopen(request) as response:
            assert response.status == 200
    finally:
        srv.shutdown()
        srv.server_close()
