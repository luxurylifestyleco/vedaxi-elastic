"""In-memory capability registry for Elastic Web.

The registry is the source of truth for which capabilities are available
for routing. It stores :class:`~capability.Capability` objects keyed by
their ``id`` and exposes CRUD plus search operations.

This is a plain in-memory implementation backed by a dict. It is
intentionally free of ranking or learning logic — selection and scoring
are the responsibility of downstream retrieval/routing layers.

Thread-safety: the registry is not internally synchronized. Callers that
mutate it from multiple threads should guard with their own lock.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from capability import Capability


class CapabilityRegistry:
    """A registry of capabilities keyed by id.

    Attributes:
        capabilities: Mapping of capability id to :class:`Capability`.
    """

    def __init__(self) -> None:
        self.capabilities: Dict[str, Capability] = {}

    def register(self, capability: Capability) -> Capability:
        """Register a capability, replacing any existing one with the same id.

        Args:
            capability: The capability to register.

        Returns:
            The registered capability.
        """
        self.capabilities[capability.id] = capability
        return capability

    def update(self, capability: Capability) -> Capability:
        """Update an existing capability.

        Args:
            capability: The capability to update. Its ``id`` must already
                be registered.

        Returns:
            The updated capability.

        Raises:
            KeyError: If no capability with ``capability.id`` is registered.
        """
        if capability.id not in self.capabilities:
            raise KeyError(f"capability not found: {capability.id}")
        self.capabilities[capability.id] = capability
        return capability

    def remove(self, capability_id: str) -> Optional[Capability]:
        """Remove a capability by id.

        Args:
            capability_id: The id of the capability to remove.

        Returns:
            The removed capability, or ``None`` if it was not present.
        """
        return self.capabilities.pop(capability_id, None)

    def list(self) -> List[Capability]:
        """Return all registered capabilities.

        Returns:
            A list of capabilities in insertion order.
        """
        return list(self.capabilities.values())

    def search(self, query: str, domain: Optional[str] = None) -> List[Capability]:
        """Search capabilities by a case-insensitive substring match.

        The query is matched against the capability ``id``, ``name``,
        ``description``, and ``domain``. An optional ``domain`` filter
        narrows results to a single domain.

        Args:
            query: Substring to match (case-insensitive).
            domain: Optional domain to restrict results to.

        Returns:
            A list of matching capabilities.
        """
        q = query.strip().lower()
        results: List[Capability] = []
        for cap in self.capabilities.values():
            if domain is not None and cap.domain != domain:
                continue
            haystack = " ".join(
                [cap.id, cap.name, cap.description, cap.domain]
            ).lower()
            if q in haystack:
                results.append(cap)
        return results

    def get_by_id(self, capability_id: str) -> Optional[Capability]:
        """Fetch a capability by id.

        Args:
            capability_id: The id of the capability to fetch.

        Returns:
            The capability, or ``None`` if not found.
        """
        return self.capabilities.get(capability_id)

    def __len__(self) -> int:
        return len(self.capabilities)

    def __iter__(self) -> Iterable[Capability]:
        return iter(self.capabilities.values())
