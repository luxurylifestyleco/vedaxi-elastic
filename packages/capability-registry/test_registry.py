"""Tests for the Elastic Web capability registry.

Covers register, update, remove, list, search, and get_by_id on
:class:`~registry.CapabilityRegistry`, plus the seed module.
"""

from __future__ import annotations

import pytest

from capability import Capability
from registry import CapabilityRegistry
from seed import build_seed_capabilities, seed_registry


def _make_cap(
    id: str = "get_balance",
    name: str = "Get Balance",
    domain: str = "accounts",
    description: str = "Retrieve account balance.",
) -> Capability:
    return Capability(
        id=id,
        name=name,
        description=description,
        domain=domain,
        inputs={"account_id": "string"},
        outputs={"balance": "number"},
        permissions=["accounts:read"],
        provider="demo-bank",
        protocol="rest",
        endpoint=f"/v1/{id}",
        estimated_latency=40,
        estimated_cost=0.001,
        historical_success=0.99,
        metadata={"tags": ["balance"]},
    )


# ----------------------------------------------------------------------
# register
# ----------------------------------------------------------------------
def test_register_adds_capability():
    reg = CapabilityRegistry()
    cap = _make_cap()
    reg.register(cap)
    assert reg.get_by_id("get_balance") is cap
    assert len(reg) == 1


def test_register_replaces_existing_same_id():
    reg = CapabilityRegistry()
    reg.register(_make_cap(id="get_balance", name="Old"))
    new = _make_cap(id="get_balance", name="New")
    reg.register(new)
    assert len(reg) == 1
    assert reg.get_by_id("get_balance").name == "New"


# ----------------------------------------------------------------------
# update
# ----------------------------------------------------------------------
def test_update_modifies_existing():
    reg = CapabilityRegistry()
    reg.register(_make_cap(id="get_balance", name="Old"))
    updated = _make_cap(id="get_balance", name="Updated", domain="payments")
    reg.update(updated)
    cap = reg.get_by_id("get_balance")
    assert cap.name == "Updated"
    assert cap.domain == "payments"
    assert len(reg) == 1


def test_update_missing_raises_keyerror():
    reg = CapabilityRegistry()
    with pytest.raises(KeyError):
        reg.update(_make_cap(id="does_not_exist"))


# ----------------------------------------------------------------------
# remove
# ----------------------------------------------------------------------
def test_remove_deletes_capability():
    reg = CapabilityRegistry()
    cap = _make_cap()
    reg.register(cap)
    removed = reg.remove("get_balance")
    assert removed is cap
    assert reg.get_by_id("get_balance") is None
    assert len(reg) == 0


def test_remove_missing_returns_none():
    reg = CapabilityRegistry()
    assert reg.remove("nope") is None


# ----------------------------------------------------------------------
# list
# ----------------------------------------------------------------------
def test_list_returns_all_in_insertion_order():
    reg = CapabilityRegistry()
    a = _make_cap(id="a", name="A")
    b = _make_cap(id="b", name="B")
    c = _make_cap(id="c", name="C")
    for cap in (a, b, c):
        reg.register(cap)
    assert reg.list() == [a, b, c]


def test_list_empty():
    assert CapabilityRegistry().list() == []


# ----------------------------------------------------------------------
# search
# ----------------------------------------------------------------------
def test_search_matches_substring_case_insensitive():
    reg = CapabilityRegistry()
    reg.register(_make_cap(id="get_balance", name="Get Balance", description="Retrieve account balance."))
    reg.register(_make_cap(id="freeze_card", name="Freeze Card", domain="cards", description="Freeze a card."))
    hits = reg.search("balance")
    assert [c.id for c in hits] == ["get_balance"]


def test_search_matches_name_and_domain():
    reg = CapabilityRegistry()
    reg.register(_make_cap(id="get_balance", name="Get Balance", domain="accounts"))
    reg.register(_make_cap(id="freeze_card", name="Freeze Card", domain="cards"))
    # matches on domain text
    assert {c.id for c in reg.search("card")} == {"freeze_card"}
    # matches on name
    assert {c.id for c in reg.search("freeze")} == {"freeze_card"}


def test_search_with_domain_filter():
    reg = CapabilityRegistry()
    reg.register(_make_cap(id="get_balance", name="Get Balance", domain="accounts"))
    reg.register(_make_cap(id="freeze_card", name="Freeze Card", domain="cards"))
    hits = reg.search("get", domain="accounts")
    assert [c.id for c in hits] == ["get_balance"]
    assert reg.search("get", domain="cards") == []


def test_search_no_match_returns_empty():
    reg = CapabilityRegistry()
    reg.register(_make_cap())
    assert reg.search("zzzz") == []


# ----------------------------------------------------------------------
# get_by_id
# ----------------------------------------------------------------------
def test_get_by_id_returns_capability():
    reg = CapabilityRegistry()
    cap = _make_cap()
    reg.register(cap)
    assert reg.get_by_id("get_balance") is cap


def test_get_by_id_missing_returns_none():
    assert CapabilityRegistry().get_by_id("missing") is None


# ----------------------------------------------------------------------
# seed
# ----------------------------------------------------------------------
def test_seed_has_at_least_50_capabilities():
    caps = build_seed_capabilities()
    assert len(caps) >= 50


def test_seed_covers_all_expected_domains():
    caps = build_seed_capabilities()
    domains = {c.domain for c in caps}
    expected = {
        "accounts",
        "payments",
        "statements/documents",
        "cards",
        "loans",
        "investments",
        "insurance",
        "KYC/profile",
        "support",
        "offers",
    }
    assert expected.issubset(domains)


def test_seed_ids_are_unique():
    caps = build_seed_capabilities()
    ids = [c.id for c in caps]
    assert len(ids) == len(set(ids))


def test_seed_registry_populates():
    reg = CapabilityRegistry()
    count = seed_registry(reg)
    assert count == len(build_seed_capabilities())
    assert len(reg) == count
