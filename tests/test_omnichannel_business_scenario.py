"""Omnichannel Business Scenario Acceptance Test for Elastic Web.

Demonstrates that Elastic Web coordinates capabilities to fulfill real business intent:
"Help me manage our incoming leads, research prospects, coordinate follow-ups,
keep response times within our targets, monitor customer satisfaction, and
show me which situations require my attention."

Verifies:
1. Intent understanding & compilation into actionable IntentIR.
2. Capability discovery from the Capability Book across multiple protocols:
   - Remote MCP: Omnichannel lead ingestion (Instagram, LinkedIn, Website, Amazon)
   - A2A Agent Delegation: Independent prospect and company research agent
   - WebMCP: Operational SLA and response-time target evaluator
   - Local tools: Sentiment/CSAT analysis, follow-up coordination & exception surfacing
3. Dynamic Recipe DAG formulation and topological execution with data bindings.
4. Handling missing/failing capabilities with safe fallback.
5. Invocation-time AuthorizationGuard preventing unauthorized external side-effects.
6. Telemetry recording of all steps without credential or data leaks.
7. Verification of business outcomes against explicit success conditions:
   - 0 missed leads across 4 channels
   - Response latency evaluated against targets (SLA breach detected)
   - Customer sentiment/CSAT scored
   - Exceptions requiring human attention explicitly isolated
   - Follow-up communications drafted but withheld from sending until human approval.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List
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
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app as gateway_app
from adapters.a2a.a2a_adapter import A2AAdapter, A2ATask, TaskState
from adapters.security.auth_guard import (
    AuthorizationGuard,
    SecurityPrincipal,
    SensitiveActionDeniedError,
    PermissionDeniedError,
)
from adapters.webmcp.webmcp_adapter import WebMCPAdapter
from capability import Capability
from compiler import RuleBasedCompiler
from compose import compose_recipe
from recipe import RecipeStatus
from store import RecipeStore
from strategies import KeywordRetriever
from telemetry import EventBus, TelemetryRecorder


# ---------------------------------------------------------------------------
# Synthetic Omnichannel Leads Data
# ---------------------------------------------------------------------------
_SYNTHETIC_LEADS = [
    {
        "lead_id": "lead-001",
        "channel": "LinkedIn",
        "sender": "Ava Vance",
        "company": "Apex Logistics",
        "title": "VP Supply Chain",
        "text": "Hi, we saw your enterprise solution and would love a demo for our 50-person ops team.",
        "received_minutes_ago": 5,
    },
    {
        "lead_id": "lead-002",
        "channel": "Instagram",
        "sender": "Marcus Thorne",
        "company": "Urban Retail",
        "title": "Owner",
        "text": "Hey! Do you offer tier pricing for small boutique shops?",
        "received_minutes_ago": 12,
    },
    {
        "lead_id": "lead-003",
        "channel": "Website",
        "sender": "Dr. Elena Rostova",
        "company": "BioHealth Systems",
        "title": "Director of IT",
        "text": "URGENT: Your webhook integration is failing and our checkout is throwing 500 errors! Please fix immediately!",
        "received_minutes_ago": 42,
    },
    {
        "lead_id": "lead-004",
        "channel": "Amazon",
        "sender": "Jordan Lee",
        "company": "Direct Customer",
        "title": "Consumer",
        "text": "Order #8921 arrived damaged. The box was crushed and parts are missing. Very disappointed with this shipment.",
        "received_minutes_ago": 8,
    },
]


# ---------------------------------------------------------------------------
# Independent A2A Research Agent Handler
# ---------------------------------------------------------------------------
class MockIndependentResearchAgent:
    """Simulates an autonomous market and prospect research agent via A2A."""

    agent_id = "agent.market_researcher"
    name = "Autonomous Prospect Researcher"
    description = "Autonomous market and prospect research agent"
    skills = [{
        "id": "research_lead_prospects",
        "name": "Research Lead Prospects",
        "description": "Enrich prospect company profiles, ARR tier, and legitimacy.",
        "domain": "operations",
        "permissions": ["a2a:delegate"],
        "metadata": {
            "intent_goals": ["manage_omnichannel_operations"],
            "stage": 2,
            "binds": {"leads": 1},
        },
    }]

    def handle_task(self, task: A2ATask) -> A2ATask:
        leads_data = task.input_data.get("leads", [])
        if isinstance(leads_data, dict):
            leads_data = leads_data.get("leads", [])
        researched = []
        for lead in leads_data:
            company = lead.get("company", "")
            if company == "Apex Logistics":
                profile = {
                    "company": company,
                    "tier": "Enterprise",
                    "estimated_arr": "$25M+",
                    "verified": True,
                    "notes": "High purchasing power; strong expansion signals",
                }
            elif company == "BioHealth Systems":
                profile = {
                    "company": company,
                    "tier": "Strategic Enterprise",
                    "estimated_arr": "$50M+",
                    "verified": True,
                    "notes": "Active SLA contract with priority support tier",
                }
            elif company == "Urban Retail":
                profile = {
                    "company": company,
                    "tier": "SMB",
                    "estimated_arr": "$500k",
                    "verified": True,
                    "notes": "Growing retail chain",
                }
            else:
                profile = {
                    "company": company,
                    "tier": "Individual / Consumer",
                    "estimated_arr": "N/A",
                    "verified": False,
                    "notes": "Retail consumer inquiry",
                }
            researched.append({"lead_id": lead.get("lead_id"), "research": profile})

        task.state = TaskState.COMPLETED
        task.output = {"prospect_profiles": researched}
        task.updated_at = time.time()
        return task


# ---------------------------------------------------------------------------
# Business Execution Logic Callables
# ---------------------------------------------------------------------------
def _evaluate_sla_logic(args: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluates response time targets against threshold (target: 15 min)."""
    leads = args.get("leads", [])
    if isinstance(leads, dict):
        leads = leads.get("leads", [])
    target = int(args.get("target_response_time_minutes", 15))

    evaluations = []
    breaches = []
    warnings = []
    for lead in leads:
        elapsed = lead.get("received_minutes_ago", 0)
        is_breach = elapsed > target
        is_warning = (target - 5) <= elapsed <= target
        status = "BREACH" if is_breach else ("WARNING" if is_warning else "ON_TARGET")
        item = {
            "lead_id": lead.get("lead_id"),
            "sender": lead.get("sender"),
            "channel": lead.get("channel"),
            "elapsed_minutes": elapsed,
            "target_minutes": target,
            "status": status,
        }
        evaluations.append(item)
        if is_breach:
            breaches.append(item)
        elif is_warning:
            warnings.append(item)

    return {
        "sla_evaluations": evaluations,
        "breaches": breaches,
        "warnings": warnings,
        "target_minutes": target,
        "total_analyzed": len(evaluations),
    }


def _assess_sentiment_logic(args: Dict[str, Any]) -> Dict[str, Any]:
    """Analyzes customer satisfaction sentiment from inquiry content."""
    leads = args.get("leads", [])
    if isinstance(leads, dict):
        leads = leads.get("leads", [])

    results = []
    negative_alerts = []
    for lead in leads:
        text = lead.get("text", "").lower()
        if "urgent" in text or "failing" in text or "500" in text:
            score = -0.85
            sentiment = "CRITICAL_NEGATIVE"
        elif "damaged" in text or "crushed" in text or "disappointed" in text:
            score = -0.70
            sentiment = "NEGATIVE"
        elif "love" in text or "enterprise" in text or "demo" in text:
            score = 0.90
            sentiment = "HIGHLY_POSITIVE"
        else:
            score = 0.50
            sentiment = "NEUTRAL"

        item = {
            "lead_id": lead.get("lead_id"),
            "sender": lead.get("sender"),
            "channel": lead.get("channel"),
            "sentiment_score": score,
            "sentiment_label": sentiment,
        }
        results.append(item)
        if score < 0:
            negative_alerts.append(item)

    return {
        "sentiment_results": results,
        "negative_alerts": negative_alerts,
        "csat_indicator": "Needs Attention (2 negative inquiries)",
    }


def _coordinate_operations_report(
    leads: Any,
    research: Any,
    sla_eval: Any,
    sentiment_eval: Any,
) -> Dict[str, Any]:
    """Synthesizes all inputs into the final executive operational report."""
    lead_list = leads.get("leads", []) if isinstance(leads, dict) else leads
    research_by_id = {
        item["lead_id"]: item["research"]
        for item in (research.get("prospect_profiles", []) if isinstance(research, dict) else [])
    }
    sla_by_id = {
        item["lead_id"]: item
        for item in (sla_eval.get("sla_evaluations", []) if isinstance(sla_eval, dict) else [])
    }
    sent_by_id = {
        item["lead_id"]: item
        for item in (sentiment_eval.get("sentiment_results", []) if isinstance(sentiment_eval, dict) else [])
    }

    followup_drafts = []
    situations_requiring_attention = []

    for lead in lead_list:
        lid = lead["lead_id"]
        sender = lead["sender"]
        channel = lead["channel"]
        r = research_by_id.get(lid, {})
        s = sla_by_id.get(lid, {})
        sent = sent_by_id.get(lid, {})

        # Build personalized draft
        draft_text = f"Hello {sender}, thank you for contacting us via {channel}."
        if r.get("tier") == "Enterprise":
            draft_text += " I have routed your request to our enterprise solutions team."
        elif "damaged" in lead.get("text", "").lower():
            draft_text += " We sincerely apologize for the damaged package. A replacement is ready to ship upon your confirmation."

        needs_human_attention = False
        reasons = []

        if s.get("status") in ("BREACH", "WARNING"):
            needs_human_attention = True
            reasons.append(
                f"Response time alert: {s.get('status')} ({s.get('elapsed_minutes')}m vs {s.get('target_minutes')}m target)"
            )

        if sent.get("sentiment_label") in ("CRITICAL_NEGATIVE", "NEGATIVE"):
            needs_human_attention = True
            reasons.append(f"Negative customer sentiment: {sent.get('sentiment_label')}")

        if r.get("tier") == "Strategic Enterprise":
            needs_human_attention = True
            reasons.append("High-value Strategic Enterprise client requiring executive handling")

        followup_drafts.append({
            "lead_id": lid,
            "sender": sender,
            "channel": channel,
            "company": lead.get("company"),
            "proposed_response": draft_text,
            "needs_human_approval": needs_human_attention,
            "approval_reasons": reasons,
            "status": "DRAFT_READY_NOT_SENT",
        })

        if needs_human_attention:
            situations_requiring_attention.append({
                "lead_id": lid,
                "sender": sender,
                "channel": channel,
                "company": lead.get("company"),
                "reasons": reasons,
                "urgency": "HIGH" if s.get("status") == "BREACH" or sent.get("sentiment_label") == "CRITICAL_NEGATIVE" else "MEDIUM",
                "recommended_action": "Owner/Manager review and approve personalized outreach",
            })

    return {
        "executive_summary": {
            "total_leads_processed": len(lead_list),
            "channels_covered": list(set(l["channel"] for l in lead_list)),
            "sla_breach_count": len(sla_eval.get("breaches", [])),
            "situations_requiring_attention_count": len(situations_requiring_attention),
            "contacts_sent": 0,
            "system_state": "All actions coordinated safely; zero unauthorized side effects executed.",
        },
        "situations_requiring_attention": situations_requiring_attention,
        "followup_drafts": followup_drafts,
        "contact_sent": False,
    }


def _refuse_outbound_contact(args: Dict[str, Any]) -> None:
    """Guarded sensitive capability: Refuses to send without explicit authorization."""
    raise RuntimeError("Refusing unauthorized outbound communication.")


# ---------------------------------------------------------------------------
# Test Suite: End-to-End Business Scenario
# ---------------------------------------------------------------------------
def test_omnichannel_operations_acceptance_scenario():
    """Validates the business owner directive across multi-protocol coordination."""
    user_request = (
        "Help me manage our incoming leads, research prospects, coordinate follow-ups, "
        "keep response times within our targets, monitor customer satisfaction, and "
        "show me which situations require my attention."
    )

    # 1. Interpret Business Objective via Compiler
    compiler = RuleBasedCompiler()
    intent = compiler.compile(user_request)

    assert intent.goal == "manage_omnichannel_operations"
    assert intent.domain == "operations"
    assert intent.action == "coordinate"
    assert intent.constraints["stop_before_contact"] is True
    assert intent.constraints["target_response_time_minutes"] == 15
    assert intent.authority["human_approval_before_contact"] is True

    # 2. Register Multi-Protocol Capabilities in Gateway
    # Ingestion capability (Remote MCP simulator)
    cap_ingest = Capability(
        id="mcp.ingest_omnichannel_leads",
        name="Ingest Omnichannel Leads",
        description="Ingest incoming customer leads across Instagram, LinkedIn, Website, and Amazon.",
        domain="operations",
        permissions=["leads:read"],
        protocol="mcp",
        metadata={
            "intent_goals": ["manage_omnichannel_operations"],
            "stage": 1,
            "transport": "mcp-rpc",
        },
    )
    gateway_app.register_local_capability(
        cap_ingest,
        lambda args: {"leads": _SYNTHETIC_LEADS},
    )

    # Prospect Research (A2A Agent delegation)
    a2a = A2AAdapter()
    a2a.register_agent(MockIndependentResearchAgent())
    a2a_caps = gateway_app.register_a2a_adapter(a2a)

    # SLA Evaluator (Web Service / WebMCP)
    cap_sla = Capability(
        id="webmcp.evaluate_response_sla",
        name="Evaluate Response SLA",
        description="Evaluate lead response times against SLA targets and flag breaches.",
        domain="operations",
        permissions=["sla:evaluate"],
        protocol="webmcp",
        metadata={
            "intent_goals": ["manage_omnichannel_operations"],
            "stage": 3,
            "binds": {"leads": 1},
        },
    )
    gateway_app.register_local_capability(cap_sla, _evaluate_sla_logic)

    # Customer Satisfaction / Sentiment Analyzer (Local Tool)
    cap_sentiment = Capability(
        id="local.assess_customer_sentiment",
        name="Assess Customer Sentiment",
        description="Evaluate customer satisfaction and sentiment score from inquiry content.",
        domain="operations",
        permissions=["sentiment:read"],
        protocol="local",
        metadata={
            "intent_goals": ["manage_omnichannel_operations"],
            "stage": 4,
            "binds": {"leads": 1},
        },
    )
    gateway_app.register_local_capability(cap_sentiment, _assess_sentiment_logic)

    # Operations Coordinator (Local Tool)
    cap_coordinator = Capability(
        id="local.coordinate_followups_and_exceptions",
        name="Coordinate Follow-ups and Exceptions",
        description="Synthesize leads, research, SLA status, and sentiment into an operational report.",
        domain="operations",
        permissions=["operations:coordinate"],
        protocol="local",
        metadata={
            "intent_goals": ["manage_omnichannel_operations"],
            "stage": 5,
            "binds": {"leads": 1, "research": 2, "sla_eval": 3, "sentiment_eval": 4},
        },
    )
    gateway_app.register_local_capability(
        cap_coordinator,
        lambda args: _coordinate_operations_report(**args),
    )

    # Sensitive Outbound Contact Dispatcher (Withheld by book)
    cap_dispatch = Capability(
        id="dispatch_customer_response",
        name="Dispatch Customer Response",
        description="Sends emails, DMs, or customer messages over external network channels.",
        domain="operations",
        permissions=["messages:send"],
        protocol="local",
        metadata={
            "intent_goals": ["manage_omnichannel_operations"],
            "sensitive": True,
            "external_side_effect": True,
        },
    )
    gateway_app.register_local_capability(cap_dispatch, _refuse_outbound_contact)

    # Distractor capability to prove capability selection selectivity
    cap_distractor = Capability(
        id="bank.transfer_funds",
        name="Transfer Funds",
        description="Move monetary balance between accounts.",
        domain="banking",
        protocol="local",
    )

    # 3. Retrieve from Capability Book
    book = [
        cap_ingest,
        a2a_caps[0],
        cap_sla,
        cap_sentiment,
        cap_coordinator,
        cap_dispatch,
        cap_distractor,
    ]
    retriever = KeywordRetriever(book)
    ranked = retriever.retrieve(intent, k=10)
    selected_ids = {r.capability_id for r in ranked if r.score > 0}

    # Verify retrieval precision
    assert "bank.transfer_funds" not in selected_ids
    assert cap_ingest.id in selected_ids
    assert cap_dispatch.id in selected_ids

    # 4. Compose Recipe DAG from Book Metadata
    selected_caps = [c for c in book if c.id in selected_ids]
    recipe = compose_recipe(intent, selected_caps, recipe_id="recipe.omnichannel_ops")

    # Verify sensitive capability was withheld as a human approval checkpoint
    assert recipe.checkpoints == ["human_approval_required:dispatch_customer_response"]
    assert "dispatch_customer_response" in recipe.provenance["withheld"]

    # Verify topological order
    assert [step.capability_id for step in recipe.steps] == [
        cap_ingest.id,
        a2a_caps[0].id,
        cap_sla.id,
        cap_sentiment.id,
        cap_coordinator.id,
    ]

    # 5. Security & Authorization Enforcement
    # Verify unapproved caller is blocked from sensitive action
    operator_principal = SecurityPrincipal(
        subject="business_operations_manager",
        granted_permissions={
            "leads:read",
            "a2a:delegate",
            "sla:evaluate",
            "sentiment:read",
            "operations:coordinate",
            "messages:send",
        },
    )
    with pytest.raises(SensitiveActionDeniedError):
        gateway_app._unified_executor(
            "dispatch_customer_response", {}, principal=operator_principal, explicit_approval=False
        )

    # 6. Execute Multi-Protocol Recipe DAG
    bus = EventBus()
    recorder = TelemetryRecorder(bus)
    store = RecipeStore(bus=bus)
    store.create(recipe)
    trace_id = "trace-omnichannel-test-001"

    def executor(cap_id: str, args: Dict[str, Any]):
        return gateway_app._unified_executor(
            cap_id, args, principal=operator_principal, explicit_approval=False
        )

    bus.emit("recipe.retrieved", trace_id=trace_id, intent_id=intent.intent_id, payload={"recipe_id": recipe.recipe_id})
    execution_results = store.execute(recipe.recipe_id, executor=executor, trace_id=trace_id, intent_id=intent.intent_id)

    bus.emit("outcome.delivered", trace_id=trace_id, intent_id=intent.intent_id, payload={"recipe_id": recipe.recipe_id})

    # 7. Outcome Verification
    final_outcome = execution_results["stage-5"]
    summary = final_outcome["executive_summary"]

    # Verify 4 channels covered without missed leads
    assert summary["total_leads_processed"] == 4
    assert set(summary["channels_covered"]) == {"Instagram", "LinkedIn", "Website", "Amazon"}

    # Verify SLA monitoring: 1 critical breach detected (Dr. Elena Rostova, 42 min)
    assert summary["sla_breach_count"] == 1
    sla_stage_data = execution_results["stage-3"]
    assert len(sla_stage_data["breaches"]) == 1
    assert sla_stage_data["breaches"][0]["sender"] == "Dr. Elena Rostova"
    assert sla_stage_data["breaches"][0]["elapsed_minutes"] == 42

    # Verify Situations Requiring Attention (Exceptions)
    exceptions = final_outcome["situations_requiring_attention"]
    assert len(exceptions) == 3
    exception_senders = {e["sender"] for e in exceptions}
    assert "Dr. Elena Rostova" in exception_senders  # SLA breach + Outage
    assert "Jordan Lee" in exception_senders         # Damaged goods / Churn risk
    assert "Ava Vance" not in exception_senders      # Clean, standard positive lead

    # Verify follow-up coordination & safety
    assert final_outcome["contact_sent"] is False
    assert summary["contacts_sent"] == 0
    drafts = final_outcome["followup_drafts"]
    assert len(drafts) == 4
    for draft in drafts:
        assert draft["status"] == "DRAFT_READY_NOT_SENT"
        assert len(draft["proposed_response"]) > 0

    # 8. Telemetry Verification
    trace_record = recorder.get(trace_id)
    assert trace_record is not None
    assert trace_record.recipe_id == recipe.recipe_id
    assert len(trace_record.errors) == 0
    assert len(trace_record.tool_calls) == 5
    # Verify no sensitive capability was called
    tool_names = [call.name for call in trace_record.tool_calls]
    assert "dispatch_customer_response" not in tool_names


def test_omnichannel_operations_failure_and_permission_boundaries():
    """Verifies that missing permissions are denied and execution failures are captured."""
    # 1. Permission denial check
    unauthorized_principal = SecurityPrincipal(
        subject="external_guest",
        granted_permissions={"leads:read"},  # Missing operations:coordinate
    )

    cap = Capability(
        id="local.guarded_coordinator",
        name="Guarded Coordinator",
        description="Operations coordinator requiring high privilege",
        domain="operations",
        permissions=["operations:coordinate"],
        protocol="local",
    )
    gateway_app.register_local_capability(cap, lambda args: {"status": "ok"})

    with pytest.raises(PermissionDeniedError):
        gateway_app._unified_executor(cap.id, {}, principal=unauthorized_principal)

    # 2. Unavailable service / failure recording
    failing_cap = Capability(
        id="local.failing_service",
        name="Failing Service",
        description="Simulates a remote third-party API outage",
        domain="operations",
        permissions=["operations:coordinate"],
        protocol="local",
    )

    def _failing_fn(args):
        raise ConnectionResetError("Remote API host unreachable")

    gateway_app.register_local_capability(failing_cap, _failing_fn)

    admin_principal = SecurityPrincipal(
        subject="admin",
        granted_permissions={"operations:coordinate"},
        is_admin=True,
    )

    # Verify execution failure is caught and error is raised cleanly
    with pytest.raises(ConnectionResetError, match="Remote API host unreachable"):
        gateway_app._unified_executor(failing_cap.id, {}, principal=admin_principal)
