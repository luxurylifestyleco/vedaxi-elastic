"""Intent resolves to a registered participant without naming the protocol."""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from app import (  # noqa: E402
    _A2A_ADAPTERS,
    _DYNAMIC_CAPABILITIES,
    _LOCAL_CALLABLES,
    _RECIPE_STORE,
    _WORKLOADS,
    create_app,
    register_a2a_adapter,
    register_local_capability,
    register_workload,
)
from adapters.a2a.a2a_adapter import A2AAdapter, A2ATask, TaskState  # noqa: E402
from capability import Capability  # noqa: E402
from recipe import Recipe, RecipeStatus, RecipeStep  # noqa: E402
from adapters.security.auth_guard import SecurityPrincipal  # noqa: E402
import bank  # noqa: E402


INTENT = "prepare outreach for these prospects"


class CourierDesk:
    agent_id = "courier-desk"
    name = "Courier Desk"
    description = "Independent participant. Does not contact anyone."
    skills = [
        {
            "id": "quote_fare",
            "name": "Quote Fare",
            "description": (
                "Prepare outreach sales plan for prospects. "
                "Synthetic quote only. Does not contact them."
            ),
            "domain": "sales",
            "permissions": ["a2a:delegate"],
        }
    ]

    def __init__(self) -> None:
        self.calls: list = []

    def handle_task(self, task: A2ATask) -> A2ATask:
        self.calls.append(dict(task.input_data))
        task.state = TaskState.COMPLETED
        task.output = {"quoted": True, "contacted": False}
        return task


def _request(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(base + path, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture(scope="module")
def desk():
    agent = CourierDesk()
    adapter = A2AAdapter()
    caps = register_a2a_adapter(adapter)
    # register_a2a_adapter reads the adapter's current skills. Register first.
    return agent, adapter, caps


@pytest.fixture(scope="module")
def participant(desk):
    agent, adapter, _stale = desk
    caps = adapter.register_agent(agent)
    registered = register_a2a_adapter(adapter)
    ids = [cap.id for cap in registered]
    yield agent, ids
    for cap_id in ids:
        _DYNAMIC_CAPABILITIES.pop(cap_id, None)
        _A2A_ADAPTERS.pop(cap_id, None)


@pytest.fixture(scope="module")
def server():
    httpd = create_app()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def caller():
    register_workload(
        "interop-caller",
        SecurityPrincipal(
            subject="interop-caller",
            tenant_id="tenant-demo",
            granted_permissions={"a2a:delegate"},
        ),
    )
    register_workload(
        "interop-other",
        SecurityPrincipal(
            subject="interop-other",
            tenant_id="tenant-demo",
            granted_permissions={"a2a:delegate"},
        ),
    )
    register_workload(
        "interop-reader",
        SecurityPrincipal(
            subject="interop-reader",
            tenant_id="tenant-demo",
            granted_permissions={"accounts:read"},
        ),
    )
    yield {
        "owner": {"Authorization": "Bearer interop-caller"},
        "other": {"Authorization": "Bearer interop-other"},
        "reader": {"Authorization": "Bearer interop-reader"},
    }
    for token in ("interop-caller", "interop-other", "interop-reader"):
        _WORKLOADS.pop(token, None)


def test_discover_does_not_require_protocol(server, participant):
    agent, ids = participant
    status, payload = _request(server, "POST", "/capabilities/discover", {"intent": INTENT})
    assert status == 200
    found = [row["capability_id"] for row in payload["candidates"]]
    assert ids[0] in found
    route = payload["route"]
    assert route["kind"] == "capability"
    assert route["capability_id"] == ids[0]
    assert route["protocol"] == "a2a"
    assert route["provider"] == agent.agent_id
    assert route["handle"] == f"quote_fare@{agent.agent_id}"
    assert agent.calls == []


def test_handle_resolves_without_naming_adapter(server, participant):
    agent, ids = participant
    status, payload = _request(server, "GET", f"/capabilities/quote_fare@{agent.agent_id}")
    assert status == 200
    assert payload["id"] == ids[0]
    assert payload["protocol"] == "a2a"


def test_rejected_call_does_not_invoke_participant(server, participant, caller):
    agent, ids = participant
    before = len(agent.calls)
    status, payload = _request(
        server,
        "POST",
        "/intent/route",
        {"intent": INTENT, "args": {"lane": "synthetic"}},
    )
    assert status == 401
    assert payload["type"] == "unauthorized"
    assert len(agent.calls) == before

    status, payload = _request(
        server,
        "POST",
        f"/capabilities/quote_fare@{agent.agent_id}/execute",
        {"args": {"lane": "synthetic"}},
        headers=caller["reader"],
    )
    assert status == 403
    assert len(agent.calls) == before


def test_authorized_intent_invokes_existing_adapter(server, participant, caller):
    agent, ids = participant
    before = len(agent.calls)
    status, payload = _request(
        server,
        "POST",
        "/intent/route",
        {"intent": INTENT, "args": {"lane": "synthetic"}, "protocol": "must-be-ignored"},
        headers=caller["owner"],
    )
    assert status == 200, payload
    assert payload["route"]["capability_id"] == ids[0]
    assert payload["route"]["protocol"] == "a2a"
    assert payload["result"]["quoted"] is True
    assert payload["result"]["contacted"] is False
    assert payload["authorization"]["provider"] == agent.agent_id
    assert len(agent.calls) == before + 1
    assert agent.calls[-1]["lane"] == "synthetic"


def test_active_recipe_wins_draft_does_not(server, participant, caller):
    agent, ids = participant
    local_calls = []

    def _step(args):
        local_calls.append(args)
        return {"from": "recipe"}

    local = Capability(
        id="interop.recipe_step",
        name="Recipe step",
        description="Prepare outreach sales plan",
        domain="sales",
        permissions=["a2a:delegate"],
        provider="recipe-local",
        protocol="tool",
    )
    register_local_capability(local, _step)
    draft = Recipe(
        recipe_id="interop-draft-outreach",
        intent_family="prepare_outreach",
        status=RecipeStatus.DRAFT,
        steps=[RecipeStep(step_id="s", action="quote", capability_id=local.id)],
    )
    active = Recipe(
        recipe_id="interop-active-outreach",
        intent_family="prepare_outreach",
        status=RecipeStatus.ACTIVE,
        steps=[RecipeStep(step_id="s", action="quote", capability_id=local.id, args={"from": "recipe"})],
    )
    before = len(agent.calls)
    try:
        _RECIPE_STORE.create(draft)
        status, payload = _request(server, "POST", "/capabilities/discover", {"intent": INTENT})
        assert status == 200
        assert payload["route"]["kind"] == "capability"
        assert payload["route"]["capability_id"] == ids[0]

        _RECIPE_STORE.create(active)
        status, payload = _request(
            server,
            "POST",
            "/intent/route",
            {"intent": INTENT},
            headers=caller["owner"],
        )
        assert status == 200, payload
        assert payload["route"]["kind"] == "recipe"
        assert payload["route"]["recipe_id"] == active.recipe_id
        assert payload["result"]["s"]["from"] == "recipe"
        assert local_calls == [{"from": "recipe"}]
        assert len(agent.calls) == before
    finally:
        _RECIPE_STORE.retire(draft.recipe_id)
        _RECIPE_STORE.retire(active.recipe_id)
        _DYNAMIC_CAPABILITIES.pop(local.id, None)
        _LOCAL_CALLABLES.pop(local.id, None)


def test_ambiguous_handle_does_not_execute(server):
    calls = []

    def _run(args):
        calls.append(args)
        return {"ran": True}

    caps = []
    for suffix in ("a", "b"):
        cap = Capability(
            id=f"a2a.twin.quote_{suffix}",
            name="Twin",
            description="duplicate handle",
            domain="sales",
            permissions=["a2a:delegate"],
            provider="twin",
            protocol="a2a",
            metadata={"skill_id": "quote_fare", "agent_id": "twin"},
        )
        register_local_capability(cap, _run)
        caps.append(cap)
    try:
        status, payload = _request(
            server,
            "POST",
            "/capabilities/quote_fare@twin/execute",
            {"args": {}},
        )
        assert status == 409
        assert payload["type"] == "ambiguous_participant"
        assert calls == []
    finally:
        for cap in caps:
            _DYNAMIC_CAPABILITIES.pop(cap.id, None)
            _LOCAL_CALLABLES.pop(cap.id, None)


def test_device_protocol_uses_existing_executor_not_a_new_client(server, participant, caller):
    _agent, ids = participant
    calls = []

    def _run(args):
        calls.append(args)
        return {"device": True}

    cap = Capability(
        id="vdx.handset.open_app",
        name="Open app",
        description="Prepare outreach sales plan on the handset",
        domain="sales",
        permissions=["a2a:delegate"],
        provider="vdx-handset",
        protocol="vdx",
        metadata={"skill_id": "open_app", "agent_id": "vdx-handset"},
    )
    hidden = {cap_id: _DYNAMIC_CAPABILITIES.pop(cap_id) for cap_id in ids}
    hidden_adapters = {cap_id: _A2A_ADAPTERS.pop(cap_id) for cap_id in ids}
    register_local_capability(cap, _run)
    try:
        status, payload = _request(
            server,
            "POST",
            "/intent/route",
            {"intent": INTENT, "args": {"app": "maps"}},
            headers=caller["owner"],
        )
        assert status == 200, payload
        assert payload["route"]["kind"] == "device"
        assert payload["route"]["protocol"] == "vdx"
        assert payload["result"]["device"] is True
        assert calls == [{"app": "maps"}]
    finally:
        _DYNAMIC_CAPABILITIES.pop(cap.id, None)
        _LOCAL_CALLABLES.pop(cap.id, None)
        _DYNAMIC_CAPABILITIES.update(hidden)
        _A2A_ADAPTERS.update(hidden_adapters)


def test_agent_card_hides_demo_bank(server):
    status, card = _request(server, "GET", "/.well-known/agent-card.json")
    assert status == 200
    skill_ids = [skill["id"] for skill in card["skills"]]
    assert skill_ids == ["route_intent"]
    assert "get_balance" not in skill_ids
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False


def test_inbound_send_requires_auth_and_session(server, participant, caller):
    agent, _ids = participant
    before = len(agent.calls)
    message = {
        "role": "ROLE_USER",
        "parts": [{"text": INTENT}, {"data": {"intent": INTENT, "args": {"lane": "peer"}}}],
        "metadata": {"skillId": "route_intent"},
    }
    status, payload = _request(
        server,
        "POST",
        "/rpc",
        {"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {"message": message}},
    )
    assert status == 401
    assert len(agent.calls) == before

    status, payload = _request(
        server,
        "POST",
        "/rpc",
        {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "SendMessage",
            "params": {"message": {**message, "contextId": "ctx-missing"}},
        },
        headers=caller["owner"],
    )
    assert status == 200
    assert payload["error"]["message"] == "session not found"
    assert len(agent.calls) == before

    status, payload = _request(
        server,
        "POST",
        "/rpc",
        {"jsonrpc": "2.0", "id": "3", "method": "SendMessage", "params": {"message": message}},
        headers=caller["owner"],
    )
    assert status == 200, payload
    task = payload["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert len(agent.calls) == before + 1
    context_id = task["contextId"]

    status, payload = _request(
        server,
        "POST",
        "/rpc",
        {
            "jsonrpc": "2.0",
            "id": "4",
            "method": "SendMessage",
            "params": {"message": {**message, "contextId": context_id}},
        },
        headers=caller["other"],
    )
    assert payload["error"]["message"] == "session not found"
    assert len(agent.calls) == before + 1

    status, session = _request(
        server,
        "POST",
        "/rpc",
        {"jsonrpc": "2.0", "id": "5", "method": "GetSession", "params": {"contextId": context_id}},
        headers=caller["owner"],
    )
    assert status == 200
    assert session["result"]["contextId"] == context_id
    assert session["result"]["turns"]

    seen = []
    original = bank.get_balance

    def _spy(**kwargs):
        seen.append(kwargs)
        return original(**kwargs)

    bank.get_balance = _spy
    try:
        status, payload = _request(
            server,
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": "6",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "role": "ROLE_USER",
                        "contextId": context_id,
                        "metadata": {"skillId": "get_balance"},
                        "parts": [{"data": {"args": {"account_id": "ACC-1"}}}],
                    }
                },
            },
            headers=caller["owner"],
        )
        assert status == 200
        assert payload["result"]["task"]["status"]["state"] == "TASK_STATE_FAILED"
        assert seen == []
    finally:
        bank.get_balance = original
