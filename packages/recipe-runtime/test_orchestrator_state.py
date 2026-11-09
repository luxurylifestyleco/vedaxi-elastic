import json

import pytest

from recipe_runtime.orchestrator_state import (
    deserialize_state,
    new_orchestrator_state,
    resume_delta,
    serialize_state,
)


def task(*, fingerprint="fp-1", source_revision="git:1", status="VERIFIED"):
    return {
        "task_id": "task-1",
        "scope": "state model",
        "status": status,
        "fingerprint": fingerprint,
        "source_revision": source_revision,
        "owner": "worker-1",
        "evidence_ids": ["evidence-1"],
        "changed_paths": ["packages/recipe-runtime/orchestrator_state.py"],
        "next_action": "close",
    }


def test_state_round_trips_as_deterministic_json():
    state = new_orchestrator_state("orchestrate Elastic work", "git:1")
    state["task_ledger"]["task-1"] = task()
    state["worker_leases"]["lease-1"] = {
        "worker_id": "worker-1",
        "task_id": "task-1",
        "lease_id": "lease-1",
        "status": "RELEASED",
        "acquired_at": "2026-11-09T00:00:00Z",
        "expires_at": "2026-11-09T01:00:00Z",
    }
    encoded = serialize_state(state)

    assert encoded == serialize_state(deserialize_state(encoded))
    assert json.loads(encoded)["schema_version"] == "elastic-orchestrator-state.v1"


def test_resume_delta_skips_unchanged_verified_tasks():
    checkpoint = new_orchestrator_state("objective", "git:1")
    checkpoint["task_ledger"]["task-1"] = task()
    current = deserialize_state(serialize_state(checkpoint))
    current["task_ledger"]["task-2"] = task(fingerprint="fp-2") | {"task_id": "task-2"}

    assert resume_delta(checkpoint, current) == {
        "source_revision_changed": False,
        "changed_task_ids": ["task-2"],
        "unchanged_task_ids": ["task-1"],
        "resume_task_ids": ["task-2"],
        "removed_task_ids": [],
    }


def test_resume_delta_reopens_changed_or_nonterminal_work():
    checkpoint = new_orchestrator_state("objective", "git:1")
    checkpoint["task_ledger"]["task-1"] = task()
    current = new_orchestrator_state("objective", "git:2")
    current["task_ledger"]["task-1"] = task(
        fingerprint="fp-2", source_revision="git:2", status="RUNNING"
    )

    delta = resume_delta(checkpoint, current)

    assert delta["source_revision_changed"] is True
    assert delta["changed_task_ids"] == ["task-1"]
    assert delta["unchanged_task_ids"] == []


def test_checkpoint_rejects_missing_fields_and_non_json_values():
    with pytest.raises(ValueError, match="missing fields"):
        deserialize_state("{}")

    state = new_orchestrator_state("objective", "git:1")
    state["task_ledger"]["bad"] = task()
    state["task_ledger"]["bad"]["evidence_ids"] = [object()]
    with pytest.raises(ValueError, match="JSON values"):
        serialize_state(state)
