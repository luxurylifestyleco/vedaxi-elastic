"""Intent IR V1 — conversational document validation.

Validates a JSON object against ``intent_ir.schema.json``. This is not a
compiler and not the compiled ``IntentIR`` Pydantic model in ``intent_ir.py``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Tuple

from jsonschema import Draft202012Validator, ValidationError

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(_HERE, "intent_ir.schema.json")

_SCHEMA: Dict[str, Any] | None = None
_VALIDATOR: Draft202012Validator | None = None


def load_schema() -> Dict[str, Any]:
    global _SCHEMA
    if _SCHEMA is None:
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            _SCHEMA = json.load(fh)
        Draft202012Validator.check_schema(_SCHEMA)
    return _SCHEMA


def validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        _VALIDATOR = Draft202012Validator(load_schema())
    return _VALIDATOR


def validate_v1(document: Any) -> Dict[str, Any]:
    """Return the document if it is a valid V1 intent.

    Raises:
        ValueError: if the document is not a valid V1 intent.
    """
    if not isinstance(document, dict):
        raise ValueError("Intent IR V1 document must be a JSON object")
    try:
        validator().validate(document)
    except ValidationError as exc:
        raise ValueError(exc.message) from exc
    return document


def try_validate_v1(document: Any) -> Tuple[bool, Dict[str, Any] | None, str | None]:
    """Validate without raising. Returns (ok, document_or_none, error_or_none)."""
    try:
        return True, validate_v1(document), None
    except ValueError as exc:
        return False, None, str(exc)
