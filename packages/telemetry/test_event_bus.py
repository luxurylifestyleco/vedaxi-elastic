"""Tests for the Elastic Web execution event bus."""

import pytest

from .event_bus import EventBus, ListSubscriber
from .events import EventType, ExecutionEvent

ALL_EVENT_TYPES = [
    EventType.INTENT_RECEIVED,
    EventType.INTENT_COMPILED,
    EventType.CAPABILITY_DISCOVERY_STARTED,
    EventType.CAPABILITY_CANDIDATES,
    EventType.CAPABILITY_SELECTED,
    EventType.RECIPE_RETRIEVED,
    EventType.RECIPE_STARTED,
    EventType.RECIPE_STEP_STARTED,
    EventType.TOOL_CALLED,
    EventType.TOOL_COMPLETED,
    EventType.RECIPE_COMPLETED,
    EventType.OUTCOME_DELIVERED,
    EventType.EVALUATION_COMPLETED,
    EventType.EXECUTION_FAILED,
]


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def collector() -> ListSubscriber:
    return ListSubscriber()


def test_all_event_types_are_defined() -> None:
    """The enum must expose every required event type."""
    expected = {
        "intent.received",
        "intent.compiled",
        "capability.discovery.started",
        "capability.candidates",
        "capability.selected",
        "recipe.retrieved",
        "recipe.started",
        "recipe.step.started",
        "tool.called",
        "tool.completed",
        "recipe.completed",
        "outcome.delivered",
        "evaluation.completed",
        "execution.failed",
    }
    assert {e.value for e in EventType} == expected


def test_every_event_type_is_collected_with_trace_id(
    bus: EventBus, collector: ListSubscriber
) -> None:
    """Emitting every event type collects them all with the same trace id."""
    bus.subscribe(collector)
    trace_id = "trace-abc-123"

    for event_type in ALL_EVENT_TYPES:
        bus.emit(event_type, trace_id=trace_id, intent_id="intent-1")

    assert len(collector.events) == len(ALL_EVENT_TYPES)
    assert collector.event_types == ALL_EVENT_TYPES
    assert all(e.trace_id == trace_id for e in collector.events)
    assert all(e.intent_id == "intent-1" for e in collector.events)


def test_events_are_collected_in_emission_order(
    bus: EventBus, collector: ListSubscriber
) -> None:
    """Events must be delivered in the order they were emitted."""
    bus.subscribe(collector)
    trace_id = "trace-order-1"

    for event_type in ALL_EVENT_TYPES:
        bus.emit(event_type, trace_id=trace_id)

    assert collector.event_types == ALL_EVENT_TYPES


def test_event_has_timestamp_and_payload(
    bus: EventBus, collector: ListSubscriber
) -> None:
    """Each event carries a timestamp and the supplied payload."""
    bus.subscribe(collector)
    bus.emit(
        EventType.TOOL_CALLED,
        trace_id="trace-ts-1",
        intent_id="intent-9",
        payload={"tool": "search", "args": {"q": "x"}},
    )

    event = collector.events[0]
    assert isinstance(event, ExecutionEvent)
    assert event.timestamp > 0
    assert event.payload == {"tool": "search", "args": {"q": "x"}}


def test_emit_returns_the_constructed_event(
    bus: EventBus, collector: ListSubscriber
) -> None:
    """emit() returns the event so producers can inspect it."""
    bus.subscribe(collector)
    event = bus.emit(EventType.RECIPE_STARTED, trace_id="trace-ret-1")
    assert isinstance(event, ExecutionEvent)
    assert event.event_type == EventType.RECIPE_STARTED
    assert event.trace_id == "trace-ret-1"


def test_unsubscribe_stops_delivery(
    bus: EventBus, collector: ListSubscriber
) -> None:
    """A removed subscriber no longer receives events."""
    bus.subscribe(collector)
    bus.emit(EventType.INTENT_RECEIVED, trace_id="trace-u-1")
    bus.unsubscribe(collector)
    bus.emit(EventType.INTENT_COMPILED, trace_id="trace-u-1")
    assert len(collector.events) == 1
    assert collector.events[0].event_type == EventType.INTENT_RECEIVED
