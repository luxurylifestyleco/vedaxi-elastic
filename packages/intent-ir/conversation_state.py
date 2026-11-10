"""Compact task state: explicit patches, no transcript, inference or persistence.

Missing fields are unknown; names in ``cleared`` were explicitly removed or
invalidated by a subject change. ``remember`` is an effect for the host to store
only after authorization, never an implicit write or execution grant.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StateConflict(ValueError):
    """The host must reject a stale patch rather than overwrite current state."""


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FieldSpec(Contract):
    kind: Literal["text", "integer", "number", "boolean"] = "text"
    required: bool = False
    choices: list[str | int | float | bool] = Field(default_factory=list, max_length=128)
    min_length: int = Field(default=0, ge=0)
    max_length: int = Field(default=280, ge=1, le=12000)
    minimum: float | int | None = None
    maximum: float | int | None = None
    subject_scoped: bool = False

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.min_length > self.max_length:
            raise ValueError("Invalid length bounds")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Invalid numeric bounds")
        for value in self.choices:
            self.validate_value(value, check_choices=False)
        return self

    def validate_value(self, value, *, check_choices=True):
        types = {"text": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,)}
        if type(value) not in types[self.kind]:
            raise ValueError(f"Expected {self.kind}")
        if self.kind == "text":
            if not value.strip() or not self.min_length <= len(value) <= self.max_length:
                raise ValueError("Text outside permitted length or blank")
        elif self.kind in ("integer", "number"):
            if type(value) is float and not math.isfinite(value):
                raise ValueError("Number must be finite")
            if self.minimum is not None and value < self.minimum:
                raise ValueError("Number below minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("Number above maximum")
        if check_choices and self.choices and not any(type(value) is type(v) and value == v for v in self.choices):
            raise ValueError("Value is not an allowed choice")
        return value


class TaskSchema(Contract):
    schema_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    version: str = Field(default="1.0", min_length=1, max_length=32)
    fields: dict[str, FieldSpec]
    derived_dependencies: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_graph(self):
        if not 1 <= len(self.fields) <= 64 or len(self.derived_dependencies) > 64:
            raise ValueError("Schema allows 1ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œ64 fields and at most 64 derived outputs")
        names = set(self.fields) | set(self.derived_dependencies)
        if set(self.fields) & set(self.derived_dependencies):
            raise ValueError("Derived outputs and input fields must have different names")
        import re
        if any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", name) for name in names):
            raise ValueError("Invalid schema field/output name")
        for dependencies in self.derived_dependencies.values():
            if len(dependencies) > 64 or len(dependencies) != len(set(dependencies)) or not set(dependencies) <= names:
                raise ValueError("Invalid derived dependencies")
        visited, visiting = set(), set()

        def visit(name):
            if name in visiting:
                raise ValueError("Cyclic derived dependencies")
            if name in visited:
                return
            visiting.add(name)
            for parent in self.derived_dependencies.get(name, []):
                visit(parent)
            visiting.remove(name)
            visited.add(name)

        for name in self.derived_dependencies:
            visit(name)
        return self


class StateField(Contract):
    """A source label is provenance metadata, not authenticated proof of origin."""
    value: str | int | float | bool
    source: str = Field(default="explicit_patch", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    scope: Literal["session"] = "session"


class CompactState(Contract):
    schema_id: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    revision: int = Field(default=1, ge=1)
    subject: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"\S")
    fields: dict[str, StateField] = Field(default_factory=dict)
    cleared: list[str] = Field(default_factory=list, max_length=64)
    invalidated: dict[str, int] = Field(default_factory=dict)


class PatchResult(Contract):
    state: CompactState
    changed: list[str]
    preserved: list[str]
    invalidated: list[str]
    needs_clarification: list[str]
    remember: dict[str, StateField]


def new_state(schema: TaskSchema, subject: str | None = None) -> CompactState:
    schema = TaskSchema.model_validate(schema.model_dump())
    if subject is not None and not subject.strip():
        raise ValueError("Subject cannot be blank")
    return CompactState(schema_id=schema.schema_id, schema_version=schema.version, subject=subject)


def apply_patch(state: CompactState, schema: TaskSchema, changes: dict,
                clears: list[str], expected_revision: int, subject: str | None = None,
                remember: list[str] | None = None) -> PatchResult:
    """Atomically validate a patch and return an independent state plus effects.

    Omitted/None subject preserves the subject. A changed subject clears bound
    fields unless explicitly replaced. Unknown names and overlapping set/clear
    operations fail. True no-ops retain revision; remember-only effects do too.
    Host persistence must compare-and-swap the same revision to prevent races.
    """
    schema = TaskSchema.model_validate(schema.model_dump())
    state = CompactState.model_validate(state.model_dump())
    if state.schema_id != schema.schema_id or state.schema_version != schema.version:
        raise ValueError("State/schema mismatch")
    if type(expected_revision) is not int or expected_revision != state.revision:
        raise StateConflict("Stale or invalid expected revision")
    if type(changes) is not dict or type(clears) is not list or (remember is not None and type(remember) is not list):
        raise ValueError("Changes must be a mapping; clears and remember must be lists")
    remember = [] if remember is None else remember
    for names in (list(changes), clears, remember, state.cleared):
        if any(type(name) is not str for name in names) or len(names) != len(set(names)):
            raise ValueError("Field names must be unique strings")
        if not set(names) <= set(schema.fields):
            raise ValueError("Unknown input field")
    if set(changes) & set(clears):
        raise ValueError("Cannot both set and clear a field")
    if not set(state.fields) <= set(schema.fields) or set(state.fields) & set(state.cleared):
        raise ValueError("Invalid stored field state")
    if not set(state.invalidated) <= set(schema.derived_dependencies):
        raise ValueError("Unknown stored derived output")
    if any(type(v) is not int or not 1 <= v <= state.revision for v in state.invalidated.values()):
        raise ValueError("Invalid stored invalidation revision")
    for name, field in state.fields.items():
        schema.fields[name].validate_value(field.value)
    for name, value in changes.items():
        schema.fields[name].validate_value(value)
    if subject is not None and (type(subject) is not str or not subject.strip() or len(subject) > 128):
        raise ValueError("Subject must be a nonblank bounded string")
    result = deepcopy(state)
    changed = set()
    subject_changed = subject is not None and subject != state.subject
    removed = set(clears)
    if subject_changed:
        result.subject = subject
        # Bound slots are invalidated even if currently unknown: dependent outputs
        # may incorporate the old subject, and must not survive its replacement.
        removed.update(name for name, spec in schema.fields.items() if spec.subject_scoped and name not in changes)
        changed.update(name for name, spec in schema.fields.items() if spec.subject_scoped)
    cleared = set(result.cleared)
    for name in removed:
        if name in result.fields or name not in cleared:
            changed.add(name)
        result.fields.pop(name, None)
        cleared.add(name)
    for name, value in changes.items():
        old = result.fields.get(name)
        if old is None or type(old.value) is not type(value) or old.value != value:
            changed.add(name)
        if name in changed:
            result.fields[name] = StateField(value=deepcopy(value))
        cleared.discard(name)
    result.cleared = sorted(cleared)
    invalidated = set()
    while True:
        found = {name for name, dependencies in schema.derived_dependencies.items()
                 if set(dependencies) & (changed | invalidated)} - invalidated
        if not found:
            break
        invalidated.update(found)
    if changed or subject_changed:
        result.revision += 1
        result.invalidated.update({name: result.revision for name in invalidated})
    if any(name not in result.fields for name in remember):
        raise ValueError("Cannot remember an unknown or cleared field")
    return PatchResult(
        state=result, changed=sorted(changed),
        preserved=sorted(set(state.fields) & set(result.fields) - changed),
        invalidated=sorted(invalidated),
        needs_clarification=sorted(name for name, spec in schema.fields.items() if spec.required and name not in result.fields),
        remember={name: deepcopy(result.fields[name]) for name in remember},
    )


def validate_state(state: CompactState | dict, schema: TaskSchema) -> CompactState:
    """Validate persisted/client state against the host schema; return a copy."""
    parsed = CompactState.model_validate(state)
    return apply_patch(parsed, schema, {}, [], parsed.revision).state


RESEARCH_SCHEMA = TaskSchema(
    schema_id="research", fields={"query": FieldSpec(min_length=3, max_length=280, required=True)},
    derived_dependencies={"results": ["query"], "summary": ["results"]},
)
