"""Structured execution telemetry for Elastic Web.

The :class:`TelemetryRecorder` wraps an :class:`EventBus`, subscribes to
every emitted event, and folds them into per-execution
:class:`TelemetryRecord` objects held in an in-memory store. Records are
finalized when an execution reaches a terminal event
(``outcome.delivered`` or ``execution.failed``) and can be exported as
JSON for local inspection.

Telemetry is intentionally local-only: nothing here performs network I/O
or sends data to any external sink. Export writes to a caller-supplied
path or returns a JSON string.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .event_bus import EventBus
from .events import EventType, ExecutionEvent

# Terminal events that finalize a record.
_TERMINAL_EVENTS = {
    EventType.OUTCOME_DELIVERED,
    EventType.EXECUTION_FAILED,
}


class ToolCall(BaseModel):
    """A single tool invocation recorded during an execution."""

    name: str
    status: str = "called"  # "called" | "completed" | "failed"
    duration: Optional[float] = None


class TelemetryRecord(BaseModel):
    """Structured telemetry for one execution.

    Attributes:
        trace_id: Correlation id shared across all events of the execution.
        intent_id: The id of the intent being executed.
        recipe_id: The id of the recipe selected for the intent.
        recipe_version: The version of the selected recipe.
        capability_ids: Ids of the capabilities selected for the execution.
        model: The model used to drive the execution (if reported).
        provider: The model provider (if reported).
        tokens: Token usage, e.g. ``{"prompt": n, "completion": n, "total": n}``.
        latency: Wall-clock seconds from first to terminal event.
        tool_calls: Ordered list of tool invocations.
        errors: Error messages captured during the execution.
        retries: Number of retries observed during the execution.
        outcome: Terminal outcome, e.g. ``"delivered"`` or ``"failed"``.
        started_at: Epoch seconds of the first observed event.
        completed_at: Epoch seconds of the terminal event.
    """

    trace_id: str
    intent_id: Optional[str] = None
    recipe_id: Optional[str] = None
    recipe_version: Optional[str] = None
    capability_ids: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    provider: Optional[str] = None
    protocol_metadata: Dict[str, Any] = Field(default_factory=dict)
    tokens: Dict[str, Any] = Field(default_factory=dict)
    latency: Optional[float] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    retries: int = 0
    outcome: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class TelemetryRecorder:
    """Subscribe to an :class:`EventBus` and record per-execution telemetry.

    The recorder keeps an in-memory map of in-progress records keyed by
    ``trace_id``. Each emitted event updates the matching record; a
    terminal event finalizes it and moves it into the completed store.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._records: Dict[str, TelemetryRecord] = {}
        self._completed: List[TelemetryRecord] = []
        bus.subscribe(self._on_event)

    # -- public API -----------------------------------------------------

    def records(self) -> List[TelemetryRecord]:
        """All finalized records, in completion order."""
        return list(self._completed)

    def get(self, trace_id: str) -> Optional[TelemetryRecord]:
        """Return a finalized record by trace id, or ``None``."""
        for record in self._completed:
            if record.trace_id == trace_id:
                return record
        return None

    def export_json(self, indent: int = 2) -> str:
        """Serialize all finalized records to a JSON string."""
        return json.dumps(
            [r.model_dump() for r in self._completed],
            indent=indent,
            default=str,
        )

    def export_to_file(self, path: str, indent: int = 2) -> str:
        """Write finalized records as JSON to ``path`` and return the JSON."""
        payload = self.export_json(indent=indent)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return payload

    def clear(self) -> None:
        """Drop all in-progress and completed records."""
        self._records.clear()
        self._completed.clear()

    # -- event handling -------------------------------------------------

    def _on_event(self, event: ExecutionEvent) -> None:
        record = self._records.get(event.trace_id)
        if record is None:
            record = TelemetryRecord(trace_id=event.trace_id)
            self._records[event.trace_id] = record
        if record.started_at is None:
            record.started_at = event.timestamp

        self._apply(event, record)

        if event.event_type in _TERMINAL_EVENTS:
            record.completed_at = event.timestamp
            if record.latency is None and record.started_at is not None:
                record.latency = record.completed_at - record.started_at
            if record.outcome is None:
                record.outcome = (
                    "delivered"
                    if event.event_type == EventType.OUTCOME_DELIVERED
                    else "failed"
                )
            self._completed.append(record)
            self._records.pop(event.trace_id, None)

    def _apply(self, event: ExecutionEvent, record: TelemetryRecord) -> None:
        payload = event.payload or {}
        protocol = payload.get("protocol")
        if isinstance(protocol, dict):
            record.protocol_metadata.update(protocol)

        if event.event_type == EventType.INTENT_RECEIVED:
            if event.intent_id:
                record.intent_id = event.intent_id
            self._capture_model(record, payload)

        elif event.event_type == EventType.CAPABILITY_SELECTED:
            self._extend(record.capability_ids, payload, "capability_ids")
            self._extend(record.capability_ids, payload, "capability_id")

        elif event.event_type == EventType.RECIPE_RETRIEVED:
            record.recipe_id = self._first(payload, "recipe_id", "recipe")
            record.recipe_version = self._first(
                payload, "recipe_version", "version"
            )

        elif event.event_type == EventType.TOOL_CALLED:
            name = self._first(payload, "tool", "name", "tool_name")
            record.tool_calls.append(ToolCall(name=name or "unknown"))

        elif event.event_type == EventType.TOOL_COMPLETED:
            self._complete_tool(record, payload)

        elif event.event_type == EventType.EXECUTION_FAILED:
            error = self._first(payload, "error", "message", "reason")
            if error:
                record.errors.append(str(error))

        elif event.event_type == EventType.RECIPE_STEP_STARTED:
            retries = payload.get("retries")
            if isinstance(retries, int):
                record.retries = max(record.retries, retries)

        # Model/provider/tokens may arrive on any event payload.
        self._capture_model(record, payload)
        self._capture_tokens(record, payload)

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _first(payload: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return None

    @staticmethod
    def _extend(target: List[str], payload: Dict[str, Any], key: str) -> None:
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if item not in target:
                    target.append(str(item))
        elif value is not None and str(value) not in target:
            target.append(str(value))

    def _capture_model(self, record: TelemetryRecord, payload: Dict[str, Any]) -> None:
        if record.model is None:
            record.model = self._first(payload, "model", "model_name")
        if record.provider is None:
            record.provider = self._first(payload, "provider", "model_provider")

    def _capture_tokens(self, record: TelemetryRecord, payload: Dict[str, Any]) -> None:
        tokens = payload.get("tokens") or payload.get("token_usage")
        if isinstance(tokens, dict):
            for key, value in tokens.items():
                if key not in record.tokens:
                    record.tokens[key] = value
        elif isinstance(tokens, int) and "total" not in record.tokens:
            record.tokens["total"] = tokens

    def _complete_tool(self, record: TelemetryRecord, payload: Dict[str, Any]) -> None:
        name = self._first(payload, "tool", "name", "tool_name")
        status = self._first(payload, "status", "result")
        if status is None:
            status = "completed"
        if isinstance(status, str) and status.lower() in {"error", "failed", "failure"}:
            status = "failed"
        else:
            status = "completed"
        for tool in reversed(record.tool_calls):
            if tool.name == (name or tool.name) and tool.status == "called":
                tool.status = status
                tool.duration = payload.get("duration")
                return
        # No matching open call; record it as a standalone completion.
        record.tool_calls.append(ToolCall(name=name or "unknown", status=status))
