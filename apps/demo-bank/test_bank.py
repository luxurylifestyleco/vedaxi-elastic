"""Tests for the Demo Bank application (Phase 8).

Asserts that:
  * the manifest exposes at least 50 capabilities across the 10 domains,
  * every manifest capability maps to a callable bank function,
  * each of the 5 canonical demo intents returns a successful result with
    the expected shape.
"""

from __future__ import annotations

import inspect

import pytest

import bank
from capability import Capability
from manifest import build_manifest

EXPECTED_DOMAINS = {
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

# Defaults used to satisfy required positional parameters when smoke-testing
# every bank function with no explicit arguments.
_DEFAULTS = {
    "amount": 100.0,
    "to_account": "ACC-1002",
    "from_account": "ACC-1001",
    "biller_id": "BILL-1",
    "from_party": "alice@example.com",
    "participants": ["a@example.com", "b@example.com"],
    "product_id": "PROD-1",
    "holding_id": "H-1",
    "units": 10.0,
    "policy_id": "POL-1",
    "claim_details": {"reason": "test"},
    "subject": "Test subject",
    "description": "Test description",
    "ticket_id": "TKT-1",
    "payment_id": "PAY-1",
    "document_id": "DOC-1",
    "card_id": "CARD-9001",
    "new_pin": "1234",
    "offer_id": "OFF-1",
    "account_id": "ACC-1001",
    "loan_id": "LOAN-5001",
    "fd_id": "FD-3001",
    "customer_id": "CUST-0001",
    "period": "2026-08",
    "months": 6,
    "year": 2026,
    "financial_year": "2025-26",
    "delivery_address": "1 Main Street",
    "document_type": "passport",
    "file_name": "passport.pdf",
    "phone": "+1-555-0100",
    "email": "customer@example.com",
    "address": {"line1": "2 Oak Avenue"},
    "nominee": {"name": "Alex Smith"},
    "limits": {"daily_limit": 1500.0},
    "query": "",
    "topic": "general",
    "preferred_time": "2026-09-11T10:00:00Z",
    "category": "general",
    "loan_type": "personal",
    "tenure_months": 24,
    "product_type": "mutual_fund",
    "reason": "damaged",
    "new_number": True,
    "frequency": "monthly",
    "start_date": "2026-10-01",
    "currency": "USD",
    "reference": "ref",
    "from_date": None,
    "to_date": None,
    "page": 1,
    "alerts": ["low_balance"],
    "note": "",
}


def _call_with_defaults(fn) -> dict:
    """Call ``fn`` supplying defaults for any required parameters."""
    sig = inspect.signature(fn)
    kwargs = {}
    for name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            kwargs[name] = _DEFAULTS.get(name, "x")
    return fn(**kwargs)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_manifest_has_at_least_50_capabilities():
    caps = build_manifest()
    assert len(caps) >= 50


def test_manifest_covers_all_ten_domains():
    caps = build_manifest()
    domains = {c.domain for c in caps}
    assert EXPECTED_DOMAINS.issubset(domains)


def test_manifest_ids_are_unique():
    caps = build_manifest()
    ids = [c.id for c in caps]
    assert len(ids) == len(set(ids))


def test_manifest_are_capability_instances():
    caps = build_manifest()
    assert all(isinstance(c, Capability) for c in caps)


def test_every_manifest_capability_maps_to_callable_bank_function():
    caps = build_manifest()
    for c in caps:
        fn = getattr(bank, c.id, None)
        assert callable(fn), f"bank.{c.id} is not callable"


def test_every_bank_function_returns_success():
    """Smoke-test every manifest function returns a success result."""
    caps = build_manifest()
    for c in caps:
        fn = getattr(bank, c.id)
        result = _call_with_defaults(fn)
        assert isinstance(result, dict), f"{c.id} did not return a dict"
        assert result.get("ok") is True, f"{c.id} did not return success"


# ---------------------------------------------------------------------------
# Demo intent (a): Get my August statement
# ---------------------------------------------------------------------------

def test_intent_get_august_statement():
    result = bank.get_statement(period="2026-08")
    assert result["ok"] is True
    assert result["period"] == "2026-08"
    assert result["format"] == "pdf"
    assert result["statement_id"].startswith("STMT-")
    assert result["file_url"].endswith("2026-08.pdf")
    assert isinstance(result["transactions"], list)
    assert result["transaction_count"] == len(result["transactions"])


# ---------------------------------------------------------------------------
# Demo intent (b): Pay my electricity bill
# ---------------------------------------------------------------------------

def test_intent_pay_electricity_bill():
    result = bank.make_payment(amount=142.75, payee="electricity")
    assert result["ok"] is True
    assert result["payee"] == "electricity"
    assert result["amount"] == 142.75
    assert result["payment_id"].startswith("PAY-")


# ---------------------------------------------------------------------------
# Demo intent (c): Freeze my stolen card
# ---------------------------------------------------------------------------

def test_intent_freeze_stolen_card():
    result = bank.freeze_card(card_id="CARD-9001")
    assert result["ok"] is True
    assert result["card_id"] == "CARD-9001"
    assert result["status"] == "frozen"
    assert result["frozen_at"]


# ---------------------------------------------------------------------------
# Demo intent (d): Get proof of income
# ---------------------------------------------------------------------------

def test_intent_get_income_proof():
    result = bank.get_income_proof()
    assert result["ok"] is True
    assert result["document_id"].startswith("INC-")
    assert result["format"] == "pdf"
    assert result["annual_income"] > 0
    assert result["employer"]


# ---------------------------------------------------------------------------
# Demo intent (e): Export transactions from the last six months
# ---------------------------------------------------------------------------

def test_intent_export_six_months():
    result = bank.export_transactions(months=6)
    assert result["ok"] is True
    assert result["months"] == 6
    assert result["format"] == "csv"
    assert isinstance(result["transactions"], list)
    assert result["count"] == len(result["transactions"])
    assert result["count"] > 0


# ---------------------------------------------------------------------------
# Demo intent dispatch (run_intent)
# ---------------------------------------------------------------------------

def test_run_intent_dispatches_all_five():
    assert bank.run_intent("Get my August statement")["period"] == "2026-08"
    assert bank.run_intent("Pay my electricity bill")["payee"] == "electricity"
    assert bank.run_intent("Freeze my stolen card")["status"] == "frozen"
    assert bank.run_intent("Get proof of income")["document_id"].startswith("INC-")
    assert bank.run_intent("Export transactions from the last six months")["months"] == 6


def test_run_intent_unknown_raises():
    with pytest.raises(ValueError):
        bank.run_intent("do something unknown")
