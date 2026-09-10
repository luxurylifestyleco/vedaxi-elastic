"""Seed data for the Elastic Web capability registry.

This module provides a curated set of realistic demo-bank capabilities
across ten functional domains. It is mock data only — no real credentials,
accounts, or external systems are involved. It is used to populate a
:class:`~registry.CapabilityRegistry` for development, testing, and demos.

Domains covered:
    accounts, payments, statements/documents, cards, loans, investments,
    insurance, KYC/profile, support, offers
"""

from __future__ import annotations

from typing import List

from capability import Capability
from registry import CapabilityRegistry


def _cap(
    id: str,
    name: str,
    description: str,
    domain: str,
    inputs: dict,
    outputs: dict,
    permissions: List[str],
    endpoint: str,
    latency_ms: int,
    cost: float,
    success: float,
    tags: List[str],
) -> Capability:
    """Build a single Capability with sensible defaults filled in."""
    return Capability(
        id=id,
        name=name,
        description=description,
        domain=domain,
        inputs=inputs,
        outputs=outputs,
        permissions=permissions,
        provider="demo-bank",
        protocol="rest",
        endpoint=endpoint,
        estimated_latency=latency_ms,
        estimated_cost=cost,
        historical_success=success,
        metadata={"tags": tags, "version": "1.0", "source": "seed"},
    )


def build_seed_capabilities() -> List[Capability]:
    """Return the full list of seeded demo-bank capabilities."""
    caps: List[Capability] = []

    # ------------------------------------------------------------------
    # accounts
    # ------------------------------------------------------------------
    caps.append(_cap(
        "get_balance", "Get Account Balance",
        "Retrieve the current available and ledger balance for an account.",
        "accounts",
        {"account_id": "string"},
        {"account_id": "string", "available_balance": "number", "ledger_balance": "number", "currency": "string"},
        ["accounts:read"],
        "/v1/accounts/{account_id}/balance", 40, 0.001, 0.99, ["balance", "read"],
    ))
    caps.append(_cap(
        "get_account_details", "Get Account Details",
        "Fetch full details of an account including type, branch, and status.",
        "accounts",
        {"account_id": "string"},
        {"account_id": "string", "account_type": "string", "branch": "string", "status": "string"},
        ["accounts:read"],
        "/v1/accounts/{account_id}", 50, 0.001, 0.98, ["account", "read"],
    ))
    caps.append(_cap(
        "list_accounts", "List Accounts",
        "List all accounts held by the customer.",
        "accounts",
        {"customer_id": "string"},
        {"accounts": "array"},
        ["accounts:read"],
        "/v1/accounts", 60, 0.001, 0.99, ["account", "list"],
    ))
    caps.append(_cap(
        "get_transactions", "Get Transactions",
        "Return a paginated list of transactions for an account over a date range.",
        "accounts",
        {"account_id": "string", "from": "date", "to": "date", "page": "integer"},
        {"transactions": "array", "total": "integer", "next_page": "string"},
        ["accounts:read"],
        "/v1/accounts/{account_id}/transactions", 90, 0.002, 0.97, ["transactions", "read"],
    ))
    caps.append(_cap(
        "export_transactions", "Export Transactions",
        "Export account transactions to a CSV or PDF file.",
        "accounts",
        {"account_id": "string", "format": "string", "from": "date", "to": "date"},
        {"file_url": "string", "format": "string"},
        ["accounts:read", "documents:create"],
        "/v1/accounts/{account_id}/transactions/export", 300, 0.005, 0.95, ["export", "transactions"],
    ))
    caps.append(_cap(
        "get_account_summary", "Get Account Summary",
        "Return a high-level summary of account activity and balances.",
        "accounts",
        {"account_id": "string"},
        {"account_id": "string", "summary": "object"},
        ["accounts:read"],
        "/v1/accounts/{account_id}/summary", 70, 0.001, 0.98, ["summary", "read"],
    ))
    caps.append(_cap(
        "set_account_alerts", "Set Account Alerts",
        "Configure alerts for account activity such as low balance or large transactions.",
        "accounts",
        {"account_id": "string", "alerts": "array"},
        {"account_id": "string", "alerts_configured": "boolean"},
        ["accounts:write"],
        "/v1/accounts/{account_id}/alerts", 120, 0.002, 0.96, ["alerts", "write"],
    ))

    # ------------------------------------------------------------------
    # payments
    # ------------------------------------------------------------------
    caps.append(_cap(
        "make_payment", "Make Payment",
        "Initiate a single payment to a payee or account.",
        "payments",
        {"from_account": "string", "to_account": "string", "amount": "number", "currency": "string", "reference": "string"},
        {"payment_id": "string", "status": "string"},
        ["payments:write"],
        "/v1/payments", 200, 0.01, 0.99, ["payment", "write"],
    ))
    caps.append(_cap(
        "schedule_payment", "Schedule Payment",
        "Schedule a recurring or future-dated payment.",
        "payments",
        {"from_account": "string", "to_account": "string", "amount": "number", "frequency": "string", "start_date": "date"},
        {"schedule_id": "string", "status": "string"},
        ["payments:write"],
        "/v1/payments/schedule", 180, 0.01, 0.98, ["payment", "schedule"],
    ))
    caps.append(_cap(
        "cancel_payment", "Cancel Payment",
        "Cancel a pending or scheduled payment.",
        "payments",
        {"payment_id": "string"},
        {"payment_id": "string", "status": "string"},
        ["payments:write"],
        "/v1/payments/{payment_id}/cancel", 150, 0.005, 0.97, ["payment", "cancel"],
    ))
    caps.append(_cap(
        "transfer_funds", "Transfer Funds",
        "Transfer funds between two accounts owned by the customer.",
        "payments",
        {"from_account": "string", "to_account": "string", "amount": "number"},
        {"transfer_id": "string", "status": "string"},
        ["payments:write"],
        "/v1/transfers", 190, 0.01, 0.99, ["transfer", "write"],
    ))
    caps.append(_cap(
        "pay_bill", "Pay Bill",
        "Pay a bill to a registered biller.",
        "payments",
        {"biller_id": "string", "amount": "number", "from_account": "string"},
        {"payment_id": "string", "status": "string"},
        ["payments:write"],
        "/v1/bills/pay", 210, 0.01, 0.98, ["bill", "pay"],
    ))
    caps.append(_cap(
        "request_money", "Request Money",
        "Send a money request to another party.",
        "payments",
        {"from": "string", "amount": "number", "note": "string"},
        {"request_id": "string", "status": "string"},
        ["payments:write"],
        "/v1/payments/request", 160, 0.005, 0.97, ["request", "money"],
    ))
    caps.append(_cap(
        "split_bill", "Split Bill",
        "Split a bill or expense among multiple participants.",
        "payments",
        {"amount": "number", "participants": "array"},
        {"split_id": "string", "shares": "array"},
        ["payments:write"],
        "/v1/bills/split", 170, 0.005, 0.96, ["split", "bill"],
    ))
    caps.append(_cap(
        "get_payment_status", "Get Payment Status",
        "Check the current status of a payment.",
        "payments",
        {"payment_id": "string"},
        {"payment_id": "string", "status": "string", "updated_at": "datetime"},
        ["payments:read"],
        "/v1/payments/{payment_id}", 60, 0.001, 0.99, ["payment", "status"],
    ))

    # ------------------------------------------------------------------
    # statements / documents
    # ------------------------------------------------------------------
    caps.append(_cap(
        "get_statement", "Get Statement",
        "Retrieve a bank statement for an account over a period.",
        "statements/documents",
        {"account_id": "string", "from": "date", "to": "date", "format": "string"},
        {"statement_id": "string", "file_url": "string", "format": "string"},
        ["documents:read"],
        "/v1/statements", 250, 0.005, 0.98, ["statement", "read"],
    ))
    caps.append(_cap(
        "download_tax_certificate", "Download Tax Certificate",
        "Download a tax certificate (e.g. interest certificate) for a financial year.",
        "statements/documents",
        {"account_id": "string", "financial_year": "string"},
        {"certificate_id": "string", "file_url": "string"},
        ["documents:read"],
        "/v1/documents/tax-certificate", 300, 0.005, 0.97, ["tax", "certificate"],
    ))
    caps.append(_cap(
        "request_cheque_book", "Request Cheque Book",
        "Request a new cheque book for an account.",
        "statements/documents",
        {"account_id": "string", "delivery_address": "string"},
        {"request_id": "string", "status": "string"},
        ["documents:write"],
        "/v1/cheque-book/request", 200, 0.01, 0.95, ["cheque", "request"],
    ))
    caps.append(_cap(
        "get_document_list", "Get Document List",
        "List all documents available for an account.",
        "statements/documents",
        {"account_id": "string"},
        {"documents": "array"},
        ["documents:read"],
        "/v1/documents", 80, 0.001, 0.98, ["documents", "list"],
    ))
    caps.append(_cap(
        "download_document", "Download Document",
        "Download a specific document by id.",
        "statements/documents",
        {"document_id": "string"},
        {"file_url": "string", "format": "string"},
        ["documents:read"],
        "/v1/documents/{document_id}/download", 220, 0.005, 0.97, ["document", "download"],
    ))
    caps.append(_cap(
        "get_interest_certificate", "Get Interest Certificate",
        "Download an interest certificate for tax filing.",
        "statements/documents",
        {"account_id": "string", "financial_year": "string"},
        {"certificate_id": "string", "file_url": "string"},
        ["documents:read"],
        "/v1/documents/interest-certificate", 300, 0.005, 0.96, ["interest", "certificate"],
    ))
    caps.append(_cap(
        "get_annual_summary", "Get Annual Summary",
        "Retrieve an annual account summary report.",
        "statements/documents",
        {"account_id": "string", "year": "integer"},
        {"summary_id": "string", "file_url": "string"},
        ["documents:read"],
        "/v1/statements/annual", 280, 0.005, 0.97, ["annual", "summary"],
    ))

    # ------------------------------------------------------------------
    # cards
    # ------------------------------------------------------------------
    caps.append(_cap(
        "freeze_card", "Freeze Card",
        "Temporarily freeze a card to prevent further transactions.",
        "cards",
        {"card_id": "string"},
        {"card_id": "string", "status": "string"},
        ["cards:write"],
        "/v1/cards/{card_id}/freeze", 120, 0.005, 0.99, ["card", "freeze"],
    ))
    caps.append(_cap(
        "replace_card", "Replace Card",
        "Request a replacement card, optionally with a new number.",
        "cards",
        {"card_id": "string", "reason": "string", "new_number": "boolean"},
        {"request_id": "string", "status": "string"},
        ["cards:write"],
        "/v1/cards/{card_id}/replace", 250, 0.01, 0.96, ["card", "replace"],
    ))
    caps.append(_cap(
        "change_pin", "Change PIN",
        "Change the PIN of a card.",
        "cards",
        {"card_id": "string", "new_pin": "string"},
        {"card_id": "string", "status": "string"},
        ["cards:write"],
        "/v1/cards/{card_id}/pin", 130, 0.005, 0.98, ["card", "pin"],
    ))
    caps.append(_cap(
        "get_card_details", "Get Card Details",
        "Fetch details of a card including limits and status.",
        "cards",
        {"card_id": "string"},
        {"card_id": "string", "card_type": "string", "status": "string", "limits": "object"},
        ["cards:read"],
        "/v1/cards/{card_id}", 60, 0.001, 0.99, ["card", "read"],
    ))
    caps.append(_cap(
        "list_cards", "List Cards",
        "List all cards issued to the customer.",
        "cards",
        {"customer_id": "string"},
        {"cards": "array"},
        ["cards:read"],
        "/v1/cards", 70, 0.001, 0.99, ["card", "list"],
    ))
    caps.append(_cap(
        "set_card_limits", "Set Card Limits",
        "Set transaction limits for a card.",
        "cards",
        {"card_id": "string", "limits": "object"},
        {"card_id": "string", "limits": "object"},
        ["cards:write"],
        "/v1/cards/{card_id}/limits", 140, 0.005, 0.97, ["card", "limits"],
    ))
    caps.append(_cap(
        "report_card_lost", "Report Card Lost",
        "Report a card as lost or stolen and block it.",
        "cards",
        {"card_id": "string"},
        {"card_id": "string", "status": "string"},
        ["cards:write"],
        "/v1/cards/{card_id}/lost", 150, 0.005, 0.99, ["card", "lost"],
    ))
    caps.append(_cap(
        "activate_card", "Activate Card",
        "Activate a newly issued card.",
        "cards",
        {"card_id": "string"},
        {"card_id": "string", "status": "string"},
        ["cards:write"],
        "/v1/cards/{card_id}/activate", 110, 0.005, 0.98, ["card", "activate"],
    ))

    # ------------------------------------------------------------------
    # loans
    # ------------------------------------------------------------------
    caps.append(_cap(
        "loan_status", "Get Loan Status",
        "Check the current status of a loan.",
        "loans",
        {"loan_id": "string"},
        {"loan_id": "string", "status": "string", "outstanding": "number"},
        ["loans:read"],
        "/v1/loans/{loan_id}", 70, 0.001, 0.98, ["loan", "status"],
    ))
    caps.append(_cap(
        "emi_schedule", "Get EMI Schedule",
        "Retrieve the EMI repayment schedule for a loan.",
        "loans",
        {"loan_id": "string"},
        {"loan_id": "string", "schedule": "array"},
        ["loans:read"],
        "/v1/loans/{loan_id}/emi-schedule", 90, 0.002, 0.97, ["loan", "emi"],
    ))
    caps.append(_cap(
        "apply_for_loan", "Apply for Loan",
        "Submit a new loan application.",
        "loans",
        {"loan_type": "string", "amount": "number", "tenure_months": "integer"},
        {"application_id": "string", "status": "string"},
        ["loans:write"],
        "/v1/loans/apply", 400, 0.02, 0.95, ["loan", "apply"],
    ))
    caps.append(_cap(
        "get_loan_offers", "Get Loan Offers",
        "Fetch pre-approved loan offers for the customer.",
        "loans",
        {"customer_id": "string"},
        {"offers": "array"},
        ["loans:read"],
        "/v1/loans/offers", 100, 0.002, 0.96, ["loan", "offers"],
    ))
    caps.append(_cap(
        "prepay_loan", "Prepay Loan",
        "Make a partial or full prepayment on a loan.",
        "loans",
        {"loan_id": "string", "amount": "number"},
        {"loan_id": "string", "status": "string", "outstanding": "number"},
        ["loans:write"],
        "/v1/loans/{loan_id}/prepay", 220, 0.01, 0.97, ["loan", "prepay"],
    ))
    caps.append(_cap(
        "get_loan_balance", "Get Loan Balance",
        "Retrieve the outstanding balance of a loan.",
        "loans",
        {"loan_id": "string"},
        {"loan_id": "string", "outstanding": "number", "currency": "string"},
        ["loans:read"],
        "/v1/loans/{loan_id}/balance", 60, 0.001, 0.98, ["loan", "balance"],
    ))

    # ------------------------------------------------------------------
    # investments
    # ------------------------------------------------------------------
    caps.append(_cap(
        "get_portfolio", "Get Portfolio",
        "Retrieve the customer's investment portfolio.",
        "investments",
        {"customer_id": "string"},
        {"portfolio": "object", "holdings": "array"},
        ["investments:read"],
        "/v1/investments/portfolio", 120, 0.002, 0.97, ["portfolio", "read"],
    ))
    caps.append(_cap(
        "get_market_rates", "Get Market Rates",
        "Fetch current market rates for investment products.",
        "investments",
        {"product_type": "string"},
        {"rates": "array"},
        ["investments:read"],
        "/v1/investments/rates", 80, 0.001, 0.99, ["market", "rates"],
    ))
    caps.append(_cap(
        "buy_investment", "Buy Investment",
        "Purchase an investment product.",
        "investments",
        {"product_id": "string", "amount": "number"},
        {"order_id": "string", "status": "string"},
        ["investments:write"],
        "/v1/investments/buy", 250, 0.01, 0.96, ["investment", "buy"],
    ))
    caps.append(_cap(
        "sell_investment", "Sell Investment",
        "Sell an investment product.",
        "investments",
        {"holding_id": "string", "units": "number"},
        {"order_id": "string", "status": "string"},
        ["investments:write"],
        "/v1/investments/sell", 250, 0.01, 0.96, ["investment", "sell"],
    ))
    caps.append(_cap(
        "get_investment_performance", "Get Investment Performance",
        "Retrieve performance metrics for an investment.",
        "investments",
        {"holding_id": "string"},
        {"holding_id": "string", "returns": "object"},
        ["investments:read"],
        "/v1/investments/{holding_id}/performance", 110, 0.002, 0.97, ["investment", "performance"],
    ))
    caps.append(_cap(
        "get_fd_details", "Get Fixed Deposit Details",
        "Fetch details of a fixed deposit.",
        "investments",
        {"fd_id": "string"},
        {"fd_id": "string", "principal": "number", "maturity_date": "date", "rate": "number"},
        ["investments:read"],
        "/v1/investments/fd/{fd_id}", 90, 0.001, 0.98, ["fd", "fixed-deposit"],
    ))

    # ------------------------------------------------------------------
    # insurance
    # ------------------------------------------------------------------
    caps.append(_cap(
        "get_insurance_policies", "Get Insurance Policies",
        "List all insurance policies held by the customer.",
        "insurance",
        {"customer_id": "string"},
        {"policies": "array"},
        ["insurance:read"],
        "/v1/insurance/policies", 90, 0.001, 0.98, ["insurance", "policies"],
    ))
    caps.append(_cap(
        "get_policy_details", "Get Policy Details",
        "Fetch details of a specific insurance policy.",
        "insurance",
        {"policy_id": "string"},
        {"policy_id": "string", "coverage": "object", "status": "string"},
        ["insurance:read"],
        "/v1/insurance/policies/{policy_id}", 80, 0.001, 0.98, ["insurance", "policy"],
    ))
    caps.append(_cap(
        "file_insurance_claim", "File Insurance Claim",
        "Submit a new insurance claim.",
        "insurance",
        {"policy_id": "string", "claim_details": "object"},
        {"claim_id": "string", "status": "string"},
        ["insurance:write"],
        "/v1/insurance/claims", 350, 0.02, 0.94, ["insurance", "claim"],
    ))
    caps.append(_cap(
        "renew_policy", "Renew Policy",
        "Renew an expiring insurance policy.",
        "insurance",
        {"policy_id": "string"},
        {"policy_id": "string", "status": "string", "new_expiry": "date"},
        ["insurance:write"],
        "/v1/insurance/policies/{policy_id}/renew", 200, 0.01, 0.96, ["insurance", "renew"],
    ))
    caps.append(_cap(
        "get_insurance_cover", "Get Insurance Cover",
        "Retrieve the coverage details of a policy.",
        "insurance",
        {"policy_id": "string"},
        {"policy_id": "string", "cover": "object"},
        ["insurance:read"],
        "/v1/insurance/policies/{policy_id}/cover", 80, 0.001, 0.98, ["insurance", "cover"],
    ))

    # ------------------------------------------------------------------
    # KYC / profile
    # ------------------------------------------------------------------
    caps.append(_cap(
        "change_address", "Change Address",
        "Update the customer's registered address.",
        "KYC/profile",
        {"address": "object"},
        {"status": "string", "updated_at": "datetime"},
        ["profile:write"],
        "/v1/profile/address", 150, 0.005, 0.97, ["address", "profile"],
    ))
    caps.append(_cap(
        "update_contact_details", "Update Contact Details",
        "Update the customer's phone or email contact details.",
        "KYC/profile",
        {"phone": "string", "email": "string"},
        {"status": "string", "updated_at": "datetime"},
        ["profile:write"],
        "/v1/profile/contact", 140, 0.005, 0.97, ["contact", "profile"],
    ))
    caps.append(_cap(
        "get_profile", "Get Profile",
        "Retrieve the customer's profile information.",
        "KYC/profile",
        {"customer_id": "string"},
        {"profile": "object"},
        ["profile:read"],
        "/v1/profile", 60, 0.001, 0.99, ["profile", "read"],
    ))
    caps.append(_cap(
        "upload_kyc_document", "Upload KYC Document",
        "Upload a KYC document for verification.",
        "KYC/profile",
        {"document_type": "string", "file": "binary"},
        {"document_id": "string", "status": "string"},
        ["profile:write"],
        "/v1/kyc/documents", 300, 0.01, 0.95, ["kyc", "upload"],
    ))
    caps.append(_cap(
        "check_kyc_status", "Check KYC Status",
        "Check the status of the customer's KYC verification.",
        "KYC/profile",
        {"customer_id": "string"},
        {"status": "string", "verified_at": "datetime"},
        ["profile:read"],
        "/v1/kyc/status", 60, 0.001, 0.99, ["kyc", "status"],
    ))
    caps.append(_cap(
        "update_nominee", "Update Nominee",
        "Add or update a nominee for an account.",
        "KYC/profile",
        {"account_id": "string", "nominee": "object"},
        {"status": "string", "updated_at": "datetime"},
        ["profile:write"],
        "/v1/profile/nominee", 160, 0.005, 0.96, ["nominee", "profile"],
    ))

    # ------------------------------------------------------------------
    # support
    # ------------------------------------------------------------------
    caps.append(_cap(
        "create_support_ticket", "Create Support Ticket",
        "Create a new customer support ticket.",
        "support",
        {"subject": "string", "description": "string", "category": "string"},
        {"ticket_id": "string", "status": "string"},
        ["support:write"],
        "/v1/support/tickets", 120, 0.005, 0.98, ["support", "ticket"],
    ))
    caps.append(_cap(
        "get_support_ticket_status", "Get Support Ticket Status",
        "Check the status of a support ticket.",
        "support",
        {"ticket_id": "string"},
        {"ticket_id": "string", "status": "string", "updated_at": "datetime"},
        ["support:read"],
        "/v1/support/tickets/{ticket_id}", 60, 0.001, 0.99, ["support", "ticket"],
    ))
    caps.append(_cap(
        "chat_with_agent", "Chat with Agent",
        "Start a chat session with a support agent.",
        "support",
        {"topic": "string"},
        {"session_id": "string", "status": "string"},
        ["support:write"],
        "/v1/support/chat", 100, 0.005, 0.97, ["support", "chat"],
    ))
    caps.append(_cap(
        "get_faq", "Get FAQ",
        "Retrieve frequently asked questions and answers.",
        "support",
        {"query": "string"},
        {"faqs": "array"},
        ["support:read"],
        "/v1/support/faq", 50, 0.001, 0.99, ["support", "faq"],
    ))
    caps.append(_cap(
        "schedule_call_back", "Schedule Call Back",
        "Schedule a call back from a support agent.",
        "support",
        {"preferred_time": "datetime", "topic": "string"},
        {"request_id": "string", "status": "string"},
        ["support:write"],
        "/v1/support/callback", 130, 0.005, 0.97, ["support", "callback"],
    ))

    # ------------------------------------------------------------------
    # offers
    # ------------------------------------------------------------------
    caps.append(_cap(
        "get_offers", "Get Offers",
        "List available offers and promotions for the customer.",
        "offers",
        {"customer_id": "string"},
        {"offers": "array"},
        ["offers:read"],
        "/v1/offers", 70, 0.001, 0.98, ["offers", "list"],
    ))
    caps.append(_cap(
        "get_offer_details", "Get Offer Details",
        "Fetch details of a specific offer.",
        "offers",
        {"offer_id": "string"},
        {"offer_id": "string", "terms": "object", "valid_until": "date"},
        ["offers:read"],
        "/v1/offers/{offer_id}", 60, 0.001, 0.99, ["offers", "details"],
    ))
    caps.append(_cap(
        "redeem_offer", "Redeem Offer",
        "Redeem an offer or coupon.",
        "offers",
        {"offer_id": "string", "account_id": "string"},
        {"redemption_id": "string", "status": "string"},
        ["offers:write"],
        "/v1/offers/{offer_id}/redeem", 150, 0.005, 0.96, ["offers", "redeem"],
    ))
    caps.append(_cap(
        "get_rewards", "Get Rewards",
        "Retrieve the customer's rewards points balance and history.",
        "offers",
        {"customer_id": "string"},
        {"points": "number", "history": "array"},
        ["offers:read"],
        "/v1/rewards", 80, 0.001, 0.98, ["rewards", "points"],
    ))
    caps.append(_cap(
        "get_cashback", "Get Cashback",
        "Retrieve cashback earned and available for redemption.",
        "offers",
        {"customer_id": "string"},
        {"cashback": "number", "available": "number"},
        ["offers:read"],
        "/v1/cashback", 80, 0.001, 0.98, ["cashback", "rewards"],
    ))

    return caps


def seed_registry(registry: CapabilityRegistry) -> int:
    """Register all seed capabilities into a registry.

    Args:
        registry: The registry to populate.

    Returns:
        The number of capabilities registered.
    """
    for cap in build_seed_capabilities():
        registry.register(cap)
    return len(registry)


def main() -> None:
    """Populate a fresh registry and print a summary."""
    reg = CapabilityRegistry()
    count = seed_registry(reg)
    domains = sorted({c.domain for c in reg.list()})
    print(f"Seeded {count} capabilities across {len(domains)} domains:")
    for d in domains:
        n = sum(1 for c in reg.list() if c.domain == d)
        print(f"  {d}: {n}")


if __name__ == "__main__":
    main()
