"""Tests for Progressive Capability Disclosure (Phase 6).

Verifies the three disclosure levels and that serialized size strictly
increases from Level 0 -> Level 1 -> Level 2, making the token savings of
progressive disclosure measurable.
"""

from __future__ import annotations

import pytest

from disclosure import (
    DisclosureEngine,
    discover,
    execute,
    inspect,
    measure,
    measure_level0_entry,
    measure_level1,
    measure_level2,
)
from seed import build_seed_capabilities


@pytest.fixture(scope="module")
def engine() -> DisclosureEngine:
    return DisclosureEngine()


@pytest.fixture(scope="module")
def sample_id() -> str:
    return "get_balance"


# ----------------------------------------------------------------------
# Level 0: discover
# ----------------------------------------------------------------------
def test_discover_returns_level0_ids_and_categories(engine):
    result = engine.discover("balance")
    assert result, "expected at least one match for 'balance'"
    for entry in result:
        assert set(entry.keys()) == {"id", "category"}
        assert entry["id"]
        assert entry["category"]


def test_discover_empty_intent_returns_all(engine):
    result = engine.discover("")
    assert len(result) == len(build_seed_capabilities())


def test_discover_no_match_returns_empty(engine):
    assert engine.discover("zzzz_nonexistent") == []


# ----------------------------------------------------------------------
# Level 1: inspect
# ----------------------------------------------------------------------
def test_inspect_returns_summary(engine, sample_id):
    summary = engine.inspect(sample_id)
    assert set(summary.keys()) == {"id", "name", "description"}
    assert summary["id"] == sample_id
    assert summary["name"]
    assert summary["description"]


def test_inspect_missing_raises_keyerror(engine):
    with pytest.raises(KeyError):
        engine.inspect("does_not_exist")


# ----------------------------------------------------------------------
# Level 2: execute
# ----------------------------------------------------------------------
def test_execute_returns_full_schema(engine, sample_id):
    result = engine.execute(sample_id, {"account_id": "acc_123"})
    assert "capability" in result
    assert "invocation" in result
    schema = result["capability"]
    # Full schema carries the fields that Level 0/1 omit.
    for field in (
        "id",
        "name",
        "description",
        "domain",
        "inputs",
        "outputs",
        "permissions",
        "provider",
        "protocol",
        "endpoint",
        "estimated_latency",
        "estimated_cost",
        "historical_success",
        "metadata",
    ):
        assert field in schema, f"full schema missing field: {field}"
    assert schema["id"] == sample_id
    # Invocation stub binds the arguments.
    assert result["invocation"]["arguments"] == {"account_id": "acc_123"}
    assert result["invocation"]["endpoint"] == schema["endpoint"]


def test_execute_missing_raises_keyerror(engine):
    with pytest.raises(KeyError):
        engine.execute("does_not_exist")


# ----------------------------------------------------------------------
# Size measurement
# ----------------------------------------------------------------------
def test_measure_reports_chars_and_tokens():
    m = measure({"a": 1})
    assert set(m.keys()) == {"chars", "tokens"}
    assert m["chars"] > 0
    assert m["tokens"] == m["chars"] // 4


def test_unicode_measurement_does_not_change_with_optional_serializer(monkeypatch):
    import importlib
    import json
    import sys
    from types import SimpleNamespace
    import disclosure

    expected_chars = len(r'{"name":"caf\u00e9"}')
    expected = {"chars": expected_chars, "tokens": expected_chars // 4}
    try:
        with monkeypatch.context() as scoped:
            scoped.setitem(sys.modules, "orjson", SimpleNamespace(
                dumps=lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
            importlib.reload(disclosure)
            assert disclosure.measure({"name": "caf\u00e9"}) == expected
    finally:
        importlib.reload(disclosure)


def test_level0_smaller_than_level1_smaller_than_level2(engine, sample_id):
    l0 = engine.measure_level0_entry(sample_id)
    l1 = engine.measure_level1(sample_id)
    l2 = engine.measure_level2(sample_id, {"account_id": "acc_123"})
    assert l0["chars"] < l1["chars"] < l2["chars"]
    assert l0["tokens"] < l1["tokens"] < l2["tokens"]


def test_level0_smaller_than_level1_smaller_than_level2_module_api():
    l0 = measure_level0_entry("get_balance")
    l1 = measure_level1("get_balance")
    l2 = measure_level2("get_balance", {"account_id": "acc_123"})
    assert l0["chars"] < l1["chars"] < l2["chars"]


# ----------------------------------------------------------------------
# Module-level convenience API
# ----------------------------------------------------------------------
def test_module_level_functions():
    assert discover("balance")
    assert inspect("get_balance")["id"] == "get_balance"
    assert "capability" in execute("get_balance")
