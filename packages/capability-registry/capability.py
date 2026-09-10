"""Capability schema for Elastic Web.

A capability is a declarative description of an operation a system can
perform on behalf of a user. It is the unit of discovery and routing in
the Elastic Web architecture: an intent compiler produces an IntentIR,
and capability routing matches it against registered capabilities.

This module defines the Pydantic v2 model for a single capability. It is
intentionally generic — it carries no ranking or learning logic. Any
performance or preference signals are stored as plain data fields
(``estimated_latency``, ``estimated_cost``, ``historical_success``) and
free-form ``metadata``, leaving interpretation to downstream consumers.

Uses Pydantic v2.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Capability(BaseModel):
    """A declarative description of an operation a system can perform.

    Attributes:
        id: Stable unique identifier for the capability (e.g. ``get_balance``).
        name: Human-readable display name.
        description: What the capability does, in plain language.
        domain: Functional domain the capability belongs to (e.g. ``accounts``).
        inputs: Structured inputs the capability accepts.
        outputs: Structured outputs the capability produces.
        permissions: Authorization/entitlement requirements.
        provider: The system/provider that executes the capability.
        protocol: Transport/interface protocol (e.g. ``rest``, ``grpc``, ``tool``).
        endpoint: The concrete endpoint or tool reference used to invoke it.
        estimated_latency: Expected latency in milliseconds.
        estimated_cost: Expected cost per invocation (arbitrary units).
        historical_success: Historical success rate, 0.0 to 1.0.
        metadata: Free-form metadata (tags, version, provenance, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable unique identifier for the capability.")
    name: str = Field(description="Human-readable display name.")
    description: str = Field(description="What the capability does, in plain language.")
    domain: str = Field(description="Functional domain the capability belongs to.")
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured inputs the capability accepts.",
    )
    outputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured outputs the capability produces.",
    )
    permissions: List[str] = Field(
        default_factory=list,
        description="Authorization/entitlement requirements.",
    )
    provider: str = Field(
        default="demo-bank",
        description="The system/provider that executes the capability.",
    )
    protocol: str = Field(
        default="rest",
        description="Transport/interface protocol (e.g. rest, grpc, tool).",
    )
    endpoint: Optional[str] = Field(
        default=None,
        description="Concrete endpoint or tool reference used to invoke it.",
    )
    estimated_latency: Optional[int] = Field(
        default=None,
        ge=0,
        description="Expected latency in milliseconds.",
    )
    estimated_cost: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Expected cost per invocation (arbitrary units).",
    )
    historical_success: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Historical success rate, 0.0 to 1.0.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form metadata (tags, version, provenance, etc.).",
    )

    @field_validator("id", "name", "description", "domain", "provider", "protocol")
    @classmethod
    def _required_strings_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be blank")
        return v.strip()

    @classmethod
    def new_id(cls) -> str:
        """Generate a fresh capability id (UUID4 hex)."""
        return uuid.uuid4().hex
