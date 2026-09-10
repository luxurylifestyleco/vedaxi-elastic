"""Demo Bank — mock banking backend (Phase 8).

A deliberately complicated mock banking application exposing callable
capabilities across ten functional domains:

    accounts, payments, statements/documents, cards, loans, investments,
    insurance, KYC/profile, support, offers

Every function is implemented with synthetic data only. No real financial
credentials, accounts, or external systems are involved. Each function
returns a plain dict whose shape mirrors the corresponding Capability
outputs declared in ``manifest.py``.

The five canonical demo intents are wired end-to-end:

    * "Get my August statement"        -> get_statement(period="2026-08")
    * "Pay my electricity bill"        -> make_payment(amount, payee="electricity")
    * "Freeze my stolen card"          -> freeze_card(card_id)
    * "Get proof of income"            -> get_income_proof()
    * "Export transactions from the last six months"
                                       -> export_transactions(months=6)
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Synthetic data store
# ---------------------------------------------------------------------------

CUSTOMER_ID = "CUST-0001"
DEFAULT_ACCOUNT = "ACC-1001"
DEFAULT_CARD = "CARD-9001"

# A small synthetic ledger used to back balance / statement / export calls.
_LEDGER: List[Dict[str, Any]] = [
    {"date": "2026-08-05", "description": "Salary credit", "amount": 4200.00, "type": "credit"},
    {"date": "2026-08-12", "description": "Grocery store", "amount": -86.40, "type": "debit"},
    {"date": "2026-08-18", "description": "Electricity bill", "amount": -142.75, "type": "debit"},
    {"date": "2026-08-22", "description": "Online shopping", "amount": -210.00, "type": "debit"},
    {"date": "2026-08-27", "description": "Interest credit", "amount": 12.30, "type": "credit"},
    {"date": "2026-07-03", "description": "Salary credit", "amount": 4200.00, "type": "credit"},
    {"date": "2026-07-15", "description": "Rent payment", "amount": -1500.00, "type": "debit"},
    {"date": "2026-07-21", "description": "Fuel", "amount": -55.20, "type": "debit"},
    {"date": "2026-06-02", "description": "Salary credit", "amount": 4200.00, "type": "credit"},
    {"date": "2026-06-10", "description": "Utilities", "amount": -98.10, "type": "debit"},
    {"date": "2026-05-04", "description": "Salary credit", "amount": 4200.00, "type": "credit"},
    {"date": "2026-05-19", "description": "Dining", "amount": -64.90, "type": "debit"},
    {"date": "2026-04-06", "description": "Salary credit", "amount": 4200.00, "type": "credit"},
    {"date": "2026-04-14", "description": "Insurance premium", "amount": -320.00, "type": "debit"},
    {"date": "2026-03-02", "description": "Salary credit", "amount": 4200.00, "type": "credit"},
    {"date": "2026-03-25", "description": "Travel", "amount": -410.00, "type": "debit"},
]


def _new_id(prefix: str) -> str:
    """Generate a synthetic id like ``PAY-<uuid4-hex>``."""
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _ok(**fields: Any) -> Dict[str, Any]:
    """Wrap a result with a success marker."""
    return {"ok": True, "status": "success", **fields}


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

def get_balance(account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Return the current available and ledger balance for an account."""
    return _ok(
        account_id=account_id,
        available_balance=12450.75,
        ledger_balance=12450.75,
        currency="USD",
    )


def get_account_details(account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Fetch full details of an account."""
    return _ok(
        account_id=account_id,
        account_type="checking",
        branch="Main Street",
        status="active",
        opened_on="2019-03-14",
    )


def list_accounts(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """List all accounts held by the customer."""
    return _ok(
        customer_id=customer_id,
        accounts=[
            {"account_id": "ACC-1001", "type": "checking", "status": "active"},
            {"account_id": "ACC-1002", "type": "savings", "status": "active"},
            {"account_id": "ACC-1003", "type": "fixed-deposit", "status": "active"},
        ],
    )


def get_transactions(
    account_id: str = DEFAULT_ACCOUNT,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
) -> Dict[str, Any]:
    """Return a paginated list of transactions for an account."""
    txs = [t for t in _LEDGER if t["date"] >= (from_date or "0000-00-00")]
    if to_date:
        txs = [t for t in txs if t["date"] <= to_date]
    return _ok(
        account_id=account_id,
        transactions=txs,
        total=len(txs),
        next_page=None if page >= 1 else str(page + 1),
    )


def export_transactions(months: int = 6, account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Export account transactions for the last ``months`` months."""
    # Keep the most recent ``months`` worth of ledger entries (synthetic).
    window = _LEDGER[: max(1, months * 2)]
    return _ok(
        account_id=account_id,
        months=months,
        format="csv",
        file_url=f"https://demo-bank.local/exports/{account_id}-{months}m.csv",
        transactions=window,
        count=len(window),
    )


def get_account_summary(account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Return a high-level summary of account activity and balances."""
    return _ok(
        account_id=account_id,
        summary={
            "total_credits": 25200.00,
            "total_debits": 2887.35,
            "net_change": 22312.65,
            "transaction_count": len(_LEDGER),
        },
    )


def set_account_alerts(account_id: str = DEFAULT_ACCOUNT, alerts: Optional[List[str]] = None) -> Dict[str, Any]:
    """Configure alerts for account activity."""
    return _ok(
        account_id=account_id,
        alerts_configured=True,
        alerts=alerts or ["low_balance", "large_transaction"],
    )


# ---------------------------------------------------------------------------
# payments
# ---------------------------------------------------------------------------

def make_payment(
    amount: float = 100.0,
    payee: str = "generic",
    from_account: str = DEFAULT_ACCOUNT,
    currency: str = "USD",
    reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Initiate a single payment to a payee."""
    return _ok(
        payment_id=_new_id("PAY"),
        status="completed",
        amount=amount,
        payee=payee,
        from_account=from_account,
        currency=currency,
        reference=reference or f"payment-{payee}",
    )


def schedule_payment(
    amount: float,
    to_account: str,
    frequency: str = "monthly",
    start_date: str = "2026-10-01",
    from_account: str = DEFAULT_ACCOUNT,
) -> Dict[str, Any]:
    """Schedule a recurring or future-dated payment."""
    return _ok(
        schedule_id=_new_id("SCH"),
        status="scheduled",
        amount=amount,
        to_account=to_account,
        frequency=frequency,
        start_date=start_date,
    )


def cancel_payment(payment_id: str) -> Dict[str, Any]:
    """Cancel a pending or scheduled payment."""
    return _ok(payment_id=payment_id, status="cancelled")


def transfer_funds(
    amount: float,
    to_account: str,
    from_account: str = DEFAULT_ACCOUNT,
) -> Dict[str, Any]:
    """Transfer funds between two accounts owned by the customer."""
    return _ok(
        transfer_id=_new_id("TRF"),
        status="completed",
        amount=amount,
        from_account=from_account,
        to_account=to_account,
    )


def pay_bill(biller_id: str, amount: float, from_account: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Pay a bill to a registered biller."""
    return _ok(
        payment_id=_new_id("PAY"),
        status="completed",
        biller_id=biller_id,
        amount=amount,
        from_account=from_account,
    )


def request_money(amount: float, from_party: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Send a money request to another party."""
    return _ok(
        request_id=_new_id("REQ"),
        status="sent",
        amount=amount,
        from_party=from_party,
        note=note or "",
    )


def split_bill(amount: float, participants: Optional[List[str]] = None) -> Dict[str, Any]:
    """Split a bill or expense among multiple participants."""
    parts = participants or ["alice@example.com", "bob@example.com", "carol@example.com"]
    share = round(amount / len(parts), 2)
    return _ok(
        split_id=_new_id("SPL"),
        status="created",
        amount=amount,
        shares=[{"participant": p, "share": share} for p in parts],
    )


def get_payment_status(payment_id: str) -> Dict[str, Any]:
    """Check the current status of a payment."""
    return _ok(
        payment_id=payment_id,
        status="completed",
        updated_at="2026-09-10T10:00:00Z",
    )


# ---------------------------------------------------------------------------
# statements / documents
# ---------------------------------------------------------------------------

def get_statement(period: str = "2026-08", account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Retrieve a bank statement for an account over a period (YYYY-MM)."""
    year, month = period.split("-")
    txs = [t for t in _LEDGER if t["date"].startswith(f"{year}-{month}")]
    return _ok(
        statement_id=_new_id("STMT"),
        account_id=account_id,
        period=period,
        format="pdf",
        file_url=f"https://demo-bank.local/statements/{account_id}-{period}.pdf",
        opening_balance=8420.00,
        closing_balance=12450.75,
        transactions=txs,
        transaction_count=len(txs),
    )


def download_tax_certificate(account_id: str = DEFAULT_ACCOUNT, financial_year: str = "2025-26") -> Dict[str, Any]:
    """Download a tax certificate for a financial year."""
    return _ok(
        certificate_id=_new_id("CERT"),
        account_id=account_id,
        financial_year=financial_year,
        file_url=f"https://demo-bank.local/documents/tax-{financial_year}.pdf",
    )


def request_cheque_book(account_id: str = DEFAULT_ACCOUNT, delivery_address: Optional[str] = None) -> Dict[str, Any]:
    """Request a new cheque book for an account."""
    return _ok(
        request_id=_new_id("CHQ"),
        status="submitted",
        account_id=account_id,
        delivery_address=delivery_address or "1 Main Street, Springfield",
    )


def get_document_list(account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """List all documents available for an account."""
    return _ok(
        account_id=account_id,
        documents=[
            {"document_id": "DOC-0001", "type": "statement", "period": "2026-08"},
            {"document_id": "DOC-0002", "type": "tax-certificate", "year": "2025-26"},
            {"document_id": "DOC-0003", "type": "income-proof", "year": "2026"},
        ],
    )


def download_document(document_id: str) -> Dict[str, Any]:
    """Download a specific document by id."""
    return _ok(
        document_id=document_id,
        file_url=f"https://demo-bank.local/documents/{document_id}.pdf",
        format="pdf",
    )


def get_interest_certificate(account_id: str = DEFAULT_ACCOUNT, financial_year: str = "2025-26") -> Dict[str, Any]:
    """Download an interest certificate for tax filing."""
    return _ok(
        certificate_id=_new_id("CERT"),
        account_id=account_id,
        financial_year=financial_year,
        interest_earned=148.20,
        file_url=f"https://demo-bank.local/documents/interest-{financial_year}.pdf",
    )


def get_annual_summary(account_id: str = DEFAULT_ACCOUNT, year: int = 2025) -> Dict[str, Any]:
    """Retrieve an annual account summary report."""
    return _ok(
        summary_id=_new_id("SUM"),
        account_id=account_id,
        year=year,
        file_url=f"https://demo-bank.local/statements/annual-{year}.pdf",
    )


def get_income_proof(customer_id: str = CUSTOMER_ID, year: int = 2026) -> Dict[str, Any]:
    """Generate a proof-of-income document for the customer."""
    return _ok(
        document_id=_new_id("INC"),
        customer_id=customer_id,
        year=year,
        format="pdf",
        file_url=f"https://demo-bank.local/documents/income-proof-{year}.pdf",
        annual_income=50400.00,
        employer="Acme Corp",
        issued_on="2026-09-10",
    )


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

def freeze_card(card_id: str = DEFAULT_CARD) -> Dict[str, Any]:
    """Temporarily freeze a card to prevent further transactions."""
    return _ok(card_id=card_id, status="frozen", frozen_at="2026-09-10T10:00:00Z")


def replace_card(card_id: str = DEFAULT_CARD, reason: str = "damaged", new_number: bool = True) -> Dict[str, Any]:
    """Request a replacement card, optionally with a new number."""
    return _ok(
        request_id=_new_id("REQ"),
        status="submitted",
        card_id=card_id,
        reason=reason,
        new_number=new_number,
    )


def change_pin(card_id: str = DEFAULT_CARD, new_pin: str = "****") -> Dict[str, Any]:
    """Change the PIN of a card."""
    return _ok(card_id=card_id, status="pin_changed")


def get_card_details(card_id: str = DEFAULT_CARD) -> Dict[str, Any]:
    """Fetch details of a card including limits and status."""
    return _ok(
        card_id=card_id,
        card_type="debit",
        status="active",
        limits={"daily_limit": 2000.00, "monthly_limit": 10000.00},
    )


def list_cards(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """List all cards issued to the customer."""
    return _ok(
        customer_id=customer_id,
        cards=[
            {"card_id": "CARD-9001", "type": "debit", "status": "active"},
            {"card_id": "CARD-9002", "type": "credit", "status": "active"},
        ],
    )


def set_card_limits(card_id: str = DEFAULT_CARD, limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Set transaction limits for a card."""
    return _ok(
        card_id=card_id,
        limits=limits or {"daily_limit": 1500.00, "monthly_limit": 8000.00},
    )


def report_card_lost(card_id: str = DEFAULT_CARD) -> Dict[str, Any]:
    """Report a card as lost or stolen and block it."""
    return _ok(card_id=card_id, status="blocked", report_id=_new_id("LOST"))


def activate_card(card_id: str = DEFAULT_CARD) -> Dict[str, Any]:
    """Activate a newly issued card."""
    return _ok(card_id=card_id, status="active")


# ---------------------------------------------------------------------------
# loans
# ---------------------------------------------------------------------------

def loan_status(loan_id: str = "LOAN-5001") -> Dict[str, Any]:
    """Check the current status of a loan."""
    return _ok(loan_id=loan_id, status="active", outstanding=18450.00)


def emi_schedule(loan_id: str = "LOAN-5001") -> Dict[str, Any]:
    """Retrieve the EMI repayment schedule for a loan."""
    return _ok(
        loan_id=loan_id,
        schedule=[
            {"installment": 1, "due": "2026-10-01", "amount": 512.50},
            {"installment": 2, "due": "2026-11-01", "amount": 512.50},
            {"installment": 3, "due": "2026-12-01", "amount": 512.50},
        ],
    )


def apply_for_loan(loan_type: str = "personal", amount: float = 10000.0, tenure_months: int = 24) -> Dict[str, Any]:
    """Submit a new loan application."""
    return _ok(
        application_id=_new_id("APP"),
        status="under_review",
        loan_type=loan_type,
        amount=amount,
        tenure_months=tenure_months,
    )


def get_loan_offers(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """Fetch pre-approved loan offers for the customer."""
    return _ok(
        customer_id=customer_id,
        offers=[
            {"offer_id": "LOFF-1", "type": "personal", "amount": 20000.00, "rate": 10.5},
            {"offer_id": "LOFF-2", "type": "auto", "amount": 35000.00, "rate": 9.0},
        ],
    )


def prepay_loan(loan_id: str = "LOAN-5001", amount: float = 1000.0) -> Dict[str, Any]:
    """Make a partial or full prepayment on a loan."""
    return _ok(
        loan_id=loan_id,
        status="prepaid",
        amount=amount,
        outstanding=17450.00,
    )


def get_loan_balance(loan_id: str = "LOAN-5001") -> Dict[str, Any]:
    """Retrieve the outstanding balance of a loan."""
    return _ok(loan_id=loan_id, outstanding=18450.00, currency="USD")


# ---------------------------------------------------------------------------
# investments
# ---------------------------------------------------------------------------

def get_portfolio(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """Retrieve the customer's investment portfolio."""
    return _ok(
        customer_id=customer_id,
        portfolio={"total_value": 45200.00, "total_cost": 41000.00},
        holdings=[
            {"holding_id": "H-1", "name": "Global Equity Fund", "value": 25000.00},
            {"holding_id": "H-2", "name": "Govt Bond Fund", "value": 15200.00},
            {"holding_id": "H-3", "name": "Gold ETF", "value": 5000.00},
        ],
    )


def get_market_rates(product_type: str = "mutual_fund") -> Dict[str, Any]:
    """Fetch current market rates for investment products."""
    return _ok(
        product_type=product_type,
        rates=[
            {"product": "Equity Fund", "rate": 12.4},
            {"product": "Bond Fund", "rate": 6.8},
            {"product": "Money Market", "rate": 4.2},
        ],
    )


def buy_investment(product_id: str, amount: float) -> Dict[str, Any]:
    """Purchase an investment product."""
    return _ok(
        order_id=_new_id("ORD"),
        status="executed",
        product_id=product_id,
        amount=amount,
    )


def sell_investment(holding_id: str, units: float) -> Dict[str, Any]:
    """Sell an investment product."""
    return _ok(
        order_id=_new_id("ORD"),
        status="executed",
        holding_id=holding_id,
        units=units,
    )


def get_investment_performance(holding_id: str = "H-1") -> Dict[str, Any]:
    """Retrieve performance metrics for an investment."""
    return _ok(
        holding_id=holding_id,
        returns={"ytd": 8.2, "one_year": 12.4, "since_inception": 18.9},
    )


def get_fd_details(fd_id: str = "FD-3001") -> Dict[str, Any]:
    """Fetch details of a fixed deposit."""
    return _ok(
        fd_id=fd_id,
        principal=10000.00,
        maturity_date="2027-03-14",
        rate=7.0,
    )


# ---------------------------------------------------------------------------
# insurance
# ---------------------------------------------------------------------------

def get_insurance_policies(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """List all insurance policies held by the customer."""
    return _ok(
        customer_id=customer_id,
        policies=[
            {"policy_id": "POL-1", "type": "term-life", "status": "active"},
            {"policy_id": "POL-2", "type": "health", "status": "active"},
        ],
    )


def get_policy_details(policy_id: str = "POL-1") -> Dict[str, Any]:
    """Fetch details of a specific insurance policy."""
    return _ok(
        policy_id=policy_id,
        coverage={"sum_assured": 500000.00, "premium": 320.00, "term_years": 20},
        status="active",
    )


def file_insurance_claim(policy_id: str, claim_details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Submit a new insurance claim."""
    return _ok(
        claim_id=_new_id("CLM"),
        status="submitted",
        policy_id=policy_id,
        claim_details=claim_details or {"reason": "hospitalization"},
    )


def renew_policy(policy_id: str = "POL-1") -> Dict[str, Any]:
    """Renew an expiring insurance policy."""
    return _ok(
        policy_id=policy_id,
        status="renewed",
        new_expiry="2027-09-10",
    )


def get_insurance_cover(policy_id: str = "POL-1") -> Dict[str, Any]:
    """Retrieve the coverage details of a policy."""
    return _ok(
        policy_id=policy_id,
        cover={"sum_assured": 500000.00, "inclusions": ["hospital", "surgery"], "exclusions": ["pre-existing"]},
    )


# ---------------------------------------------------------------------------
# KYC / profile
# ---------------------------------------------------------------------------

def change_address(address: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Update the customer's registered address."""
    return _ok(
        status="updated",
        updated_at="2026-09-10T10:00:00Z",
        address=address or {"line1": "2 Oak Avenue", "city": "Springfield", "postcode": "12345"},
    )


def update_contact_details(phone: Optional[str] = None, email: Optional[str] = None) -> Dict[str, Any]:
    """Update the customer's phone or email contact details."""
    return _ok(
        status="updated",
        updated_at="2026-09-10T10:00:00Z",
        phone=phone or "+1-555-0100",
        email=email or "customer@example.com",
    )


def get_profile(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """Retrieve the customer's profile information."""
    return _ok(
        customer_id=customer_id,
        profile={
            "name": "Jordan Smith",
            "email": "customer@example.com",
            "phone": "+1-555-0100",
            "kyc_status": "verified",
        },
    )


def upload_kyc_document(document_type: str = "passport", file_name: str = "passport.pdf") -> Dict[str, Any]:
    """Upload a KYC document for verification."""
    return _ok(
        document_id=_new_id("KYC"),
        status="under_review",
        document_type=document_type,
        file_name=file_name,
    )


def check_kyc_status(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """Check the status of the customer's KYC verification."""
    return _ok(
        customer_id=customer_id,
        status="verified",
        verified_at="2026-01-15T09:00:00Z",
    )


def update_nominee(account_id: str = DEFAULT_ACCOUNT, nominee: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add or update a nominee for an account."""
    return _ok(
        status="updated",
        updated_at="2026-09-10T10:00:00Z",
        account_id=account_id,
        nominee=nominee or {"name": "Alex Smith", "relation": "spouse"},
    )


# ---------------------------------------------------------------------------
# support
# ---------------------------------------------------------------------------

def create_support_ticket(subject: str, description: str, category: str = "general") -> Dict[str, Any]:
    """Create a new customer support ticket."""
    return _ok(
        ticket_id=_new_id("TKT"),
        status="open",
        subject=subject,
        category=category,
    )


def get_support_ticket_status(ticket_id: str) -> Dict[str, Any]:
    """Check the status of a support ticket."""
    return _ok(
        ticket_id=ticket_id,
        status="in_progress",
        updated_at="2026-09-10T10:00:00Z",
    )


def chat_with_agent(topic: str = "general") -> Dict[str, Any]:
    """Start a chat session with a support agent."""
    return _ok(
        session_id=_new_id("CHAT"),
        status="connected",
        topic=topic,
    )


def get_faq(query: str = "") -> Dict[str, Any]:
    """Retrieve frequently asked questions and answers."""
    return _ok(
        query=query,
        faqs=[
            {"question": "How do I freeze my card?", "answer": "Use the freeze card option in the app."},
            {"question": "How do I get a statement?", "answer": "Statements are available under Documents."},
        ],
    )


def schedule_call_back(preferred_time: str = "2026-09-11T10:00:00Z", topic: str = "general") -> Dict[str, Any]:
    """Schedule a call back from a support agent."""
    return _ok(
        request_id=_new_id("CB"),
        status="scheduled",
        preferred_time=preferred_time,
        topic=topic,
    )


# ---------------------------------------------------------------------------
# offers
# ---------------------------------------------------------------------------

def get_offers(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """List available offers and promotions for the customer."""
    return _ok(
        customer_id=customer_id,
        offers=[
            {"offer_id": "OFF-1", "title": "5% cashback on dining", "valid_until": "2026-12-31"},
            {"offer_id": "OFF-2", "title": "0% EMI on electronics", "valid_until": "2026-11-30"},
        ],
    )


def get_offer_details(offer_id: str = "OFF-1") -> Dict[str, Any]:
    """Fetch details of a specific offer."""
    return _ok(
        offer_id=offer_id,
        terms={"min_spend": 50.00, "max_cashback": 25.00},
        valid_until="2026-12-31",
    )


def redeem_offer(offer_id: str, account_id: str = DEFAULT_ACCOUNT) -> Dict[str, Any]:
    """Redeem an offer or coupon."""
    return _ok(
        redemption_id=_new_id("RED"),
        status="redeemed",
        offer_id=offer_id,
        account_id=account_id,
    )


def get_rewards(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """Retrieve the customer's rewards points balance and history."""
    return _ok(
        customer_id=customer_id,
        points=1250,
        history=[
            {"date": "2026-08-20", "points": 120, "source": "dining"},
            {"date": "2026-07-15", "points": 80, "source": "shopping"},
        ],
    )


def get_cashback(customer_id: str = CUSTOMER_ID) -> Dict[str, Any]:
    """Retrieve cashback earned and available for redemption."""
    return _ok(
        customer_id=customer_id,
        cashback=42.50,
        available=42.50,
    )


# ---------------------------------------------------------------------------
# Demo intent dispatch
# ---------------------------------------------------------------------------

def run_intent(intent: str, **kwargs: Any) -> Dict[str, Any]:
    """Dispatch a named demo intent to its bank function.

    This is the end-to-end wiring for the five canonical demo intents.
    """
    intent = intent.strip().lower()
    if "august statement" in intent or "statement" in intent:
        return get_statement(period=kwargs.get("period", "2026-08"))
    if "electricity" in intent or "pay" in intent:
        return make_payment(
            amount=kwargs.get("amount", 142.75),
            payee=kwargs.get("payee", "electricity"),
        )
    if "freeze" in intent or "stolen" in intent:
        return freeze_card(card_id=kwargs.get("card_id", DEFAULT_CARD))
    if "income" in intent or "proof" in intent:
        return get_income_proof()
    if "export" in intent or "six months" in intent:
        return export_transactions(months=kwargs.get("months", 6))
    raise ValueError(f"unknown intent: {intent}")
