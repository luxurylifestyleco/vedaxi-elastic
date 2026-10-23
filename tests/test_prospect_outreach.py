"""Business intent through the capability book, not a hard-coded recipe.

Independent processes:
- examples/independent_mcp_server.py (stdio MCP)
- examples/independent_a2a_agent.py (A2A v1 JSON-RPC)
- examples/company_directory_server.py (declarative WebMCP form)

No message is sent. Imperative document.modelContext is not executed.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (
    _REPO_ROOT,
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "intent-ir"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "packages", "capability-retrieval"),
    os.path.join(_REPO_ROOT, "packages", "recipe-schema"),
    os.path.join(_REPO_ROOT, "apps", "gateway"),
    os.path.join(_REPO_ROOT, "adapters"),
    os.path.join(_REPO_ROOT, "examples"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app as gateway_app
from adapters.a2a.a2a_adapter import A2AAdapter
from adapters.mcp.remote_mcp import RemoteMCPAdapter
from adapters.security.auth_guard import SecurityPrincipal, SensitiveActionDeniedError
from adapters.webmcp.declarative import DeclarativeWebMCPClient
from capability import Capability
from compiler import RuleBasedCompiler
from compose import compose_recipe
from outreach_report import build_outreach_report, refuse_send
from recipe import RecipeStatus
from store import RecipeStore
from strategies import KeywordRetriever
from telemetry import EventBus, TelemetryRecorder

_INTENT = (
    "Find suitable prospects, research their companies, prepare a personalized outreach plan, "
    "and report which prospects need human approval before contact."
)


def _spawn(script: str, prefix: str, args: list[str] | None = None) -> tuple[subprocess.Popen, int]:
    proc = subprocess.Popen(
        [sys.executable, script, *(args or [])],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line.startswith(prefix):
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(f"expected {prefix}, got {line!r} stderr={err!r}")
    return proc, int(line.split("=", 1)[1].strip())


def test_prospect_outreach_stops_before_contact():
    a2a_proc, a2a_port = _spawn(
        os.path.join(_REPO_ROOT, "examples", "independent_a2a_agent.py"),
        "A2A_PORT=",
        ["--port", "0"],
    )
    directory_proc, directory_port = _spawn(
        os.path.join(_REPO_ROOT, "examples", "company_directory_server.py"),
        "DIRECTORY_PORT=",
    )
    mcp = RemoteMCPAdapter(
        command=[sys.executable, os.path.join(_REPO_ROOT, "examples", "independent_mcp_server.py")],
        timeout=5,
    )
    try:
        intent = RuleBasedCompiler().compile(_INTENT)
        assert intent.goal == "prepare_outreach"
        assert "steps" not in intent.model_dump()

        mcp_caps = mcp.discover()
        assert any(cap.metadata["transport"] == "stdio" for cap in mcp_caps)
        gateway_app.register_remote_mcp_adapter(mcp)

        a2a = A2AAdapter()
        a2a_caps = a2a.discover_http(f"http://127.0.0.1:{a2a_port}")
        gateway_app.register_a2a_adapter(a2a)
        assert a2a_caps[0].metadata["binding"] == "jsonrpc"

        page = DeclarativeWebMCPClient(f"http://127.0.0.1:{directory_port}/")
        web_caps = gateway_app.register_declarative_webmcp(page)
        assert web_caps[0].metadata["specification"] == "webmcp-declarative-form"
        assert web_caps[0].metadata["imperative_model_context"] is False

        report = Capability(
            id="report_outreach_approval",
            name="Report Outreach Approval",
            description="Prepare an outreach sales plan and report who needs human approval before contact.",
            domain="sales",
            permissions=["outreach:plan"],
            provider="local",
            protocol="local",
            metadata={
                "intent_goals": ["prepare_outreach"],
                "stage": 4,
                "binds": {"prospects": 1, "research": 2, "profiles": 3},
            },
        )
        send = Capability(
            id="send_outreach",
            name="Send Outreach",
            description="Send outreach contact to sales prospects. External side effect.",
            domain="sales",
            permissions=["outreach:send"],
            provider="local",
            protocol="local",
            metadata={
                "intent_goals": ["prepare_outreach"],
                "sensitive": True,
                "external_side_effect": True,
            },
        )
        distractor = Capability(
            id="get_balance",
            name="Get Balance",
            description="Read the current account balance",
            domain="accounts",
            protocol="local",
        )
        gateway_app.register_local_capability(report, lambda args: build_outreach_report(**args))
        gateway_app.register_local_capability(send, refuse_send)

        book = [*mcp_caps, *a2a_caps, *web_caps, report, send, distractor]
        ranked = KeywordRetriever(book).retrieve(intent, k=10)
        selected_ids = [row.capability_id for row in ranked if row.score > 0]
        assert "get_balance" not in selected_ids
        assert "find_prospects" in selected_ids
        assert "send_outreach" in selected_ids
        selected = [cap for cap in book if cap.id in selected_ids]
        recipe = compose_recipe(intent, selected, recipe_id="recipe.prepare_outreach")
        assert [step.capability_id for step in recipe.steps] == [
            "find_prospects",
            a2a_caps[0].id,
            "webmcp.lookup_company",
            "report_outreach_approval",
        ]
        assert recipe.checkpoints == ["human_approval_required:send_outreach"]
        assert recipe.status == RecipeStatus.ACTIVE

        principal = SecurityPrincipal(
            subject="outreach_planner",
            granted_permissions={
                "prospects:read",
                "a2a:delegate",
                "web:access",
                "outreach:plan",
                "outreach:send",
            },
        )
        with pytest.raises(SensitiveActionDeniedError):
            gateway_app._unified_executor("send_outreach", {}, principal=principal)
        with pytest.raises(SensitiveActionDeniedError):
            gateway_app._unified_executor(
                "send_outreach", {}, principal=principal, explicit_approval=True
            )

        bus = EventBus()
        recorder = TelemetryRecorder(bus)
        store = RecipeStore(bus=bus)
        store.create(recipe)
        trace_id = "trace-prospect-outreach"

        def executor(capability_id: str, args: dict):
            return gateway_app._unified_executor(
                capability_id, args, principal=principal, explicit_approval=False
            )

        bus.emit(
            "recipe.retrieved",
            trace_id=trace_id,
            intent_id=intent.intent_id,
            payload={"recipe_id": recipe.recipe_id},
        )
        results = store.execute(recipe.recipe_id, executor=executor, trace_id=trace_id, intent_id=intent.intent_id)
        outcome = results["stage-4"]
        assert outcome["contact_sent"] is False
        assert all(item["sent"] is False for item in outcome["outreach_plan"])
        holds = {item["prospect"]: item["reason"] for item in outcome["needs_human_approval"]}
        assert holds["Ben Ortiz"] == "existing customer"
        assert holds["Cleo Park"] == "no public profile"
        assert "Ava Shah" not in holds
        ava = next(item for item in outcome["outreach_plan"] if item["prospect"] == "Ava Shah")
        assert "logistics software" in ava["draft"]
        assert outcome["profiles_checked"] == ["Northwind Labs", "Brightparcel", "Closed Books LLC"]
        assert results["stage-2"]["research"][2]["public"] is False

        bus.emit(
            "outcome.delivered",
            trace_id=trace_id,
            intent_id=intent.intent_id,
            payload={"recipe_id": recipe.recipe_id},
        )
        record = recorder.get(trace_id)
        assert record is not None
        assert record.recipe_id == recipe.recipe_id
        assert record.errors == []
        assert [call.name for call in record.tool_calls] == [step.capability_id for step in recipe.steps]
        assert "send_outreach" not in [call.name for call in record.tool_calls]
    finally:
        mcp.close()
        a2a_proc.kill()
        directory_proc.kill()
        a2a_proc.wait(timeout=5)
        directory_proc.wait(timeout=5)
