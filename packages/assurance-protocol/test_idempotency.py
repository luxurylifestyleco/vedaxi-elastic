import pytest

from idempotency import (
    CheckpointState,
    IdempotencyConflict,
    IdempotencyDecision,
    IdempotencyStore,
    UncertainOperation,
)


INPUT = "a" * 64
OTHER_INPUT = "b" * 64
OUTPUT = "c" * 64


def test_same_key_same_input_replays_completed_result():
    store = IdempotencyStore()
    first = store.begin("op-1", INPUT)
    assert first.decision is IdempotencyDecision.START
    store.complete("op-1", OUTPUT)

    replay = store.begin("op-1", INPUT)
    assert replay.decision is IdempotencyDecision.REPLAY
    assert replay.checkpoint.output_sha256 == OUTPUT
    assert replay.checkpoint.attempt == 1


def test_same_key_changed_input_is_rejected():
    store = IdempotencyStore()
    store.begin("op-1", INPUT)
    with pytest.raises(IdempotencyConflict):
        store.begin("op-1", OTHER_INPUT)


def test_uncertain_operation_cannot_be_retried_blindly():
    store = IdempotencyStore(max_attempts=3)
    store.begin("op-1", INPUT)
    store.mark_uncertain("op-1", "timeout after dispatch")

    with pytest.raises(UncertainOperation):
        store.begin("op-1", INPUT)

    store.resolve_uncertain("op-1")
    retry = store.begin("op-1", INPUT)
    assert retry.decision is IdempotencyDecision.RETRY
    assert retry.checkpoint.attempt == 2


def test_attempt_tracking_is_bounded():
    store = IdempotencyStore(max_attempts=2)
    store.begin("op-1", INPUT)
    store.fail("op-1", "temporary failure")
    retry = store.begin("op-1", INPUT)
    assert retry.decision is IdempotencyDecision.RETRY
    assert retry.checkpoint.attempt == 2
    store.fail("op-1", "second failure")

    blocked = store.begin("op-1", INPUT)
    assert blocked.decision is IdempotencyDecision.ATTEMPT_LIMIT
    assert blocked.checkpoint.state is CheckpointState.FAILED


def test_active_operation_is_not_started_twice():
    store = IdempotencyStore()
    store.begin("op-1", INPUT)
    claim = store.begin("op-1", INPUT)
    assert claim.decision is IdempotencyDecision.IN_PROGRESS
    assert claim.checkpoint.attempt == 1
