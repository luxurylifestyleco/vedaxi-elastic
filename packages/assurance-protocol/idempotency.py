"""Pure in-memory idempotency and checkpoint contract.

This module deliberately has no provider, database, gateway, or retry side
effects.  It records the facts needed to make a safe next-attempt decision.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


Digest = str


class CheckpointState(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class IdempotencyDecision(str, Enum):
    START = "start"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"
    RETRY = "retry"
    INPUT_MISMATCH = "input_mismatch"
    RECONCILE_REQUIRED = "reconcile_required"
    ATTEMPT_LIMIT = "attempt_limit"


class IdempotencyCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt: int = Field(ge=1)
    state: CheckpointState
    output_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: str | None = None


class IdempotencyClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: IdempotencyDecision
    checkpoint: IdempotencyCheckpoint


class IdempotencyConflict(Exception):
    """The same idempotency key was reused for different input."""


class UncertainOperation(Exception):
    """A provider operation may have happened; blind retry is forbidden."""


class IdempotencyStore:
    """Bounded in-memory checkpoint store.

    A failed operation may be started again up to ``max_attempts``.  An
    uncertain operation must first be explicitly resolved as failed or
    completed; ``begin`` never retries it blindly.
    """

    def __init__(self, *, max_attempts: int = 1) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self._checkpoints: dict[str, IdempotencyCheckpoint] = {}

    def begin(self, idempotency_key: str, input_sha256: Digest) -> IdempotencyClaim:
        self._validate_key(idempotency_key)
        self._validate_digest(input_sha256)
        prior = self._checkpoints.get(idempotency_key)
        if prior is None:
            checkpoint = self._save(idempotency_key, input_sha256, 1, CheckpointState.STARTED)
            return IdempotencyClaim(decision=IdempotencyDecision.START, checkpoint=checkpoint)
        if prior.input_sha256 != input_sha256:
            raise IdempotencyConflict("idempotency key reused with different input")
        if prior.state is CheckpointState.COMPLETED:
            return IdempotencyClaim(decision=IdempotencyDecision.REPLAY, checkpoint=prior)
        if prior.state is CheckpointState.UNCERTAIN:
            raise UncertainOperation("operation state is uncertain; reconcile before retry")
        if prior.state is CheckpointState.STARTED:
            return IdempotencyClaim(decision=IdempotencyDecision.IN_PROGRESS, checkpoint=prior)
        if prior.attempt >= self.max_attempts:
            return IdempotencyClaim(decision=IdempotencyDecision.ATTEMPT_LIMIT, checkpoint=prior)
        checkpoint = self._save(
            idempotency_key, input_sha256, prior.attempt + 1, CheckpointState.STARTED
        )
        return IdempotencyClaim(decision=IdempotencyDecision.RETRY, checkpoint=checkpoint)

    def complete(self, idempotency_key: str, output_sha256: Digest) -> IdempotencyCheckpoint:
        prior = self._require(idempotency_key)
        self._validate_digest(output_sha256)
        if prior.state is CheckpointState.COMPLETED and prior.output_sha256 != output_sha256:
            raise IdempotencyConflict("completed key cannot receive a different output")
        return self._save(
            prior.idempotency_key,
            prior.input_sha256,
            prior.attempt,
            CheckpointState.COMPLETED,
            output_sha256=output_sha256,
        )

    def fail(self, idempotency_key: str, error: str) -> IdempotencyCheckpoint:
        prior = self._require(idempotency_key)
        return self._save(
            prior.idempotency_key,
            prior.input_sha256,
            prior.attempt,
            CheckpointState.FAILED,
            error=error,
        )

    def mark_uncertain(self, idempotency_key: str, error: str | None = None) -> IdempotencyCheckpoint:
        prior = self._require(idempotency_key)
        return self._save(
            prior.idempotency_key,
            prior.input_sha256,
            prior.attempt,
            CheckpointState.UNCERTAIN,
            error=error,
        )

    def resolve_uncertain(self, idempotency_key: str, *, completed_output_sha256: Digest | None = None) -> IdempotencyCheckpoint:
        prior = self._require(idempotency_key)
        if prior.state is not CheckpointState.UNCERTAIN:
            raise ValueError("only uncertain checkpoints can be resolved")
        if completed_output_sha256 is not None:
            return self.complete(idempotency_key, completed_output_sha256)
        return self.fail(idempotency_key, "reconciled provider failure")

    def get(self, idempotency_key: str) -> IdempotencyCheckpoint | None:
        return self._checkpoints.get(idempotency_key)

    def _require(self, key: str) -> IdempotencyCheckpoint:
        self._validate_key(key)
        try:
            return self._checkpoints[key]
        except KeyError as exc:
            raise KeyError(f"unknown idempotency key: {key}") from exc

    def _save(self, key: str, digest: str, attempt: int, state: CheckpointState, *, output_sha256: str | None = None, error: str | None = None) -> IdempotencyCheckpoint:
        checkpoint = IdempotencyCheckpoint(
            idempotency_key=key,
            input_sha256=digest,
            attempt=attempt,
            state=state,
            output_sha256=output_sha256,
            error=error,
        )
        self._checkpoints[key] = checkpoint
        return checkpoint

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("idempotency_key must be non-empty")

    @staticmethod
    def _validate_digest(digest: str) -> None:
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("digest must be a lowercase SHA-256 hex value")
