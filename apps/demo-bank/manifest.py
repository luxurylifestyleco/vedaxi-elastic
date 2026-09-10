"""Capability manifest for the Demo Bank application (Phase 8).

Builds a :class:`~capability.Capability` object for every callable function
in :mod:`bank`, reusing the Capability model from the capability-registry
package. The manifest is the discovery/routing surface: each entry declares
the domain, inputs, outputs, permissions, and endpoint for a bank function.

The manifest is derived from an explicit table so that the declared
Capability metadata stays in lock-step with the implemented functions.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

import bank
from capability import Capability

# ---------------------------------------------------------------------------
# Manifest table: (function_name, domain, name, description, inputs, outputs,
#                  permissions, endpoint)
# ---------------------------------------------------------------------------

_MANIFEST: List[tuple] = [
    # accounts
    ("get_balance", "accounts", "Get Account Balance",
     "Retrieve the current available and ledger balance for an account.",
     {"account_id": "string"}, {"account_id": "string", "available_balance": "number", "ledger_balance": "number", "currency": "string"},
     ["accounts:read"], "/v1/accounts/{account_id}/balance"),
    ("get_account_details", "accounts", "Get Account Details",
     "Fetch full details of an account including type, branch, and status.",
     {"account_id": "string"}, {"account_id": "string", "account_type": "string", "branch": "string", "status": "string"},
     ["accounts:read"], "/v1/accounts/{account_id}"),
    ("list_accounts", "accounts", "List Accounts",
     "List all accounts held by the customer.",
     {"customer_id": "string"}, {"accounts": "array"},
     ["accounts:read"], "/v1/accounts"),
    ("get_transactions", "accounts", "Get Transactions",
     "Return a paginated list of transactions for an account over a date range.",
     {"account_id": "string", "from_date": "date", "to_date": "date", "page": "integer"},
     {"transactions": "array", "total": "integer", "next_page": "string"},
     ["accounts:read"], "/v1/accounts/{account_id}/transactions"),
    ("export_transactions", "accounts", "Export Transactions",
     "Export account transactions for the last N months to a CSV file.",
     {"months": "integer", "account_id": "string"},
     {"file_url": "string", "format": "string", "transactions": "array", "count": "integer"},
     ["accounts:read", "documents:create"], "/v1/accounts/{account_id}/transactions/export"),
    ("get_account_summary", "accounts", "Get Account Summary",
     "Return a high-level summary of account activity and balances.",
     {"account_id": "string"}, {"account_id": "string", "summary": "object"},
     ["accounts:read"], "/v1/accounts/{account_id}/summary"),
    ("set_account_alerts", "accounts", "Set Account Alerts",
     "Configure alerts for account activity such as low balance or large transactions.",
     {"account_id": "string", "alerts": "array"}, {"account_id": "string", "alerts_configured": "boolean"},
     ["accounts:write"], "/v1/accounts/{account_id}/alerts"),

    # payments
    ("make_payment", "payments", "Make Payment",
     "Initiate a single payment to a payee.",
     {"amount": "number", "payee": "string", "from_account": "string", "currency": "string", "reference": "string"},
     {"payment_id": "string", "status": "string", "amount": "number", "payee": "string"},
     ["payments:write"], "/v1/payments"),
    ("schedule_payment", "payments", "Schedule Payment",
     "Schedule a recurring or future-dated payment.",
     {"amount": "number", "to_account": "string", "frequency": "string", "start_date": "date"},
     {"schedule_id": "string", "status": "string"},
     ["payments:write"], "/v1/payments/schedule"),
    ("cancel_payment", "payments", "Cancel Payment",
     "Cancel a pending or scheduled payment.",
     {"payment_id": "string"}, {"payment_id": "string", "status": "string"},
     ["payments:write"], "/v1/payments/{payment_id}/cancel"),
    ("transfer_funds", "payments", "Transfer Funds",
     "Transfer funds between two accounts owned by the customer.",
     {"amount": "number", "to_account": "string", "from_account": "string"},
     {"transfer_id": "string", "status": "string"},
     ["payments:write"], "/v1/transfers"),
    ("pay_bill", "payments", "Pay Bill",
     "Pay a bill to a registered biller.",
     {"biller_id": "string", "amount": "number", "from_account": "string"},
     {"payment_id": "string", "status": "string"},
     ["payments:write"], "/v1/bills/pay"),
    ("request_money", "payments", "Request Money",
     "Send a money request to another party.",
     {"amount": "number", "from_party": "string", "note": "string"},
     {"request_id": "string", "status": "string"},
     ["payments:write"], "/v1/payments/request"),
    ("split_bill", "payments", "Split Bill",
     "Split a bill or expense among multiple participants.",
     {"amount": "number", "participants": "array"},
     {"split_id": "string", "shares": "array"},
     ["payments:write"], "/v1/bills/split"),
    ("get_payment_status", "payments", "Get Payment Status",
     "Check the current status of a payment.",
     {"payment_id": "string"}, {"payment_id": "string", "status": "string", "updated_at": "datetime"},
     ["payments:read"], "/v1/payments/{payment_id}"),

    # statements / documents
    ("get_statement", "statements/documents", "Get Statement",
     "Retrieve a bank statement for an account over a period (YYYY-MM).",
     {"period": "string", "account_id": "string"},
     {"statement_id": "string", "file_url": "string", "format": "string", "transactions": "array", "transaction_count": "integer"},
     ["documents:read"], "/v1/statements"),
    ("download_tax_certificate", "statements/documents", "Download Tax Certificate",
     "Download a tax certificate for a financial year.",
     {"account_id": "string", "financial_year": "string"},
     {"certificate_id": "string", "file_url": "string"},
     ["documents:read"], "/v1/documents/tax-certificate"),
    ("request_cheque_book", "statements/documents", "Request Cheque Book",
     "Request a new cheque book for an account.",
     {"account_id": "string", "delivery_address": "string"},
     {"request_id": "string", "status": "string"},
     ["documents:write"], "/v1/cheque-book/request"),
    ("get_document_list", "statements/documents", "Get Document List",
     "List all documents available for an account.",
     {"account_id": "string"}, {"documents": "array"},
     ["documents:read"], "/v1/documents"),
    ("download_document", "statements/documents", "Download Document",
     "Download a specific document by id.",
     {"document_id": "string"}, {"file_url": "string", "format": "string"},
     ["documents:read"], "/v1/documents/{document_id}/download"),
    ("get_interest_certificate", "statements/documents", "Get Interest Certificate",
     "Download an interest certificate for tax filing.",
     {"account_id": "string", "financial_year": "string"},
     {"certificate_id": "string", "file_url": "string", "interest_earned": "number"},
     ["documents:read"], "/v1/documents/interest-certificate"),
    ("get_annual_summary", "statements/documents", "Get Annual Summary",
     "Retrieve an annual account summary report.",
     {"account_id": "string", "year": "integer"},
     {"summary_id": "string", "file_url": "string"},
     ["documents:read"], "/v1/statements/annual"),
    ("get_income_proof", "statements/documents", "Get Proof of Income",
     "Generate a proof-of-income document for the customer.",
     {"customer_id": "string", "year": "integer"},
     {"document_id": "string", "file_url": "string", "annual_income": "number", "employer": "string"},
     ["documents:read"], "/v1/documents/income-proof"),

    # cards
    ("freeze_card", "cards", "Freeze Card",
     "Temporarily freeze a card to prevent further transactions.",
     {"card_id": "string"}, {"card_id": "string", "status": "string"},
     ["cards:write"], "/v1/cards/{card_id}/freeze"),
    ("replace_card", "cards", "Replace Card",
     "Request a replacement card, optionally with a new number.",
     {"card_id": "string", "reason": "string", "new_number": "boolean"},
     {"request_id": "string", "status": "string"},
     ["cards:write"], "/v1/cards/{card_id}/replace"),
    ("change_pin", "cards", "Change PIN",
     "Change the PIN of a card.",
     {"card_id": "string", "new_pin": "string"}, {"card_id": "string", "status": "string"},
     ["cards:write"], "/v1/cards/{card_id}/pin"),
    ("get_card_details", "cards", "Get Card Details",
     "Fetch details of a card including limits and status.",
     {"card_id": "string"}, {"card_id": "string", "card_type": "string", "status": "string", "limits": "object"},
     ["cards:read"], "/v1/cards/{card_id}"),
    ("list_cards", "cards", "List Cards",
     "List all cards issued to the customer.",
     {"customer_id": "string"}, {"cards": "array"},
     ["cards:read"], "/v1/cards"),
    ("set_card_limits", "cards", "Set Card Limits",
     "Set transaction limits for a card.",
     {"card_id": "string", "limits": "object"}, {"card_id": "string", "limits": "object"},
     ["cards:write"], "/v1/cards/{card_id}/limits"),
    ("report_card_lost", "cards", "Report Card Lost",
     "Report a card as lost or stolen and block it.",
     {"card_id": "string"}, {"card_id": "string", "status": "string"},
     ["cards:write"], "/v1/cards/{card_id}/lost"),
    ("activate_card", "cards", "Activate Card",
     "Activate a newly issued card.",
     {"card_id": "string"}, {"card_id": "string", "status": "string"},
     ["cards:write"], "/v1/cards/{card_id}/activate"),

    # loans
    ("loan_status", "loans", "Get Loan Status",
     "Check the current status of a loan.",
     {"loan_id": "string"}, {"loan_id": "string", "status": "string", "outstanding": "number"},
     ["loans:read"], "/v1/loans/{loan_id}"),
    ("emi_schedule", "loans", "Get EMI Schedule",
     "Retrieve the EMI repayment schedule for a loan.",
     {"loan_id": "string"}, {"loan_id": "string", "schedule": "array"},
     ["loans:read"], "/v1/loans/{loan_id}/emi-schedule"),
    ("apply_for_loan", "loans", "Apply for Loan",
     "Submit a new loan application.",
     {"loan_type": "string", "amount": "number", "tenure_months": "integer"},
     {"application_id": "string", "status": "string"},
     ["loans:write"], "/v1/loans/apply"),
    ("get_loan_offers", "loans", "Get Loan Offers",
     "Fetch pre-approved loan offers for the customer.",
     {"customer_id": "string"}, {"offers": "array"},
     ["loans:read"], "/v1/loans/offers"),
    ("prepay_loan", "loans", "Prepay Loan",
     "Make a partial or full prepayment on a loan.",
     {"loan_id": "string", "amount": "number"},
     {"loan_id": "string", "status": "string", "outstanding": "number"},
     ["loans:write"], "/v1/loans/{loan_id}/prepay"),
    ("get_loan_balance", "loans", "Get Loan Balance",
     "Retrieve the outstanding balance of a loan.",
     {"loan_id": "string"}, {"loan_id": "string", "outstanding": "number", "currency": "string"},
     ["loans:read"], "/v1/loans/{loan_id}/balance"),

    # investments
    ("get_portfolio", "investments", "Get Portfolio",
     "Retrieve the customer's investment portfolio.",
     {"customer_id": "string"}, {"portfolio": "object", "holdings": "array"},
     ["investments:read"], "/v1/investments/portfolio"),
    ("get_market_rates", "investments", "Get Market Rates",
     "Fetch current market rates for investment products.",
     {"product_type": "string"}, {"rates": "array"},
     ["investments:read"], "/v1/investments/rates"),
    ("buy_investment", "investments", "Buy Investment",
     "Purchase an investment product.",
     {"product_id": "string", "amount": "number"}, {"order_id": "string", "status": "string"},
     ["investments:write"], "/v1/investments/buy"),
    ("sell_investment", "investments", "Sell Investment",
     "Sell an investment product.",
     {"holding_id": "string", "units": "number"}, {"order_id": "string", "status": "string"},
     ["investments:write"], "/v1/investments/sell"),
    ("get_investment_performance", "investments", "Get Investment Performance",
     "Retrieve performance metrics for an investment.",
     {"holding_id": "string"}, {"holding_id": "string", "returns": "object"},
     ["investments:read"], "/v1/investments/{holding_id}/performance"),
    ("get_fd_details", "investments", "Get Fixed Deposit Details",
     "Fetch details of a fixed deposit.",
     {"fd_id": "string"}, {"fd_id": "string", "principal": "number", "maturity_date": "date", "rate": "number"},
     ["investments:read"], "/v1/investments/fd/{fd_id}"),

    # insurance
    ("get_insurance_policies", "insurance", "Get Insurance Policies",
     "List all insurance policies held by the customer.",
     {"customer_id": "string"}, {"policies": "array"},
     ["insurance:read"], "/v1/insurance/policies"),
    ("get_policy_details", "insurance", "Get Policy Details",
     "Fetch details of a specific insurance policy.",
     {"policy_id": "string"}, {"policy_id": "string", "coverage": "object", "status": "string"},
     ["insurance:read"], "/v1/insurance/policies/{policy_id}"),
    ("file_insurance_claim", "insurance", "File Insurance Claim",
     "Submit a new insurance claim.",
     {"policy_id": "string", "claim_details": "object"}, {"claim_id": "string", "status": "string"},
     ["insurance:write"], "/v1/insurance/claims"),
    ("renew_policy", "insurance", "Renew Policy",
     "Renew an expiring insurance policy.",
     {"policy_id": "string"}, {"policy_id": "string", "status": "string", "new_expiry": "date"},
     ["insurance:write"], "/v1/insurance/policies/{policy_id}/renew"),
    ("get_insurance_cover", "insurance", "Get Insurance Cover",
     "Retrieve the coverage details of a policy.",
     {"policy_id": "string"}, {"policy_id": "string", "cover": "object"},
     ["insurance:read"], "/v1/insurance/policies/{policy_id}/cover"),

    # KYC / profile
    ("change_address", "KYC/profile", "Change Address",
     "Update the customer's registered address.",
     {"address": "object"}, {"status": "string", "updated_at": "datetime"},
     ["profile:write"], "/v1/profile/address"),
    ("update_contact_details", "KYC/profile", "Update Contact Details",
     "Update the customer's phone or email contact details.",
     {"phone": "string", "email": "string"}, {"status": "string", "updated_at": "datetime"},
     ["profile:write"], "/v1/profile/contact"),
    ("get_profile", "KYC/profile", "Get Profile",
     "Retrieve the customer's profile information.",
     {"customer_id": "string"}, {"profile": "object"},
     ["profile:read"], "/v1/profile"),
    ("upload_kyc_document", "KYC/profile", "Upload KYC Document",
     "Upload a KYC document for verification.",
     {"document_type": "string", "file_name": "string"}, {"document_id": "string", "status": "string"},
     ["profile:write"], "/v1/kyc/documents"),
    ("check_kyc_status", "KYC/profile", "Check KYC Status",
     "Check the status of the customer's KYC verification.",
     {"customer_id": "string"}, {"status": "string", "verified_at": "datetime"},
     ["profile:read"], "/v1/kyc/status"),
    ("update_nominee", "KYC/profile", "Update Nominee",
     "Add or update a nominee for an account.",
     {"account_id": "string", "nominee": "object"}, {"status": "string", "updated_at": "datetime"},
     ["profile:write"], "/v1/profile/nominee"),

    # support
    ("create_support_ticket", "support", "Create Support Ticket",
     "Create a new customer support ticket.",
     {"subject": "string", "description": "string", "category": "string"},
     {"ticket_id": "string", "status": "string"},
     ["support:write"], "/v1/support/tickets"),
    ("get_support_ticket_status", "support", "Get Support Ticket Status",
     "Check the status of a support ticket.",
     {"ticket_id": "string"}, {"ticket_id": "string", "status": "string", "updated_at": "datetime"},
     ["support:read"], "/v1/support/tickets/{ticket_id}"),
    ("chat_with_agent", "support", "Chat with Agent",
     "Start a chat session with a support agent.",
     {"topic": "string"}, {"session_id": "string", "status": "string"},
     ["support:write"], "/v1/support/chat"),
    ("get_faq", "support", "Get FAQ",
     "Retrieve frequently asked questions and answers.",
     {"query": "string"}, {"faqs": "array"},
     ["support:read"], "/v1/support/faq"),
    ("schedule_call_back", "support", "Schedule Call Back",
     "Schedule a call back from a support agent.",
     {"preferred_time": "datetime", "topic": "string"}, {"request_id": "string", "status": "string"},
     ["support:write"], "/v1/support/callback"),

    # offers
    ("get_offers", "offers", "Get Offers",
     "List available offers and promotions for the customer.",
     {"customer_id": "string"}, {"offers": "array"},
     ["offers:read"], "/v1/offers"),
    ("get_offer_details", "offers", "Get Offer Details",
     "Fetch details of a specific offer.",
     {"offer_id": "string"}, {"offer_id": "string", "terms": "object", "valid_until": "date"},
     ["offers:read"], "/v1/offers/{offer_id}"),
    ("redeem_offer", "offers", "Redeem Offer",
     "Redeem an offer or coupon.",
     {"offer_id": "string", "account_id": "string"}, {"redemption_id": "string", "status": "string"},
     ["offers:write"], "/v1/offers/{offer_id}/redeem"),
    ("get_rewards", "offers", "Get Rewards",
     "Retrieve the customer's rewards points balance and history.",
     {"customer_id": "string"}, {"points": "number", "history": "array"},
     ["offers:read"], "/v1/rewards"),
    ("get_cashback", "offers", "Get Cashback",
     "Retrieve cashback earned and available for redemption.",
     {"customer_id": "string"}, {"cashback": "number", "available": "number"},
     ["offers:read"], "/v1/cashback"),
]


def build_manifest() -> List[Capability]:
    """Build a :class:`Capability` for every bank function in the manifest.

    Returns:
        A list of Capability objects, one per implemented bank function.
    """
    caps: List[Capability] = []
    for (func_name, domain, name, description, inputs, outputs, permissions, endpoint) in _MANIFEST:
        # Verify the function actually exists in the bank module.
        if not hasattr(bank, func_name) or not callable(getattr(bank, func_name)):
            raise AttributeError(f"bank module has no callable '{func_name}'")
        caps.append(
            Capability(
                id=func_name,
                name=name,
                description=description,
                domain=domain,
                inputs=inputs,
                outputs=outputs,
                permissions=permissions,
                provider="demo-bank",
                protocol="rest",
                endpoint=endpoint,
                estimated_latency=60,
                estimated_cost=0.002,
                historical_success=0.98,
                metadata={"tags": [domain, func_name], "version": "1.0", "source": "demo-bank"},
            )
        )
    return caps


def build_registry() -> Any:
    """Build a :class:`~registry.CapabilityRegistry` populated with the manifest."""
    from registry import CapabilityRegistry

    reg = CapabilityRegistry()
    for cap in build_manifest():
        reg.register(cap)
    return reg


def main() -> None:
    """Print a summary of the manifest."""
    caps = build_manifest()
    domains: Dict[str, int] = {}
    for c in caps:
        domains[c.domain] = domains.get(c.domain, 0) + 1
    print(f"Manifest: {len(caps)} capabilities across {len(domains)} domains")
    for d in sorted(domains):
        print(f"  {d}: {domains[d]}")


if __name__ == "__main__":
    main()
