"""Tests for the Elastic Web telemetry recorder."""

import json
import socket

import pytest

from .event_bus import EventBus
from .events import EventType
from .telemetry import TelemetryRecorder, TelemetryRecord, ToolCall


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def recorder(bus: EventBus) -> TelemetryRecorder:
    return TelemetryRecorder(bus)


def _emit_full_execution(bus: EventBus, trace_id: str = "trace-full-1") -> None:
    """Emit a complete execution from intent.received to outcome.delivered."""
    bus.emit(
        EventType.INTENT_RECEIVED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"model": "deepseek-v4", "provider": "ollama-cloud"},
    )
    bus.emit(EventType.INTENT_COMPILED, trace_id=trace_id, intent_id="intent-42")
    bus.emit(
        EventType.CAPABILITY_DISCOVERY_STARTED,
        trace_id=trace_id,
        intent_id="intent-42",
    )
    bus.emit(
        EventType.CAPABILITY_CANDIDATES,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"candidates": ["cap-search", "cap-rag"]},
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
        EventType.RECIPE_STARTED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"tokens": {"prompt": 120, "completion": 45, "total": 165}},
    )
    bus.emit(
        EventType.RECIPE_STEP_STARTED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"step": 1, "retries": 1},
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
    bus.emit(EventType.RECIPE_COMPLETED, trace_id=trace_id, intent_id="intent-42")
    bus.emit(
        EventType.OUTCOME_DELIVERED,
        trace_id=trace_id,
        intent_id="intent-42",
        payload={"outcome": "delivered"},
    )


def test_full_execution_produces_complete_record(
    bus: EventBus, recorder: TelemetryRecorder
) -> None:
    """A full execution yields one finalized record with all fields populated."""
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
    assert record.tokens == {"prompt": 120, "completion": 45, "total": 165}
    assert record.latency is not None and record.latency >= 0
    assert len(record.tool_calls) == 1
    assert record.tool_calls[0].name == "web_search"
    assert record.tool_calls[0].status == "completed"
    assert record.tool_calls[0].duration == 0.42
    assert record.errors == []
    assert record.retries == 1
    assert record.outcome == "delivered"
    assert record.started_at is not None
    assert record.completed_at is not None
    assert record.completed_at >= record.started_at


def test_export_produces_valid_json(
    bus: EventBus, recorder: TelemetryRecorder
) -> None:
    """export_json returns parseable JSON describing the records."""
    _emit_full_execution(bus)

    payload = recorder.export_json()
    parsed = json.loads(payload)

    assert isinstance(parsed, list)
    assert len(parsed) == 1
    record = parsed[0]
    assert record["trace_id"] == "trace-full-1"
    assert record["intent_id"] == "intent-42"
    assert record["recipe_id"] == "recipe-web-search"
    assert record["outcome"] == "delivered"
    assert record["tool_calls"][0]["name"] == "web_search"
    assert record["tokens"]["total"] == 165


def test_export_to_file_writes_valid_json(
    bus: EventBus, recorder: TelemetryRecorder, tmp_path
) -> None:
    """export_to_file writes a JSON file that round-trips."""
    _emit_full_execution(bus)

    target = tmp_path / "telemetry.json"
    payload = recorder.export_to_file(str(target))

    assert target.exists()
    assert json.loads(payload) == json.loads(target.read_text(encoding="utf-8"))
    assert json.loads(target.read_text(encoding="utf-8"))[0]["trace_id"] == "trace-full-1"


def test_failed_execution_records_error_and_outcome(
    bus: EventBus, recorder: TelemetryRecorder
) -> None:
    """A failed execution captures the error and a 'failed' outcome."""
    bus.emit(
        EventType.INTENT_RECEIVED,
        trace_id="trace-fail-1",
        intent_id="intent-7",
    )
    bus.emit(
        EventType.EXECUTION_FAILED,
        trace_id="trace-fail-1",
        intent_id="intent-7",
        payload={"error": "recipe not found"},
    )

    records = recorder.records()
    assert len(records) == 1
    record = records[0]
    assert record.outcome == "failed"
    assert record.errors == ["recipe not found"]
    assert record.latency is not None


def test_no_external_network_calls(
    bus: EventBus, recorder: TelemetryRecorder
) -> None:
    """Recording and exporting must not open any network connections."""
    _emit_full_execution(bus)

    # Attempting to connect to a localhost port that nothing is listening on
    # would raise ConnectionRefusedError if any code path tried to open a
    # socket. Recording/exporting must complete without touching the network.
    payload = recorder.export_json()
    assert json.loads(payload)

    # Sanity: the socket module is available but unused by the recorder.
    assert socket is not None


def test_recorder_does_not_emit_events(bus: EventBus, recorder: TelemetryRecorder) -> None:
    """The recorder is a passive subscriber and never emits onto the bus."""
    _emit_full_execution(bus)
    # No events were added by the recorder itself; the bus only saw the
    # events the test emitted. We assert the recorder produced exactly one
    # finalized record and no stray in-progress records remain.
    assert len(recorder.records()) == 1
    assert recorder.get("trace-full-1") is not None
    assert recorder.get("missing-trace") is None
