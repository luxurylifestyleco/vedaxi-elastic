"""Unit tests for DatabaseTelemetryRecorder."""

import os
from unittest.mock import patch

import pytest

from .db_recorder import DatabaseTelemetryRecorder
from .event_bus import EventBus
from .events import EventType


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def memory_recorder(bus: EventBus) -> DatabaseTelemetryRecorder:
    recorder = DatabaseTelemetryRecorder(bus=bus, db_path=":memory:", force_sqlite=True)
    yield recorder
    recorder.close()


def _emit_full_execution(bus: EventBus, trace_id: str = "trace-test-1") -> None:
    """Emit a complete execution flow from INTENT_RECEIVED to OUTCOME_DELIVERED."""
    bus.emit(
        EventType.INTENT_RECEIVED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={
            "input": {"query": "test transfer $50"},
            "model": "deepseek-v4",
            "provider": "ollama-cloud",
        },
        timestamp=100.0,
    )
    bus.emit(
        EventType.CAPABILITY_SELECTED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={"capability_ids": ["bank.transfer"]},
        timestamp=100.1,
    )
    bus.emit(
        EventType.RECIPE_RETRIEVED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={"recipe_id": "monthly-budget-review", "recipe_version": 1},
        timestamp=100.2,
    )
    bus.emit(
        EventType.RECIPE_STARTED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={"tokens": {"prompt": 80, "completion": 20, "total": 100}},
        timestamp=100.3,
    )
    bus.emit(
        EventType.RECIPE_STEP_STARTED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={"step": 1, "step_key": "step-fetch", "input": {"acc": "123"}},
        timestamp=100.4,
    )
    bus.emit(
        EventType.TOOL_CALLED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={"tool": "bank.transactions", "args": {"acc": "123"}},
        timestamp=100.5,
    )
    bus.emit(
        EventType.TOOL_COMPLETED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={
            "tool": "bank.transactions",
            "status": "completed",
            "duration": 0.42,
            "output": {"transactions": [1, 2]},
        },
        timestamp=100.92,
    )
    bus.emit(
        EventType.RECIPE_COMPLETED,
        trace_id=trace_id,
        intent_id="intent-101",
        timestamp=101.0,
    )
    bus.emit(
        EventType.OUTCOME_DELIVERED,
        trace_id=trace_id,
        intent_id="intent-101",
        payload={"output": {"status": "success", "summary": "completed"}},
        timestamp=101.5,
    )


def test_sqlite_in_memory_initialization(memory_recorder: DatabaseTelemetryRecorder) -> None:
    """Recorder initializes in-memory with empty tables and correct backend."""
    assert memory_recorder.backend == "sqlite"
    traces = memory_recorder.list_traces()
    assert traces == []
    assert memory_recorder.get_trace("nonexistent") is None


def test_full_execution_records_trace_and_steps(
    bus: EventBus, memory_recorder: DatabaseTelemetryRecorder
) -> None:
    """Full execution records trace fields, steps, durations, and output."""
    trace_id = "trace-test-1"
    _emit_full_execution(bus, trace_id=trace_id)

    trace = memory_recorder.get_trace(trace_id)
    assert trace is not None
    assert trace["trace_id"] == trace_id
    assert trace["status"] == "succeeded"
    assert trace["recipe_id"] == "monthly-budget-review"
    assert trace["recipe_version"] == 1
    assert trace["trigger"] == "user"
    assert trace["input"] == {"query": "test transfer $50"}
    assert trace["output"] == {"status": "success", "summary": "completed"}
    assert trace["error"] is None
    assert trace["started_at"] is not None
    assert trace["finished_at"] is not None
    assert trace["duration_ms"] == 1500  # (101.5 - 100.0) * 1000

    metadata = trace["metadata"]
    assert metadata.get("intent_id") == "intent-101"
    assert metadata.get("model") == "deepseek-v4"
    assert metadata.get("provider") == "ollama-cloud"
    assert metadata.get("capability_ids") == ["bank.transfer"]
    assert metadata.get("tokens") == {"prompt": 80, "completion": 20, "total": 100}

    # Verify steps
    steps = memory_recorder.get_trace_steps(trace_id)
    assert len(steps) == 2

    # Step 1: recipe step
    recipe_step = steps[0]
    assert recipe_step["step_key"] == "step-fetch"
    assert recipe_step["step_type"] == "step"
    assert recipe_step["status"] == "succeeded"
    assert recipe_step["input"] == {"acc": "123"}

    # Step 2: tool step
    tool_step = steps[1]
    assert tool_step["step_key"] == "bank.transactions"
    assert tool_step["step_type"] == "tool"
    assert tool_step["status"] == "succeeded"
    assert tool_step["input"] == {"acc": "123"}
    assert tool_step["output"] == {"transactions": [1, 2]}
    assert tool_step["duration_ms"] == 420  # 0.42 * 1000


def test_failed_execution_updates_status_and_errors(
    bus: EventBus, memory_recorder: DatabaseTelemetryRecorder
) -> None:
    """Terminal EXECUTION_FAILED marks trace and pending steps as failed."""
    trace_id = "trace-fail-10"
    bus.emit(
        EventType.INTENT_RECEIVED,
        trace_id=trace_id,
        intent_id="intent-fail",
        payload={"input": {"action": "fail_test"}},
        timestamp=200.0,
    )
    bus.emit(
        EventType.TOOL_CALLED,
        trace_id=trace_id,
        payload={"tool": "broken_tool", "args": {"flag": True}},
        timestamp=200.2,
    )
    bus.emit(
        EventType.EXECUTION_FAILED,
        trace_id=trace_id,
        payload={"error": {"code": "TIMEOUT", "message": "Operation timed out"}},
        timestamp=201.2,
    )

    trace = memory_recorder.get_trace(trace_id)
    assert trace is not None
    assert trace["status"] == "failed"
    assert trace["error"] == {"code": "TIMEOUT", "message": "Operation timed out"}
    assert trace["duration_ms"] == 1200

    steps = memory_recorder.get_trace_steps(trace_id)
    assert len(steps) == 1
    assert steps[0]["step_key"] == "broken_tool"
    assert steps[0]["status"] == "failed"


def test_failed_tool_step_recorded(
    bus: EventBus, memory_recorder: DatabaseTelemetryRecorder
) -> None:
    """Tool completion with failure status is recorded as failed."""
    trace_id = "trace-tool-fail"
    bus.emit(EventType.INTENT_RECEIVED, trace_id=trace_id, timestamp=300.0)
    bus.emit(
        EventType.TOOL_CALLED,
        trace_id=trace_id,
        payload={"tool": "flaky_tool"},
        timestamp=300.1,
    )
    bus.emit(
        EventType.TOOL_COMPLETED,
        trace_id=trace_id,
        payload={
            "tool": "flaky_tool",
            "status": "error",
            "error": "connection refused",
            "duration": 0.25,
        },
        timestamp=300.35,
    )

    steps = memory_recorder.get_trace_steps(trace_id)
    assert len(steps) == 1
    assert steps[0]["step_key"] == "flaky_tool"
    assert steps[0]["status"] == "failed"
    assert steps[0]["error"] == "connection refused"
    assert steps[0]["duration_ms"] == 250


def test_list_traces_pagination(
    bus: EventBus, memory_recorder: DatabaseTelemetryRecorder
) -> None:
    """list_traces honors limit and offset parameters."""
    for i in range(5):
        bus.emit(
            EventType.INTENT_RECEIVED,
            trace_id=f"trace-page-{i}",
            payload={"index": i},
            timestamp=400.0 + i,
        )

    all_traces = memory_recorder.list_traces(limit=50, offset=0)
    assert len(all_traces) == 5

    page1 = memory_recorder.list_traces(limit=2, offset=0)
    assert len(page1) == 2
    assert page1[0]["trace_id"] == "trace-page-4"
    assert page1[1]["trace_id"] == "trace-page-3"

    page2 = memory_recorder.list_traces(limit=2, offset=2)
    assert len(page2) == 2
    assert page2[0]["trace_id"] == "trace-page-2"
    assert page2[1]["trace_id"] == "trace-page-1"

    page3 = memory_recorder.list_traces(limit=2, offset=4)
    assert len(page3) == 1
    assert page3[0]["trace_id"] == "trace-page-0"


def test_persistent_file_database(bus: EventBus, tmp_path) -> None:
    """Traces and steps persist to SQLite file and reload in a new instance."""
    db_file = str(tmp_path / "persist_test.db")
    recorder1 = DatabaseTelemetryRecorder(bus=bus, db_path=db_file, force_sqlite=True)

    _emit_full_execution(bus, trace_id="trace-persist-1")
    recorder1.close()

    assert os.path.exists(db_file)

    # Open with a fresh recorder instance pointing to the same file
    recorder2 = DatabaseTelemetryRecorder(db_path=db_file, force_sqlite=True)
    trace = recorder2.get_trace("trace-persist-1")
    assert trace is not None
    assert trace["recipe_id"] == "monthly-budget-review"
    assert trace["status"] == "succeeded"

    steps = recorder2.get_trace_steps("trace-persist-1")
    assert len(steps) == 2
    assert steps[1]["step_key"] == "bank.transactions"
    recorder2.close()


def test_direct_callable_subscriber(bus: EventBus) -> None:
    """Recorder can be registered directly as a callable subscriber."""
    recorder = DatabaseTelemetryRecorder(db_path=":memory:", force_sqlite=True)
    bus.subscribe(recorder)

    bus.emit(
        EventType.INTENT_RECEIVED,
        trace_id="trace-callable-1",
        payload={"msg": "hello"},
    )
    trace = recorder.get_trace("trace-callable-1")
    assert trace is not None
    assert trace["trace_id"] == "trace-callable-1"

    recorder.close()


def test_clear_drops_all_data(
    bus: EventBus, memory_recorder: DatabaseTelemetryRecorder
) -> None:
    """clear() removes all execution traces and steps."""
    _emit_full_execution(bus, trace_id="trace-clear-1")
    assert len(memory_recorder.list_traces()) == 1
    assert len(memory_recorder.get_trace_steps("trace-clear-1")) == 2

    memory_recorder.clear()
    assert len(memory_recorder.list_traces()) == 0
    assert len(memory_recorder.get_trace_steps("trace-clear-1")) == 0


def test_postgres_fallback_when_unavailable() -> None:
    """When PostgreSQL connection fails, recorder falls back to SQLite."""
    with patch.object(
        DatabaseTelemetryRecorder,
        "_connect_postgres",
        side_effect=Exception("Connection refused on 5432"),
    ):
        recorder = DatabaseTelemetryRecorder(db_path=":memory:")
        assert recorder.backend == "sqlite"
        recorder.close()

