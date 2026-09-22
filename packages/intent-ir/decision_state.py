"""Provider-neutral, revision-bound input for a bounded semantic decision.

This is data, never an execution grant. Callers supply only the inputs and
candidates appropriate for the decision. It performs no network requests.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
Description = Annotated[str, StringConstraints(min_length=1, max_length=4000, pattern=r"\S")]


class DecisionCandidate(BaseModel):
    """A host-supplied alternative, not proof that the alternative is authorized."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    id: Identifier
    description: Description
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: list[Description] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def bounded_json(self):
        if self.id == "__none__":
            raise ValueError("__none__ is reserved for abstention")
        json.dumps(self.model_dump(mode="json"), allow_nan=False)
        return self


class DecisionState(BaseModel):
    """Minimal decision input. Identity, credentials and grants stay with the host."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    case_id: Identifier
    intent_revision: int = Field(default=1, strict=True, ge=1)
    inputs: dict[str, JsonValue]
    candidates: list[DecisionCandidate] = Field(default_factory=list, max_length=254)

    @model_validator(mode="after")
    def unique_finite_candidates(self):
        identifiers = [candidate.id for candidate in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Candidate IDs must be unique")
        json.dumps(self.model_dump(mode="json"), allow_nan=False)
        return self

    def content_sha256(self) -> str:
        """Content fingerprint for invalidation/replay; not a signature or permission."""
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
