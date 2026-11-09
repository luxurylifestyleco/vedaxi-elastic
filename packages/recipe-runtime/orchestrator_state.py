"""Checkpoint-safe state for the Elastic master orchestration graph.

The state contains only JSON values so it can be used directly as a LangGraph
state schema and persisted by a strict checkpointer.
"""

from __future__ import annotations

import json
from typing import Literal, Mapping, NotRequired, TypedDict, cast


SCHEMA_VERSION = "elastic-orchestrator-state.v1"
TERMINAL_TASK_STATUSES = frozenset({"VERIFIED", "CLOSED"})

TaskStatus = Literal[
    "QUEUED",
    "RUNNING",
    "REPORTED",
    "VERIFIED",
    "CLOSED",
    "FAILED",
    "BLOCKED",
]


class TaskLedgerEntry(TypedDict):
    task_id: str
    scope: str
    status: TaskStatus
    fingerprint: str
    source_revision: str
    owner: str
    evidence_ids: list[str]
    changed_paths: list[str]
    next_action: str


class WorkerLease(TypedDict):
    worker_id: str
    task_id: str
    lease_id: str
    status: Literal["ACTIVE", "RELEASED", "EXPIRED"]
    acquired_at: str
    expires_at: str


class EvidenceClaim(TypedDict):
    claim_id: str
    task_id: str
    statement: str
    source: str
    source_revision: str
    verified: bool


class Blocker(TypedDict):
    blocker_id: str
    task_id: NotRequired[str]
    reason: str
    required_action: str
    status: Literal["OPEN", "RESOLVED"]


class NextAction(TypedDict):
    task_id: str
    action: str


class OrchestratorState(TypedDict, total=False):
    schema_version: str
    project_objective: str
    canonical_source_revision: str
    lane_cursor: int
    task_ledger: dict[str, TaskLedgerEntry]
    worker_leases: dict[str, WorkerLease]
    evidence_claims: dict[str, EvidenceClaim]
    blockers: dict[str, Blocker]
    next_action: NextAction | None


class ResumeDelta(TypedDict):
    source_revision_changed: bool
    changed_task_ids: list[str]
    unchanged_task_ids: list[str]
    resume_task_ids: list[str]
    removed_task_ids: list[str]


def new_orchestrator_state(
    project_objective: str,
    canonical_source_revision: str,
    *,
    lane_cursor: int = 0,
    next_action: NextAction | None = None,
) -> OrchestratorState:
    """Create a complete, empty state suitable for a first graph checkpoint."""

    if not project_objective or not canonical_source_revision:
        raise ValueError("project objective and source revision are required")
    if lane_cursor < 0:
        raise ValueError("lane cursor cannot be negative")
    return {
        "schema_version": SCHEMA_VERSION,
        "project_objective": project_objective,
        "canonical_source_revision": canonical_source_revision,
        "lane_cursor": lane_cursor,
        "task_ledger": {},
        "worker_leases": {},
        "evidence_claims": {},
        "blockers": {},
        "next_action": next_action,
    }


def serialize_state(state: Mapping[str, object]) -> str:
    """Return deterministic JSON for a LangGraph checkpointer."""

    _validate_state(state)
    try:
        return json.dumps(state, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("orchestrator state must contain only JSON values") from exc


def deserialize_state(payload: str | bytes) -> OrchestratorState:
    """Decode and validate a checkpoint without restoring executable objects."""

    try:
        value = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid orchestrator checkpoint JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("orchestrator checkpoint must be a JSON object")
    _validate_state(value)
    return cast(OrchestratorState, value)


def resume_delta(
    checkpoint: Mapping[str, object], current: Mapping[str, object]
) -> ResumeDelta:
    """Identify work that needs analysis after a checkpoint restore.

    A task is unchanged only when its fingerprint and source revision still
    match and it reached a terminal verified state. Everything else resumes.
    """

    _validate_state(checkpoint)
    _validate_state(current)
    previous_tasks = cast(dict[str, TaskLedgerEntry], checkpoint["task_ledger"])
    current_tasks = cast(dict[str, TaskLedgerEntry], current["task_ledger"])
    current_revision = cast(str, current["canonical_source_revision"])
    source_revision_changed = (
        checkpoint["canonical_source_revision"] != current_revision
    )

    changed: list[str] = []
    unchanged: list[str] = []
    for task_id, task in current_tasks.items():
        previous = previous_tasks.get(task_id)
        same_inputs = (
            previous is not None
            and previous["fingerprint"] == task["fingerprint"]
            and previous["source_revision"] == task["source_revision"] == current_revision
        )
        if same_inputs and task["status"] in TERMINAL_TASK_STATUSES:
            unchanged.append(task_id)
        else:
            changed.append(task_id)

    removed = sorted(set(previous_tasks) - set(current_tasks))
    return {
        "source_revision_changed": source_revision_changed,
        "changed_task_ids": changed,
        "unchanged_task_ids": unchanged,
        "resume_task_ids": changed,
        "removed_task_ids": removed,
    }


def _validate_state(state: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "project_objective",
        "canonical_source_revision",
        "lane_cursor",
        "task_ledger",
        "worker_leases",
        "evidence_claims",
        "blockers",
        "next_action",
    }
    missing = required - set(state)
    if missing:
        raise ValueError(f"orchestrator state missing fields: {sorted(missing)}")
    if state["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported orchestrator state: {state['schema_version']!r}")
    if not isinstance(state["project_objective"], str) or not state["project_objective"]:
        raise ValueError("project objective must be a non-empty string")
    if not isinstance(state["canonical_source_revision"], str) or not state[
        "canonical_source_revision"
    ]:
        raise ValueError("canonical source revision must be a non-empty string")
    if not isinstance(state["lane_cursor"], int) or state["lane_cursor"] < 0:
        raise ValueError("lane cursor must be a non-negative integer")
    for field in ("task_ledger", "worker_leases", "evidence_claims", "blockers"):
        if not isinstance(state[field], dict):
            raise ValueError(f"{field} must be a mapping")


__all__ = [
    "Blocker",
    "EvidenceClaim",
    "NextAction",
    "OrchestratorState",
    "ResumeDelta",
    "TaskLedgerEntry",
    "TaskStatus",
    "WorkerLease",
    "deserialize_state",
    "new_orchestrator_state",
    "resume_delta",
    "serialize_state",
]
