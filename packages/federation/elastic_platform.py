"""Elastic Web platform version and capability compatibility ranges.

Capability versions are not pinned to the platform version. A capability
declares the meta-schema and execution-contract ranges it needs.

This file is not named platform.py. That name shadows the stdlib module when
this directory is on sys.path.
"""

from __future__ import annotations

from typing import Tuple

# What this process understands. Not a catalog of ecosystem capabilities.
PLATFORM_VERSION = "1.0.0"
META_SCHEMA_RANGE = ">=1.0,<2.0"
EXECUTION_CONTRACT_RANGE = ">=1.0,<2.0"
RECIPE_MODEL_RANGE = ">=1.0,<2.0"
TOOL_CALL_RANGE = ">=1.0,<2.0"


def _parse(version: str) -> Tuple[int, int]:
    text = version.strip().lstrip("v")
    parts = text.split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"version must be major.minor: {version!r}")
    return int(parts[0]), int(parts[1])


def in_range(version: str, spec: str) -> bool:
    """Evaluate a single range clause: >=1.0,<2.0 or ==1.2."""
    major, minor = _parse(version)
    for clause in spec.split(","):
        clause = clause.strip()
        if not clause:
            continue
        if clause.startswith(">="):
            bound = _parse(clause[2:])
            if (major, minor) < bound:
                return False
        elif clause.startswith(">"):
            bound = _parse(clause[1:])
            if (major, minor) <= bound:
                return False
        elif clause.startswith("<="):
            bound = _parse(clause[2:])
            if (major, minor) > bound:
                return False
        elif clause.startswith("<"):
            bound = _parse(clause[1:])
            if (major, minor) >= bound:
                return False
        elif clause.startswith("=="):
            if (major, minor) != _parse(clause[2:]):
                return False
        else:
            raise ValueError(f"unsupported range clause: {clause!r}")
    return True


def platform_accepts(meta_schema_version: str, execution_contract_version: str) -> bool:
    """True when this platform can orchestrate the given contract versions."""
    return in_range(meta_schema_version, META_SCHEMA_RANGE) and in_range(
        execution_contract_version, EXECUTION_CONTRACT_RANGE
    )
