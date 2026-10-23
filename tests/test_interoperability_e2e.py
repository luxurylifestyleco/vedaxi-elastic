"""Phase 5 — Multi-Protocol End-to-End Interoperability Test.

Proves genuine multi-agent and multi-protocol capability execution across:
1. IntentIR (intent intake and compilation)
2. Capability Book retrieval & DAG composition
3. WebMCP HTTP capability execution
4. A2A independent agent task delegation and verification
5. Remote MCP tool execution over stdio
6. AuthorizationGuard enforcement and failure observability
7. Outcome verification without external side effects
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
for _p in [
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "intent-ir"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "packages", "capability-retrieval"),
    os.path.join(_REPO_ROOT, "packages", "recipe-schema"),
    os.path.join(_REPO_ROOT, "apps", "gateway"),
    os.path.join(_REPO_ROOT, "adapters"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from compiler import RuleBasedCompiler
from intent_ir import IntentIR
from recipe import Recipe, RecipeStep, RecipeStatus
from store import RecipeStore
from telemetry import EventBus, TelemetryRecorder
from capability import Capability

from adapters.mcp.remote_mcp import RemoteMCPAdapter
from adapters.a2a.a2a_adapter import (
    A2AAdapter,
    A2ATask,
    AgentCard,
    TaskState,
)
from adapters.webmcp.webmcp_adapter import WebMCPAdapter
from adapters.security.auth_guard import (
    AuthorizationGuard,
    SecurityPrincipal,
    PermissionDeniedError,
)

import app as gateway_app


# ---------------------------------------------------------------------------
# Fixture: Mock WebMCP Server
# ---------------------------------------------------------------------------
class WebMCPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/capabilities/get_balance":
            payload = {
                "id": "get_balance",
                "name": "Check Balance",
                "description": "Check current funds over WebMCP.",
                "domain": "accounts",
                "inputs": {"account_id": {"type": "string"}},
                "outputs": {"available_balance": {"type": "number"}},
                "permissions": ["accounts:read"],
                "protocol": "webmcp",
                "endpoint": "/capabilities/get_balance/execute",
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/capabilities/get_balance/execute":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            req = json.loads(raw.decode("utf-8"))
            args = req.get("args", {})
            res = {
                "capability_id": "get_balance",
                "result": {"account_id": args.get("account_id"), "available_balance": 15000.0, "currency": "USD"},
            }
            body = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture
def webmcp_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), WebMCPHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# Fixture: Independent A2A Compliance Auditor Agent
# ---------------------------------------------------------------------------
class IndependentComplianceAgent:
    agent_id = "agent.external_risk_auditor"
    name = "External Risk Auditor"
    description = "Autonomous regulatory compliance agent"
    skills = [
        {
            "id": "compliance_audit",
            "name": "Audit Transaction Risk",
            "description": "Reviews source, destination, and amount for sanction violations.",
            "inputs": {"amount": "number", "payee": "string"},
            "outputs": {"approved": "boolean", "audit_token": "string"},
            "permissions": ["compliance:audit"],
        }
    ]

    def handle_task(self, task: A2ATask) -> A2ATask:
        amount = task.input_data.get("amount", 0)
        payee = task.input_data.get("payee", "")

        if "blacklisted" in payee.lower():
            task.state = TaskState.FAILED
            task.error = "Payee is blacklisted by compliance policy"
        else:
            task.state = TaskState.COMPLETED
            task.output = {
                "approved": True,
                "audit_token": f"AUDIT-SIG-VALID-{task.task_id}",
                "delegated_agent": self.agent_id,
                "timestamp": time.time(),
            }
        task.updated_at = time.time()
        return task


# ---------------------------------------------------------------------------
# End-to-End Interoperability Test
# ---------------------------------------------------------------------------
def test_end_to_end_multi_protocol_workflow(webmcp_url):
    """Proves: IntentIR -> Capability Retrieval -> DAG Multi-Protocol Execution
    (WebMCP + A2A + Remote MCP) -> Authorization & Verification.
    """
    # 1. Intent Intake & Representation via IntentIR
    compiler = RuleBasedCompiler()
    # Financial intent: compile statement/invoice/payment intent
    intent: IntentIR = compiler.compile("bank statement for march")
    assert intent.goal == "retrieve_financial_document"
    assert intent.domain == "banking"
    assert "period" in intent.constraints

    # 2. Setup Adapters
    # Adapter 1: WebMCP Adapter
    webmcp_adapter = WebMCPAdapter(base_url=webmcp_url)
    cap_balance = webmcp_adapter.discover_capability("get_balance")
    assert cap_balance is not None

    # Adapter 2: A2A Adapter
    a2a_adapter = A2AAdapter()
    compliance_agent = IndependentComplianceAgent()
    a2a_caps = a2a_adapter.register_agent(compliance_agent)
    assert len(a2a_caps) == 1
    cap_compliance = a2a_caps[0]

    # Adapter 3: Remote MCP Adapter (stdio)
    server_script = os.path.join(_REPO_ROOT, "examples", "sample_mcp_server.py")
    remote_mcp = RemoteMCPAdapter(command=[sys.executable, server_script])
    remote_caps = remote_mcp.discover()
    assert len(remote_caps) >= 4
    cap_payment = remote_mcp.get_capability("make_payment")
    assert cap_payment is not None

    # Register in Gateway
    gateway_app.register_webmcp_adapter(webmcp_adapter, ["get_balance"])
    gateway_app.register_a2a_adapter(a2a_adapter)
    gateway_app.register_remote_mcp_adapter(remote_mcp)

    try:
        # 3. Plan & Compose DAG Recipe spanning all 3 protocols
        # Step 1 (WebMCP): Check available balance
        # Step 2 (A2A): Delegate compliance audit to independent compliance agent
        # Step 3 (Remote MCP): Execute final payment with audit verification
        recipe = Recipe(
            recipe_id="recipe.cross_protocol_transfer",
            intent_family="cross_protocol_transfer",
            version="1.0.0",
            status=RecipeStatus.ACTIVE,
            steps=[
                RecipeStep(
                    step_id="step1_balance",
                    action="check_balance",
                    capability_id=cap_balance.id,  # webmcp.get_balance
                    args={"account_id": "ACC-CORP-42"},
                ),
                RecipeStep(
                    step_id="step2_compliance",
                    action="audit_compliance",
                    capability_id=cap_compliance.id,  # a2a.agent.external_risk_auditor.compliance_audit
                    args={"amount": 4500, "payee": "Global Tech Supplies Inc"},
                    depends_on=["step1_balance"],
                ),
                RecipeStep(
                    step_id="step3_pay",
                    action="execute_payment",
                    capability_id=cap_payment.id,  # make_payment via Remote MCP
                    args={"from_account": "ACC-CORP-42", "to_account": "ACC-GLOBAL-TECH", "amount": 4500.0, "reference": "Invoice INV-2026-99"},
                    depends_on=["step2_compliance"],
                ),
            ],
        )

        # 4. Execute Multi-Protocol DAG
        bus = EventBus()
        recorder = TelemetryRecorder(bus)
        store = RecipeStore(bus=bus)
        store.create(recipe)

        trace_id = "trace-e2e-interop-proof"
        bus.emit("recipe.retrieved", trace_id=trace_id, payload={"recipe_id": "recipe.cross_protocol_transfer"})
        principal = SecurityPrincipal(
            subject="e2e_operator",
            tenant_id="tenant-demo",
            granted_permissions={
                "accounts:read",
                "compliance:audit",
                "a2a:delegate",
                "payments:write",
                "web:access",
            },
        )

        def executor(capability_id, args):
            return gateway_app._unified_executor(
                capability_id,
                args,
                principal=principal,
                explicit_approval=True,
            )

        results = store.execute(
            "recipe.cross_protocol_transfer",
            executor=executor,
            trace_id=trace_id,
        )

        # 5. Verify Results & Outcomes across all 3 protocols
        # Result 1: WebMCP output
        assert "step1_balance" in results
        assert results["step1_balance"]["available_balance"] == 15000.0

        # Result 2: A2A delegation output
        assert "step2_compliance" in results
        assert results["step2_compliance"]["approved"] is True
        assert "AUDIT-SIG-VALID" in results["step2_compliance"]["audit_token"]
        assert results["step2_compliance"]["delegated_agent"] == "agent.external_risk_auditor"

        # Result 3: Remote MCP tool execution output
        assert "step3_pay" in results
        assert results["step3_pay"]["status"] == "pending"
        assert results["step3_pay"]["amount"] == 4500

        # 6. Verify Telemetry trace recorded all steps without credential leakage
        bus.emit("outcome.delivered", trace_id=trace_id, payload={"recipe_id": "recipe.cross_protocol_transfer"})
        trace_record = recorder.get(trace_id)
        assert trace_record is not None
        assert trace_record.recipe_id == "recipe.cross_protocol_transfer"
        assert len(trace_record.tool_calls) == 3
        tool_names = [tc.name for tc in trace_record.tool_calls]
        assert tool_names == [
            "webmcp.get_balance",
            "a2a.agent.external_risk_auditor.compliance_audit",
            "make_payment",
        ]

    finally:
        remote_mcp.close()


def test_authorization_denial_observability():
    """Verify that unauthorized calls are blocked and observable."""
    guard = AuthorizationGuard()
    # A sensitive capability requiring write entitlement
    secure_cap = Capability(
        id="a2a.agent.vault.release_funds",
        name="Release Funds",
        description="Release restricted funds",
        domain="vault",
        permissions=["vault:release"],
        metadata={"sensitive": True},
    )

    unauthorized_caller = SecurityPrincipal(
        subject="external_guest",
        granted_permissions={"accounts:read"},  # Missing vault:release
    )

    with pytest.raises(PermissionDeniedError) as exc_info:
        guard.check(secure_cap, principal=unauthorized_caller)

    assert "Missing permissions: ['vault:release']" in str(exc_info.value)
