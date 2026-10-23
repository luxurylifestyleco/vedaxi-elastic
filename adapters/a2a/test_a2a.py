"""Tests for A2A (Agent-to-Agent) Delegation Adapter."""

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

from adapters.a2a.a2a_adapter import (
    A2AAdapter,
    A2ATask,
    AgentCard,
    TaskState,
    A2AAgentInterface,
)
from capability import Capability


class ComplianceAuditAgent:
    """An independent compliance agent that audits transactions."""
    agent_id = "agent.compliance_auditor"
    name = "Compliance Auditor"
    description = "Audits financial operations against regulatory rules."
    skills = [
        {
            "id": "verify_transaction",
            "name": "Verify Transaction Compliance",
            "description": "Checks if an amount and recipient pass AML/KYC rules.",
            "inputs": {"amount": "number", "payee": "string"},
            "outputs": {"approved": "boolean", "risk_score": "number", "audit_token": "string"},
            "permissions": ["compliance:audit"],
        }
    ]

    def handle_task(self, task: A2ATask) -> A2ATask:
        if task.skill == "verify_transaction":
            amount = task.input_data.get("amount", 0)
            payee = task.input_data.get("payee", "")

            # Independent business rule
            if amount > 10000 and "unverified" in payee.lower():
                task.state = TaskState.FAILED
                task.error = "Transaction flagged: high-risk unverified payee"
            else:
                task.state = TaskState.COMPLETED
                task.output = {
                    "approved": True,
                    "risk_score": 0.05 if amount < 5000 else 0.25,
                    "audit_token": f"AUDIT-OK-{task.task_id}",
                    "verified_by": self.agent_id,
                }
        else:
            task.state = TaskState.FAILED
            task.error = f"Unsupported skill: {task.skill}"
        task.updated_at = time.time()
        return task


def test_a2a_agent_registration_and_discovery():
    adapter = A2AAdapter()
    agent = ComplianceAuditAgent()
    caps = adapter.register_agent(agent)

    assert len(caps) == 1
    cap = caps[0]
    assert isinstance(cap, Capability)
    assert cap.protocol == "a2a"
    assert cap.provider == "agent.compliance_auditor"
    assert cap.id == "a2a.agent.compliance_auditor.verify_transaction"
    assert "amount" in cap.inputs


def test_a2a_two_agent_delegation_roundtrip():
    """Test two independent agents: Primary agent delegates verification to Compliance agent."""
    adapter = A2AAdapter()
    compliance_agent = ComplianceAuditAgent()
    adapter.register_agent(compliance_agent)

    # Agent A executes capability through the adapter
    cap_id = "a2a.agent.compliance_auditor.verify_transaction"
    payload = {"amount": 2500, "payee": "Alice Corp"}

    result = adapter.delegate_and_wait(cap_id, payload)

    assert result.success is True
    assert result.error is None
    assert result.result["approved"] is True
    assert result.result["risk_score"] == 0.05
    assert result.result["verified_by"] == "agent.compliance_auditor"
    assert "AUDIT-OK" in result.result["audit_token"]
    assert result.duration_ms > 0


def test_a2a_delegation_failure_handling():
    adapter = A2AAdapter()
    compliance_agent = ComplianceAuditAgent()
    adapter.register_agent(compliance_agent)

    cap_id = "a2a.agent.compliance_auditor.verify_transaction"
    # Trigger compliance rejection rule
    payload = {"amount": 15000, "payee": "Unverified Global LLC"}

    result = adapter.delegate_and_wait(cap_id, payload)

    assert result.success is False
    assert "high-risk" in result.error
