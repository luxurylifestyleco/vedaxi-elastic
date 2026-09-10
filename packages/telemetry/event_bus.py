"""Execution event bus for Elastic Web telemetry.

The bus decouples event producers (execution pipeline stages) from
consumers (subscribers). Events are emitted with a trace id and
timestamp; subscribers receive them in emission order.

An in-memory :class:`ListSubscriber` is provided so tests can collect
and assert on emitted events without any external telemetry sink.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from .events import EventType, ExecutionEvent

# A subscriber is any callable that accepts an ExecutionEvent.
Subscriber = Callable[[ExecutionEvent], None]


class EventBus:
    """Publish/subscribe bus for execution events."""

    def __init__(self) -> None:
        self._subscribers: List[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        """Register a subscriber to receive every emitted event."""
        if subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        """Remove a previously registered subscriber."""
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def emit(
        self,
        event_type: EventType,
        trace_id: str,
        intent_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> ExecutionEvent:
        """Build and dispatch an event to all subscribers.

        Returns the constructed event so producers can inspect it.
        """
        event = ExecutionEvent(
            event_type=event_type,
            trace_id=trace_id,
            intent_id=intent_id,
            timestamp=timestamp if timestamp is not None else time.time(),
            payload=payload or {},
        )
        for subscriber in list(self._subscribers):
            subscriber(event)
        return event


class ListSubscriber:
    """In-memory subscriber that collects events into a list.

    Useful for tests and lightweight local consumers. Events are
    appended in emission order.
    """

    def __init__(self) -> None:
        self.events: List[ExecutionEvent] = []

    def __call__(self, event: ExecutionEvent) -> None:
        self.events.append(event)

    @property
    def event_types(self) -> List[EventType]:
        """The event types collected, in emission order."""
        return [e.event_type for e in self.events]

    def clear(self) -> None:
        """Drop all collected events."""
        self.events.clear()
