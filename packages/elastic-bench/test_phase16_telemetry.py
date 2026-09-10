"""Phase 16 — Telemetry tests.

Verifies that the telemetry package (event_bus.py, events.py, telemetry.py)
records events, folds them into per-execution records, and exports JSON.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in ("telemetry",):
    _p = os.path.join(_PACKAGES, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)
_demo = os.path.join(_APPS, "demo-bank")
if _demo not in sys.path:
    sys.path.insert(0, _demo)

from telemetry.event_bus import EventBus, ListSubscriber  # noqa: E402
from telemetry.events import EventType, ExecutionEvent  # noqa: E402
from telemetry.telemetry import TelemetryRecorder, TelemetryRecord  # noqa: E402


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def recorder(bus: EventBus) -> TelemetryRecorder:
    return TelemetryRecorder(bus)


def _emit_full_execution(bus: EventBus, trace_id: str = "trace-full-1") -> None:
    bus.emit(
        EventType.INTENT_RECEIVED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"model": "deepseek-v4", "provider": "ollama-cloud"},
    )
    bus.emit(
        EventType.CAPABILITY_SELECTED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"capability_ids": ["cap-search", "cap-rag"]},
    )
    bus.emit(
        EventType.RECIPE_RETRIEVED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"recipe_id": "recipe-web-search", "recipe_version": "1.3.0"},
    )
    bus.emit(
        EventType.TOOL_CALLED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"tool": "web_search", "args": {"q": "elastic web"}},
    )
    bus.emit(
        EventType.TOOL_COMPLETED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"tool": "web_search", "status": "completed", "duration": 0.42},
    )
    bus.emit(
        EventType.OUTCOME_DELIVERED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"outcome": "delivered"},
    )


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


def test_bus_delivers_events_in_order(bus):
    collector = ListSubscriber()
    bus.subscribe(collector)
    bus.emit(EventType.INTENT_RECEIVED, trace_id="t1")
    bus.emit(EventType.TOOL_CALLED, trace_id="t1")
    assert collector.event_types == ["intent.received", "tool.called"]


def test_bus_unsubscribe_stops_delivery(bus):
    collector = ListSubscriber()
    bus.subscribe(collector)
    bus.unsubscribe(collector)
    bus.emit(EventType.INTENT_RECEIVED, trace_id="t1")
    assert collector.events == []


def test_emit_returns_execution_event(bus):
    event = bus.emit(EventType.INTENT_RECEIVED, trace_id="t1", intent_id="i1")
    assert isinstance(event, ExecutionEvent)
    assert event.trace_id == "t1"
    assert event.intent_id == "i1"
    assert event.payload == {}


# ---------------------------------------------------------------------------
# Telemetry recorder
# ---------------------------------------------------------------------------


def test_full_execution_produces_complete_record(bus, recorder):
    _emit_full_execution(bus)
    records = recorder.records()
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, TelemetryRecord)
    assert record.trace_id == "trace-full-1"
    assert record.intent_id == "intent-42"
    assert record.recipe_id == "recipe-web-search"
    assert record.recipe_version == "1.3.0"
    assert record.capability_ids == ["cap-search", "cap-rag"]
    assert record.model == "deepseek-v4"
    assert record.provider == "ollama-cloud"
    assert len(record.tool_calls) == 1
    assert record.tool_calls[0].name == "web_search"
    assert record.tool_calls[0].status == "completed"
    assert record.tool_calls[0].duration == 0.42
    assert record.outcome == "delivered"
    assert record.started_at is not None
    assert record.completed_at is not None
    assert record.completed_at >= record.started_at


def test_failed_execution_records_error_and_outcome(bus, recorder):
    bus.emit(EventType.INTENT_RECEIVED, trace_id="trace-fail-1", intent_id="intent-7")
    bus.emit(
        EventType.EXECUTION_FAILED,
        trace_id="trace-fail-1",
        intent_id="intent-7",
        payload={"error": "recipe not found"},
    )
    record = recorder.records()[0]
    assert record.outcome == "failed"
    assert record.errors == ["recipe not found"]


def test_export_json_is_valid(bus, recorder):
    _emit_full_execution(bus)
    payload = recorder.export_json()
    parsed = json.loads(payload)
    assert isinstance(parsed, list)
    assert parsed[0]["trace_id"] == "trace-full-1"
    assert parsed[0]["outcome"] == "delivered"


def test_export_to_file_writes_json(bus, recorder, tmp_path):
    _emit_full_execution(bus)
    target = tmp_path / "telemetry.json"
    payload = recorder.export_to_file(str(target))
    assert target.exists()
    assert json.loads(payload) == json.loads(target.read_text(encoding="utf-8"))


def test_get_returns_none_for_missing_trace(bus, recorder):
    _emit_full_execution(bus)
    assert recorder.get("missing-trace") is None


def test_recorder_clear_drops_records(bus, recorder):
    _emit_full_execution(bus)
    assert len(recorder.records()) == 1
    recorder.clear()
    assert recorder.records() == []
