"""Execution event schema for Elastic Web telemetry.

This module defines the structured event model emitted by the execution
event bus. It is intentionally independent of any UI layer so that
telemetry can be consumed by tests, analytics, or future sinks without
coupling to presentation concerns.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """The canonical set of execution event types."""

    INTENT_RECEIVED = "intent.received"
    INTENT_COMPILED = "intent.compiled"
    CAPABILITY_DISCOVERY_STARTED = "capability.discovery.started"
    CAPABILITY_CANDIDATES = "capability.candidates"
    CAPABILITY_SELECTED = "capability.selected"
    RECIPE_RETRIEVED = "recipe.retrieved"
    RECIPE_STARTED = "recipe.started"
    RECIPE_STEP_STARTED = "recipe.step.started"
    TOOL_CALLED = "tool.called"
    TOOL_COMPLETED = "tool.completed"
    RECIPE_COMPLETED = "recipe.completed"
    OUTCOME_DELIVERED = "outcome.delivered"
    EVALUATION_COMPLETED = "evaluation.completed"
    EXECUTION_FAILED = "execution.failed"


class ExecutionEvent(BaseModel):
    """A single structured execution telemetry event.

    Attributes:
        event_type: The kind of event (see :class:`EventType`).
        trace_id: Correlation id shared across all events of one execution.
        intent_id: The id of the intent this event belongs to.
        timestamp: Epoch seconds (float) when the event was emitted.
        payload: Arbitrary structured data attached to the event.
    """

    event_type: EventType
    trace_id: str
    intent_id: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)
