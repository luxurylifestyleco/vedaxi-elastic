"""Acceptance tests for the Elastic Web side of the three-plane split."""

from __future__ import annotations

import urllib.request

import pytest

from adapters import standard_adapters
from failure_codes import FailureCode, recovery_for
from hot_path import HotPathViolation, execute_locally
from elastic_platform import PLATFORM_VERSION, in_range, platform_accepts


def _entry(capability_id: str, **states):
    base = {
        "EXISTS": True,
        "DISCOVERABLE": True,
        "INSTALLABLE": True,
        "INSTALLED": True,
        "ENABLED": True,
        "AUTHORIZED": True,
        "SUPPORTED": True,
        "EXECUTABLE": True,
        "AVAILABLE": True,
    }
    base.update(states)
    return {
        "capability_id": capability_id,
        "ecosystem_attested": True,
        "states": base,
        "requires_network": False,
    }


def _projection(*entries, runtime=None, **extra):
    body = {
        "meta_schema_version": "1.0",
        "execution_contract_version": "1.0",
        "entries": list(entries),
        "runtime": runtime or {"network": True, "execution_state": "foreground"},
    }
    body.update(extra)
    return body


def test_platform_version_is_independent_of_capability_version():
    assert PLATFORM_VERSION == "1.0.0"
    assert platform_accepts("1.4", "1.2")
    assert not platform_accepts("2.0", "1.0")
    assert in_range("1.9", ">=1.0,<2.0")
    assert not in_range("2.0", ">=1.0,<2.0")


def test_unsupported_device_is_identified_before_execution():
    called = {"n": 0}

    def executor(capability_id, args):
        called["n"] += 1
        return {"ok": True}

    entry = _entry("mail.send", SUPPORTED=False)
    entry["unsupported_reason"] = "OS capability unavailable"
    outcome = execute_locally("mail.send", _projection(entry), executor, {})
    assert called["n"] == 0
    assert outcome.executed is False
    assert outcome.decision.code is FailureCode.DEVICE_UNSUPPORTED
    assert "OS capability unavailable" in outcome.decision.reason


def test_hot_path_does_not_contact_a_store(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("store contacted")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    projection = _projection(_entry("mail.send"))
    outcome = execute_locally("mail.send", projection, lambda cid, args: {"sent": True}, {})
    assert outcome.executed is True
    assert outcome.result == {"sent": True}
    with pytest.raises(HotPathViolation):
        execute_locally("mail.send", projection, lambda cid, args: None, store_client=object())


def test_projection_rejects_full_user_memory_and_crm():
    projection = _projection(_entry("mail.send"), user_memories=[{"k": "v"}])
    with pytest.raises(HotPathViolation):
        execute_locally("mail.send", projection, lambda cid, args: None)


def test_revocation_prevents_execution():
    entry = _entry("mail.send")
    entry["revoked"] = True
    outcome = execute_locally("mail.send", _projection(entry), lambda cid, args: {"no": True})
    assert outcome.executed is False
    assert outcome.decision.code is FailureCode.CAPABILITY_REVOKED


def test_new_capability_negotiates_without_a_core_catalog_edit():
    outcome = execute_locally(
        "calendar.create_event",
        _projection(_entry("calendar.create_event")),
        executor=None,
    )
    assert outcome.executed is False
    assert outcome.decision.code is FailureCode.TOOL_UNAVAILABLE
    assert outcome.decision.recovery is not None


def test_alternative_offered_when_device_rejects_primary():
    primary = _entry("transport.request_ride", SUPPORTED=False)
    primary["unsupported_reason"] = "background execution unavailable"
    backup = _entry("transport.request_other")
    outcome = execute_locally(
        "transport.request_ride",
        _projection(primary, backup),
        lambda cid, args: {"should_not": True},
    )
    assert outcome.decision.alternative == "transport.request_other"
    assert outcome.decision.recovery.value == "select_alternative"


def test_os_versions_are_not_collapsed():
    old = _entry("voice.background", SUPPORTED=False)
    old["os_unsupported"] = True
    old["unsupported_reason"] = "OS capability unavailable"
    new = _entry("voice.background", SUPPORTED=True)
    old_decision = execute_locally("voice.background", _projection(old), lambda c, a: None)
    new_decision = execute_locally("voice.background", _projection(new), lambda c, a: {"ok": 1})
    assert old_decision.decision.code is FailureCode.OS_UNSUPPORTED
    assert new_decision.executed is True


def test_failure_codes_are_not_generic():
    for code in FailureCode:
        assert recovery_for(code).value != "generic_error"


def test_adapters_declare_required_fields():
    adapters = standard_adapters("corr-1")
    assert set(adapters) == {
        "CapabilityAdapter",
        "AuthorizationAdapter",
        "InstallationAdapter",
        "DeviceExecutionAdapter",
        "ToolExecutionAdapter",
        "SchemaAdapter",
        "PlatformCompatibilityAdapter",
    }
    for contract in adapters.values():
        contract.validate()
        assert contract.timeout_ms == 5000
        assert contract.correlation_id == "corr-1"
