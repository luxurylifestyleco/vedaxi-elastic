"""Typed contracts and LangChain-core prompts for master orchestration.

These models describe worker work and its evidence. They do not execute work,
change queue state, or grant runtime authority.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: str = Field(default="1.0", min_length=1)


class WorkerTaskSpec(Contract):
    """The bounded work order a master may give to one worker."""

    task_id: str = Field(min_length=1)
    worker_name: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    write_boundaries: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)


class EvidenceReport(Contract):
    """The worker's observable report; self-reported claims remain unverified."""

    task_id: str = Field(min_length=1)
    changed_files: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    exact_evidence: list[str] = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)
    next_action: str = Field(min_length=1)


class VerificationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class VerificationVerdict(Contract):
    """An independent verdict over a worker report."""

    task_id: str = Field(min_length=1)
    status: VerificationStatus
    checked: list[str] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    failures: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)


class NextActionDecision(Contract):
    """The master's explicit decision after verification."""

    task_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    authorization_required: bool = False
    depends_on: list[str] = Field(default_factory=list)


def build_worker_task_prompt(spec: WorkerTaskSpec) -> Any:
    """Build a structured prompt; this does not invoke a model or worker."""

    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are {worker_name}. Work only within the supplied scope and "
                "write boundaries. Do not execute orchestration authority.",
            ),
            (
                "human",
                "Task: {task_id}\nScope: {scope}\nWrite boundaries: {write_boundaries}\n"
                "Acceptance criteria: {acceptance_criteria}\nConstraints: {constraints}\n"
                "Return exact commands, outputs, changed files, blockers, and one next action.",
            ),
        ]
    ).partial(**spec.model_dump(mode="json"))


def build_verification_prompt(
    report: EvidenceReport, verdict: VerificationVerdict | None = None
) -> Any:
    """Build a review prompt from report evidence; this does not verify it."""

    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Independently check the worker report against its observable evidence. "
                "Return PASS, FAIL, or BLOCKED; never infer missing evidence.",
            ),
            (
                "human",
                "Task: {task_id}\nChanged files: {changed_files}\nCommands: {commands}\n"
                "Exact evidence: {exact_evidence}\nBlockers: {blockers}\n"
                "Worker next action: {next_action}\nPrior verdict: {prior_verdict}",
            ),
        ]
    ).partial(
        **report.model_dump(mode="json"),
        prior_verdict=verdict.model_dump(mode="json") if verdict else None,
    )


__all__ = [
    "EvidenceReport",
    "NextActionDecision",
    "VerificationStatus",
    "VerificationVerdict",
    "WorkerTaskSpec",
    "build_verification_prompt",
    "build_worker_task_prompt",
]
