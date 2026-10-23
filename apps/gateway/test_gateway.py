"""Tests for the Elastic Web HTTP API gateway.

Exercises every endpoint through the in-process HTTP server using the
standard library ``urllib`` client. The gateway is a thin HTTP layer over
the foundation packages, so these tests assert that each endpoint wires
correctly to the underlying package functions.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

# Make the gateway app importable (it bootstraps sys.path itself).
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from app import (  # noqa: E402
    _RECIPE_STORE,
    _RECORDER,
    create_app,
    register_workload,
)
from recipe import Recipe, RecipeStep  # noqa: E402
from adapters.security.auth_guard import SecurityPrincipal  # noqa: E402


@pytest.fixture(scope="module")
def server():
    """Start the gateway on an ephemeral port and yield its base URL."""
    httpd = create_app()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    base = f"http://{host}:{port}"
    yield base
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _request(
    base: str,
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict | None = None,
):
    """Perform an HTTP request and return (status, parsed_json)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers=req_headers,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(server):
    status, payload = _request(server, "GET", "/health")
    assert status == 200
    assert payload == {"status": "ok"}


# ---------------------------------------------------------------------------
# /intent/compile
# ---------------------------------------------------------------------------


def test_intent_compile(server):
    status, payload = _request(
        server, "POST", "/intent/compile", {"text": "Get my August bank statement"}
    )
    assert status == 200
    assert payload["goal"] == "retrieve_financial_document"
    assert payload["domain"] == "banking"
    assert payload["object"] == "account_statement"
    assert payload["constraints"]["period"] == "2026-08"
    assert payload["intent_id"]


def test_intent_compile_empty_text(server):
    status, payload = _request(server, "POST", "/intent/compile", {"text": ""})
    assert status == 400
    assert "error" in payload


def test_intent_compile_unparseable(server):
    status, payload = _request(
        server, "POST", "/intent/compile", {"text": "zzz nonsense words"}
    )
    assert status == 422
    assert "error" in payload


# ---------------------------------------------------------------------------
# /intent/v1  (conversational Intent IR — not a compiler)
# ---------------------------------------------------------------------------

_CALL_MOM_V1 = {
    "schema_version": "1.0",
    "intent_id": "call-mom",
    "revision": 1,
    "source_text": "Call Mom.",
    "action": {"status": "resolved", "value": "call", "surface": "Call"},
    "object": {"status": "resolved", "value": "Mom", "surface": "Mom"},
}


def test_intent_v1_accepts_call_mom(server):
    status, payload = _request(server, "POST", "/intent/v1", _CALL_MOM_V1)
    assert status == 200
    assert payload["schema_version"] == "1.0"
    assert payload["intent_id"] == "call-mom"
    assert payload["action"]["value"] == "call"
    assert payload["object"]["value"] == "Mom"
    assert "domain" not in payload


def test_intent_v1_accepts_wrapped_intent(server):
    status, payload = _request(server, "POST", "/intent/v1", {"intent": _CALL_MOM_V1})
    assert status == 200
    assert payload["intent_id"] == "call-mom"


def test_intent_v1_rejects_unknown_field(server):
    bad = dict(_CALL_MOM_V1)
    bad["capability_id"] = "nope"
    status, payload = _request(server, "POST", "/intent/v1", bad)
    assert status == 400
    assert "error" in payload


def test_intent_compile_unchanged_by_v1_route(server):
    status, payload = _request(
        server, "POST", "/intent/compile", {"text": "Get my August bank statement"}
    )
    assert status == 200
    assert payload["goal"] == "retrieve_financial_document"


# ---------------------------------------------------------------------------
# /capabilities/discover
# ---------------------------------------------------------------------------


def test_capabilities_discover(server):
    status, payload = _request(
        server, "POST", "/capabilities/discover", {"intent": "Get my bank statement"}
    )
    assert status == 200
    assert payload["intent_id"]
    assert isinstance(payload["candidates"], list)
    assert len(payload["candidates"]) > 0
    first = payload["candidates"][0]
    assert "capability_id" in first
    assert 0.0 <= first["score"] <= 1.0


def test_capabilities_discover_missing_intent(server):
    status, payload = _request(server, "POST", "/capabilities/discover", {})
    assert status == 400
    assert "error" in payload


# ---------------------------------------------------------------------------
# /capabilities/{id}
# ---------------------------------------------------------------------------


def test_capability_get(server):
    status, payload = _request(server, "GET", "/capabilities/get_balance")
    assert status == 200
    assert payload["id"] == "get_balance"
    assert payload["domain"] == "accounts"
    assert payload["provider"] == "demo-bank"


def test_capability_get_not_found(server):
    status, payload = _request(server, "GET", "/capabilities/does_not_exist")
    assert status == 404
    assert "error" in payload


# ---------------------------------------------------------------------------
# /capabilities/{id}/execute
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reader(server):
    register_workload(
        "reader-test",
        SecurityPrincipal(
            subject="reader",
            tenant_id="tenant-demo",
            granted_permissions={"accounts:read", "documents:read", "documents:create"},
        ),
    )
    return {"Authorization": "Bearer reader-test"}


def test_capability_execute(server, reader):
    status, payload = _request(
        server,
        "POST",
        "/capabilities/get_balance/execute",
        {"args": {"account_id": "ACC-1001"}},
        headers=reader,
    )
    status, payload = _request(
        server, "POST", "/capabilities/nope/execute", {"args": {}}
    )
    assert status == 404
    assert "error" in payload


def test_capability_execute_bad_args(server, reader):
    status, payload = _request(
        server,
        "POST",
        "/capabilities/get_balance/execute",
        {"args": {"bogus_kwarg": 1}},
        headers=reader,
    )
    assert status == 400
    assert "error" in payload


# ---------------------------------------------------------------------------
# /recipes/resolve
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_recipe():
    """Seed a recipe into the shared store for resolve/execute tests."""
    recipe = Recipe(
        recipe_id="gw-recipe-1",
        intent_family="retrieve_financial_document",
        version="1.0.0",
        steps=[
            RecipeStep(
                step_id="s1",
                action="retrieve",
                capability_id="get_balance",
                args={"account_id": "ACC-1001"},
            )
        ],
        success_conditions=["balance returned"],
    )
    _RECIPE_STORE.create(recipe)
    return recipe


def test_recipes_resolve(server, seeded_recipe):
    status, payload = _request(
        server,
        "POST",
        "/recipes/resolve",
        {"intent_family": "retrieve_financial_document"},
    )
    assert status == 200
    assert payload["recipe_id"] == "gw-recipe-1"
    assert payload["intent_family"] == "retrieve_financial_document"


def test_recipes_resolve_not_found(server):
    status, payload = _request(
        server, "POST", "/recipes/resolve", {"intent_family": "no_such_family"}
    )
    assert status == 404
    assert "error" in payload


# ---------------------------------------------------------------------------
# /recipes/{id}/execute
# ---------------------------------------------------------------------------


def test_recipe_execute(server, seeded_recipe, reader):
    status, payload = _request(
        server, "POST", "/recipes/gw-recipe-1/execute", {"args": {}}, headers=reader
    )
    assert status == 200
    assert payload["recipe_id"] == "gw-recipe-1"
    assert payload["trace_id"]
    assert "s1" in payload["results"]
    assert "available_balance" in payload["results"]["s1"]


def test_recipe_execute_not_found(server):
    status, payload = _request(
        server, "POST", "/recipes/no_such_recipe/execute", {"args": {}}
    )
    assert status == 404
    assert "error" in payload


# ---------------------------------------------------------------------------
# /traces/{id}
# ---------------------------------------------------------------------------


def test_trace_get(server, seeded_recipe, reader):
    # Execute the recipe to produce a finalized telemetry record.
    status, payload = _request(
        server, "POST", "/recipes/gw-recipe-1/execute", {"args": {}}, headers=reader
    )
    assert status == 200
    trace_id = payload["trace_id"]

    status, trace = _request(server, "GET", f"/traces/{trace_id}")
    assert status == 200
    assert trace["trace_id"] == trace_id
    assert trace["recipe_id"] == "gw-recipe-1"
    assert trace["outcome"] == "delivered"


def test_trace_get_not_found(server):
    status, payload = _request(server, "GET", "/traces/does_not_exist")
    assert status == 404
    assert "error" in payload


# ---------------------------------------------------------------------------
# Unknown route
# ---------------------------------------------------------------------------


def test_unknown_route(server):
    status, payload = _request(server, "GET", "/nope")
    assert status == 404
    assert "error" in payload


def test_forged_principal_does_not_execute(server):
    status, payload = _request(
        server,
        "POST",
        "/capabilities/make_payment/execute",
        {"args": {"from_account": "ACC-1001", "to_account": "ACC-9", "amount": 1}},
        headers={"X-Principal": json.dumps({"is_admin": True, "permissions": ["payments:write"]})},
    )
    assert status == 401
    assert payload["type"] == "unverified_credential"
    assert "result" not in payload


def test_unauthenticated_execute_is_denied(server):
    status, payload = _request(
        server,
        "POST",
        "/capabilities/get_balance/execute",
        {"args": {"account_id": "ACC-1001"}},
    )
    assert status == 401
    assert payload["type"] == "unauthorized"


def test_recipe_execute_without_credential_is_denied(server, seeded_recipe):
    status, payload = _request(server, "POST", "/recipes/gw-recipe-1/execute", {"args": {}})
    assert status == 401
    assert payload["type"] == "unauthorized"
