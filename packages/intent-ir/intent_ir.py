"""Intent IR (Intent Intermediate Representation) Pydantic model.

A structured, validated description of a user's intent. This is the
schema-validated data contract produced by a compiler (rule-based or LLM)
and consumed by downstream capability routing.

Uses Pydantic v2.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntentState(str, Enum):
    """Small lifecycle vocabulary for intent formation and execution."""

    UNCLEAR = "UNCLEAR"
    DISCOVERY = "DISCOVERY"
    FORMED = "FORMED"
    EXECUTING = "EXECUTING"
    FULFILLED = "FULFILLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IntentIR(BaseModel):
    """Structured representation of a user intent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = Field(
        default="1.1",
        description="Version of the IntentIR contract.",
    )

    intent_id: str = Field(
        description="Stable unique identifier for this intent instance."
    )
    intent_revision: int = Field(
        default=1, strict=True, ge=1,
        description="Monotonic revision of this intent, not an authorization grant.",
    )
    original_expression: Optional[str] = Field(
        default=None,
        description="The original human or machine expression, preserved without interpretation.",
    )
    state: IntentState = Field(
        default=IntentState.FORMED,
        description="Lifecycle state of the intent representation.",
    )
    goal: str = Field(description="Canonical goal the user wants to achieve.")
    domain: str = Field(description="Functional domain the intent belongs to.")
    action: str = Field(description="Verb describing the operation.")
    object: str = Field(description="The entity the action applies to.")
    constraints: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured constraints narrowing the intent.",
    )
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-mandatory preferences used to rank otherwise suitable fulfilment paths.",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Ambient context informing execution.",
    )
    desired_output: str = Field(
        description="Requested output format or artifact (e.g. pdf, json)."
    )
    authority: Dict[str, Any] = Field(
        default_factory=dict,
        description="Authorization/entitlement requirements.",
    )
    disclosure: Dict[str, Any] = Field(
        default_factory=dict,
        description="Data-disclosure and privacy requirements.",
    )
    success_conditions: List[str] = Field(
        default_factory=list,
        description="Explicit conditions for the intent to be considered fulfilled.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Compiler confidence in the parsed intent, 0.0 to 1.0.",
    )
    uncertainty: Dict[str, Any] = Field(
        default_factory=dict,
        description="Explicit unresolved fields, ambiguity, or clarification requirements.",
    )
    fulfillment: Dict[str, Any] = Field(
        default_factory=dict,
        description="Fulfillment and assurance state; execution success alone is not fulfillment proof.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form metadata (compiler version, timestamps, provenance).",
    )

    @field_validator("intent_id")
    @classmethod
    def _intent_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("intent_id must not be blank")
        return v.strip()

    @field_validator("goal", "domain", "action", "object", "desired_output")
    @classmethod
    def _required_strings_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v.strip()

    @classmethod
    def new_id(cls) -> str:
        """Generate a fresh intent_id (UUID4 hex)."""
        return uuid.uuid4().hex
