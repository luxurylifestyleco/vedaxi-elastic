"""Phase 16 — Unit smoke tests.

Verifies that the core Elastic Web modules import cleanly and that their
basic public functions behave as documented. These are shallow smoke tests:
they confirm the wiring is intact, not the full behavior (which the
dedicated Phase 16 schema/retrieval/MCP/recipe/telemetry/benchmark files
cover in depth).
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Import path setup (mirrors conftest.py + the recipe/telemetry packages).
# ---------------------------------------------------------------------------
_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("intent-ir", "capability-registry", "capability-retrieval"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _name in ("recipe-schema", "telemetry"):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

# ---------------------------------------------------------------------------
# Core module imports
# ---------------------------------------------------------------------------


def test_intent_ir_imports():
    import intent_ir  # noqa: F401
    from intent_ir import IntentIR  # noqa: F401

    assert callable(IntentIR.new_id)


def test_capability_imports():
    from capability import Capability  # noqa: F401

    assert callable(Capability.new_id)


def test_retrieval_modules_import():
    import factory  # noqa: F401
    import retriever  # noqa: F401
    import strategies  # noqa: F401

    assert "keyword" in factory.available_strategies()


def test_mcp_modules_import():
    import demo_mcp_tools  # noqa: F401
    from mcp_adapter import MCPAdapter  # noqa: F401

    assert len(demo_mcp_tools.DEMO_TOOL_REGISTRY) >= 1


def test_recipe_modules_import():
    from recipe import Recipe, RecipeStatus, RecipeStep  # noqa: F401
    from store import RecipeStore  # noqa: F401

    assert RecipeStatus.ACTIVE.value == "active"


def test_telemetry_modules_import():
    from telemetry.event_bus import EventBus, ListSubscriber  # noqa: F401
    from telemetry.events import EventType  # noqa: F401
    from telemetry.telemetry import TelemetryRecorder  # noqa: F401

    assert EventType.INTENT_RECEIVED.value == "intent.received"


def test_demo_bank_imports():
    import bank  # noqa: F401
    from manifest import build_manifest  # noqa: F401

    assert callable(bank.get_balance)
    assert callable(bank.run_intent)


def test_control_agents_import():
    from control_a import BaselineAgent  # noqa: F401
    from control_b import RetrievalAgent  # noqa: F401
    import control_c  # noqa: F401

    assert callable(control_c.ControlC)


# ---------------------------------------------------------------------------
# Basic function smoke tests
# ---------------------------------------------------------------------------


def test_manifest_builds_capabilities():
    from manifest import build_manifest

    caps = build_manifest()
    assert len(caps) >= 60
    ids = {c.id for c in caps}
    assert {"get_balance", "make_payment", "freeze_card"}.issubset(ids)


def test_bank_run_intent_dispatches_demo_intents():
    import bank

    assert bank.run_intent("Get my August statement")["ok"] is True
    assert bank.run_intent("Pay my electricity bill")["ok"] is True
    assert bank.run_intent("Freeze my stolen card")["ok"] is True
    assert bank.run_intent("Get proof of income")["ok"] is True
    assert bank.run_intent("Export transactions from the last six months")["ok"] is True


def test_bank_run_intent_unknown_raises():
    import bank

    with pytest.raises(ValueError):
        bank.run_intent("do something completely unrelated")


def test_metrics_estimators_are_deterministic():
    from metrics import estimate_tokens, finalize, new_metrics

    assert estimate_tokens("hello world") == estimate_tokens("hello world")
    m = new_metrics()
    assert m["success"] is False
    finalize(m)
    assert m["total_tokens"] == 0
    assert m["estimated_model_cost"] == 0.0
