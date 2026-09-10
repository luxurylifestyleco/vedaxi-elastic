"""Progressive Capability Disclosure for Elastic Web (Phase 6).

The core idea: never hand a model every full capability schema up front.
Instead, disclose capabilities in increasing levels of detail, so the model
only pays for the detail it actually needs at each stage of a task:

    Level 0  discover(intent)      -> capability IDs + categories only
    Level 1  inspect(capability_id)-> short summary (id + name + one-line desc)
    Level 2  execute(capability_id)-> full capability schema + invocation stub

This module exposes a :class:`DisclosureEngine` plus module-level convenience
functions. It also provides :func:`measure` to quantify the serialized size
(characters and an estimated token count of ``chars / 4``) at each level, so
the token savings of progressive disclosure are directly measurable.

The engine is backed by a :class:`~registry.CapabilityRegistry` populated from
the 63 seeded demo-bank capabilities in :mod:`seed`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the sibling capability-registry package importable regardless of the
# current working directory (the repo has no installed package layout).
_CAPREG_DIR = Path(__file__).resolve().parent.parent / "capability-registry"
if str(_CAPREG_DIR) not in sys.path:
    sys.path.insert(0, str(_CAPREG_DIR))

from capability import Capability  # noqa: E402
from registry import CapabilityRegistry  # noqa: E402
from seed import build_seed_capabilities, seed_registry  # noqa: E402

# Estimated tokens per character. A common rule of thumb is ~4 chars/token.
CHARS_PER_TOKEN = 4


# ----------------------------------------------------------------------
# Level 0 / Level 1 / Level 2 payload builders
# ----------------------------------------------------------------------
def _level0_entry(cap: Capability) -> Dict[str, str]:
    """Level 0: capability id and category (domain) only."""
    return {"id": cap.id, "category": cap.domain}


def _level1_entry(cap: Capability) -> Dict[str, str]:
    """Level 1: id + name + one-line description."""
    return {
        "id": cap.id,
        "name": cap.name,
        "description": cap.description,
    }


def _level2_entry(cap: Capability) -> Dict[str, Any]:
    """Level 2: the full capability schema."""
    return cap.model_dump()


# ----------------------------------------------------------------------
# Serialized-size measurement
# ----------------------------------------------------------------------
def measure(payload: Any) -> Dict[str, int]:
    """Measure the serialized size of a payload.

    Serializes ``payload`` to compact JSON and reports both the character
    count and an estimated token count (``chars / 4``).

    Args:
        payload: Any JSON-serializable object.

    Returns:
        A dict with ``chars`` and ``tokens`` keys.
    """
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    chars = len(text)
    return {"chars": chars, "tokens": chars // CHARS_PER_TOKEN}


# ----------------------------------------------------------------------
# Disclosure engine
# ----------------------------------------------------------------------
class DisclosureEngine:
    """Progressive disclosure over a capability registry.

    Args:
        registry: A :class:`~registry.CapabilityRegistry`. If ``None``, a
            fresh registry seeded with the 63 demo-bank capabilities is used.
    """

    def __init__(self, registry: Optional[CapabilityRegistry] = None) -> None:
        self.registry = registry if registry is not None else self._seeded_registry()

    @staticmethod
    def _seeded_registry() -> CapabilityRegistry:
        reg = CapabilityRegistry()
        seed_registry(reg)
        return reg

    # -- Level 0 ------------------------------------------------------
    def discover(self, intent: str) -> List[Dict[str, str]]:
        """Return Level 0 capability IDs and categories for an intent.

        Args:
            intent: A natural-language intent or search query.

        Returns:
            A list of ``{"id": ..., "category": ...}`` dicts. When ``intent``
            is empty, all capabilities are returned.
        """
        query = (intent or "").strip()
        if not query:
            caps = self.registry.list()
        else:
            caps = self.registry.search(query)
        return [_level0_entry(cap) for cap in caps]

    # -- Level 1 ------------------------------------------------------
    def inspect(self, capability_id: str) -> Dict[str, str]:
        """Return a Level 1 summary for a single capability.

        Args:
            capability_id: The id of the capability to summarize.

        Returns:
            A ``{"id", "name", "description"}`` dict.

        Raises:
            KeyError: If no capability with ``capability_id`` is registered.
        """
        cap = self._require(capability_id)
        return _level1_entry(cap)

    # -- Level 2 ------------------------------------------------------
    def execute(
        self, capability_id: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Return the Level 2 full schema plus an invocation stub.

        Args:
            capability_id: The id of the capability to execute.
            arguments: Optional arguments to bind into the invocation stub.

        Returns:
            A dict with ``capability`` (the full schema) and ``invocation``
            (a stub describing how to call it).

        Raises:
            KeyError: If no capability with ``capability_id`` is registered.
        """
        cap = self._require(capability_id)
        args = arguments or {}
        invocation = {
            "provider": cap.provider,
            "protocol": cap.protocol,
            "endpoint": cap.endpoint,
            "arguments": args,
        }
        return {
            "capability": _level2_entry(cap),
            "invocation": invocation,
        }

    # -- measurement helpers -----------------------------------------
    def measure_level0(self, intent: str = "") -> Dict[str, int]:
        """Serialized size of the Level 0 result for an intent."""
        return measure(self.discover(intent))

    def measure_level0_entry(self, capability_id: str) -> Dict[str, int]:
        """Serialized size of a single capability's Level 0 entry.

        This is the apples-to-apples comparison against a single Level 1
        summary or Level 2 schema for the same capability.
        """
        return measure(_level0_entry(self._require(capability_id)))

    def measure_level1(self, capability_id: str) -> Dict[str, int]:
        """Serialized size of the Level 1 summary for a capability."""
        return measure(self.inspect(capability_id))

    def measure_level2(
        self, capability_id: str, arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, int]:
        """Serialized size of the Level 2 schema + stub for a capability."""
        return measure(self.execute(capability_id, arguments))

    def _require(self, capability_id: str) -> Capability:
        cap = self.registry.get_by_id(capability_id)
        if cap is None:
            raise KeyError(f"capability not found: {capability_id}")
        return cap


# ----------------------------------------------------------------------
# Module-level convenience API
# ----------------------------------------------------------------------
_default_engine: Optional[DisclosureEngine] = None


def _engine() -> DisclosureEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = DisclosureEngine()
    return _default_engine


def discover(intent: str) -> List[Dict[str, str]]:
    """Level 0: capability IDs and categories for an intent."""
    return _engine().discover(intent)


def inspect(capability_id: str) -> Dict[str, str]:
    """Level 1: short summary (id + name + one-line description)."""
    return _engine().inspect(capability_id)


def execute(
    capability_id: str, arguments: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Level 2: full capability schema + invocation stub."""
    return _engine().execute(capability_id, arguments)


def measure_level0(intent: str = "") -> Dict[str, int]:
    """Serialized size of the Level 0 result for an intent."""
    return _engine().measure_level0(intent)


def measure_level0_entry(capability_id: str) -> Dict[str, int]:
    """Serialized size of a single capability's Level 0 entry."""
    return _engine().measure_level0_entry(capability_id)


def measure_level1(capability_id: str) -> Dict[str, int]:
    """Serialized size of the Level 1 summary for a capability."""
    return _engine().measure_level1(capability_id)


def measure_level2(
    capability_id: str, arguments: Optional[Dict[str, Any]] = None
) -> Dict[str, int]:
    """Serialized size of the Level 2 schema + stub for a capability."""
    return _engine().measure_level2(capability_id, arguments)


def main() -> None:
    """Demonstrate progressive disclosure and its token savings."""
    engine = DisclosureEngine()
    sample = "get_balance"
    l0 = engine.measure_level0("balance")
    l1 = engine.measure_level1(sample)
    l2 = engine.measure_level2(sample, {"account_id": "acc_123"})
    print(f"Seeded {len(engine.registry)} capabilities")
    print(f"Level 0 (discover 'balance'): {l0}")
    print(f"Level 1 (inspect {sample}):    {l1}")
    print(f"Level 2 (execute {sample}):    {l2}")


if __name__ == "__main__":
    main()
