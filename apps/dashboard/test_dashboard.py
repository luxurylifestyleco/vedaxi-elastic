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
