"""Comprehensive recipe definitions covering all 64 capabilities in Demo Bank.

Covers all 10 banking domains:
  1. Accounts (7 capabilities)
  2. Payments (8 capabilities)
  3. Statements/Documents (8 capabilities)
  4. Cards (8 capabilities)
  5. Loans (6 capabilities)
  6. Investments (6 capabilities)
  7. Insurance (5 capabilities)
  8. KYC/Profile (6 capabilities)
  9. Support (5 capabilities)
  10. Offers (5 capabilities)

Total: 64 hand-written recipes, each validating against demo-bank capability IDs
and arguments.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

_PACKAGES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PACKAGES_DIR not in sys.path:
    sys.path.insert(0, _PACKAGES_DIR)

_RECIPE_SCHEMA_DIR = os.path.join(_PACKAGES_DIR, "recipe-schema")
if _RECIPE_SCHEMA_DIR not in sys.path:
    sys.path.insert(0, _RECIPE_SCHEMA_DIR)

from recipe import Recipe, RecipeStatus, RecipeStep  # noqa: E402

_PROVENANCE = {
    "author": "elastic-bench",
    "control": "C",
    "created": "2026-09-15",
    "source": "hand-written",
    "version": "1.0.0",
}

_METRIC_FIELDS = [
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "llm_calls",
    "tool_calls",
    "retrieval_calls",
    "steps",
    "wall_clock_latency_ms",
    "success",
    "estimated_model_cost",
]


def _make_recipe(
    recipe_id: str,
    intent_family: str,
    steps: List[RecipeStep],
    domain: str,
    description: str,
    invariants: List[str] | None = None,
    success_conditions: List[str] | None = None,
) -> Recipe:
    return Recipe(
        recipe_id=recipe_id,
        intent_family=intent_family,
        version="1.0.0",
        applicability_conditions=[
            "user is authenticated",
            f"user intends to perform {description}",
        ],
        invariants=invariants or ["action must be logged in telemetry"],
        steps=steps,
        skills=[domain, intent_family],
        adaptation_points=["args", "context"],
        checkpoints=[f"{intent_family} completed"],
        success_conditions=success_conditions or ["step returned ok=True"],
        fallbacks=[{"on": "error", "action": "abort_and_log"}],
        freshness_policy={"max_age_seconds": 3600},
        metrics=_METRIC_FIELDS,
        status=RecipeStatus.ACTIVE,
        provenance=_PROVENANCE,
    )


def build_all_recipes() -> List[Recipe]:
    """Build and return all 64 recipes covering the demo-bank capabilities."""
    recipes: List[Recipe] = []

    # =========================================================================
    # 1. ACCOUNTS (7 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="account.balance",
            intent_family="get_balance",
            domain="accounts",
            description="get account balance",
            steps=[
                RecipeStep(
                    step_id="get_balance",
                    action="retrieve",
                    capability_id="get_balance",
                    args={"account_id": "ACC-1001"},
                    checkpoints=["balance returned"],
                )
            ],
            invariants=["read-only operation"],
            success_conditions=["available_balance is present"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="account.details",
            intent_family="get_account_details",
            domain="accounts",
            description="fetch account details",
            steps=[
                RecipeStep(
                    step_id="get_account_details",
                    action="retrieve",
                    capability_id="get_account_details",
                    args={"account_id": "ACC-1001"},
                    checkpoints=["details returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="account.list",
            intent_family="list_accounts",
            domain="accounts",
            description="list customer accounts",
            steps=[
                RecipeStep(
                    step_id="list_accounts",
                    action="retrieve",
                    capability_id="list_accounts",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["accounts listed"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="account.transactions",
            intent_family="get_transactions",
            domain="accounts",
            description="retrieve transactions",
            steps=[
                RecipeStep(
                    step_id="get_transactions",
                    action="retrieve",
                    capability_id="get_transactions",
                    args={
                        "account_id": "ACC-1001",
                        "from_date": "2026-01-01",
                        "to_date": "2026-12-31",
                        "page": 1,
                    },
                    checkpoints=["transactions listed"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="account.export_transactions",
            intent_family="export_transactions",
            domain="accounts",
            description="export account transactions to CSV",
            steps=[
                RecipeStep(
                    step_id="export_transactions",
                    action="export",
                    capability_id="export_transactions",
                    args={"months": 6, "account_id": "ACC-1001"},
                    checkpoints=["export generated"],
                )
            ],
            success_conditions=["file_url is present"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="account.summary",
            intent_family="get_account_summary",
            domain="accounts",
            description="get account activity summary",
            steps=[
                RecipeStep(
                    step_id="get_account_summary",
                    action="retrieve",
                    capability_id="get_account_summary",
                    args={"account_id": "ACC-1001"},
                    checkpoints=["summary returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="account.alerts",
            intent_family="set_account_alerts",
            domain="accounts",
            description="configure account activity alerts",
            steps=[
                RecipeStep(
                    step_id="set_account_alerts",
                    action="update",
                    capability_id="set_account_alerts",
                    args={
                        "account_id": "ACC-1001",
                        "alerts": ["low_balance", "large_transaction"],
                    },
                    checkpoints=["alerts saved"],
                )
            ],
        )
    )

    # =========================================================================
    # 2. PAYMENTS (8 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="payment.execute",
            intent_family="make_payment",
            domain="payments",
            description="check balance and execute single payment",
            steps=[
                RecipeStep(
                    step_id="get_balance",
                    action="check_balance",
                    capability_id="get_balance",
                    args={"account_id": "ACC-1001"},
                    checkpoints=["balance checked"],
                ),
                RecipeStep(
                    step_id="make_payment",
                    action="pay",
                    capability_id="make_payment",
                    args={
                        "amount": 142.75,
                        "payee": "electricity",
                        "from_account": "ACC-1001",
                        "currency": "USD",
                        "reference": "ref-001",
                    },
                    depends_on=["get_balance"],
                    checkpoints=["payment completed"],
                ),
            ],
            invariants=["balance verified before payment", "amount must be positive"],
            success_conditions=["payment status completed"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.schedule",
            intent_family="schedule_payment",
            domain="payments",
            description="schedule a recurring or future-dated payment",
            steps=[
                RecipeStep(
                    step_id="schedule_payment",
                    action="schedule",
                    capability_id="schedule_payment",
                    args={
                        "amount": 100.0,
                        "to_account": "ACC-1002",
                        "frequency": "monthly",
                        "start_date": "2026-10-01",
                        "from_account": "ACC-1001",
                    },
                    checkpoints=["payment scheduled"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.cancel",
            intent_family="cancel_payment",
            domain="payments",
            description="cancel a pending or scheduled payment",
            steps=[
                RecipeStep(
                    step_id="cancel_payment",
                    action="cancel",
                    capability_id="cancel_payment",
                    args={"payment_id": "PAY-1"},
                    checkpoints=["payment cancelled"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.transfer",
            intent_family="transfer_funds",
            domain="payments",
            description="transfer funds between customer accounts",
            steps=[
                RecipeStep(
                    step_id="get_balance",
                    action="check_balance",
                    capability_id="get_balance",
                    args={"account_id": "ACC-1001"},
                    checkpoints=["balance checked"],
                ),
                RecipeStep(
                    step_id="transfer_funds",
                    action="transfer",
                    capability_id="transfer_funds",
                    args={
                        "amount": 100.0,
                        "to_account": "ACC-1002",
                        "from_account": "ACC-1001",
                    },
                    depends_on=["get_balance"],
                    checkpoints=["funds transferred"],
                ),
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.pay_bill",
            intent_family="pay_bill",
            domain="payments",
            description="pay a registered biller",
            steps=[
                RecipeStep(
                    step_id="pay_bill",
                    action="pay",
                    capability_id="pay_bill",
                    args={
                        "biller_id": "BILL-1",
                        "amount": 75.50,
                        "from_account": "ACC-1001",
                    },
                    checkpoints=["bill paid"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.request_money",
            intent_family="request_money",
            domain="payments",
            description="send a money request",
            steps=[
                RecipeStep(
                    step_id="request_money",
                    action="request",
                    capability_id="request_money",
                    args={
                        "amount": 50.0,
                        "from_party": "alice@example.com",
                        "note": "please pay",
                    },
                    checkpoints=["request sent"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.split_bill",
            intent_family="split_bill",
            domain="payments",
            description="split a bill among participants",
            steps=[
                RecipeStep(
                    step_id="split_bill",
                    action="split",
                    capability_id="split_bill",
                    args={
                        "amount": 90.0,
                        "participants": ["alice@example.com", "bob@example.com"],
                    },
                    checkpoints=["split calculated"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="payment.status",
            intent_family="get_payment_status",
            domain="payments",
            description="check payment status",
            steps=[
                RecipeStep(
                    step_id="get_payment_status",
                    action="retrieve",
                    capability_id="get_payment_status",
                    args={"payment_id": "PAY-1"},
                    checkpoints=["status returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    # =========================================================================
    # 3. STATEMENTS / DOCUMENTS (8 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="statement.retrieve",
            intent_family="retrieve_statement",
            domain="statements/documents",
            description="retrieve monthly account statement",
            steps=[
                RecipeStep(
                    step_id="get_statement",
                    action="retrieve",
                    capability_id="get_statement",
                    args={"period": "2026-08", "account_id": "ACC-1001"},
                    checkpoints=["statement file url returned"],
                )
            ],
            invariants=["read-only operation"],
            success_conditions=["statement file_url present"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.tax_certificate",
            intent_family="download_tax_certificate",
            domain="statements/documents",
            description="download annual tax certificate",
            steps=[
                RecipeStep(
                    step_id="download_tax_certificate",
                    action="download",
                    capability_id="download_tax_certificate",
                    args={
                        "account_id": "ACC-1001",
                        "financial_year": "2025-26",
                    },
                    checkpoints=["certificate ready"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.cheque_book",
            intent_family="request_cheque_book",
            domain="statements/documents",
            description="order a new cheque book",
            steps=[
                RecipeStep(
                    step_id="request_cheque_book",
                    action="request",
                    capability_id="request_cheque_book",
                    args={
                        "account_id": "ACC-1001",
                        "delivery_address": "1 Main Street, Springfield",
                    },
                    checkpoints=["cheque book requested"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.list",
            intent_family="get_document_list",
            domain="statements/documents",
            description="list available documents",
            steps=[
                RecipeStep(
                    step_id="get_document_list",
                    action="retrieve",
                    capability_id="get_document_list",
                    args={"account_id": "ACC-1001"},
                    checkpoints=["document list returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.download",
            intent_family="download_document",
            domain="statements/documents",
            description="download specific document by ID",
            steps=[
                RecipeStep(
                    step_id="download_document",
                    action="download",
                    capability_id="download_document",
                    args={"document_id": "DOC-0001"},
                    checkpoints=["document download url ready"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.interest_certificate",
            intent_family="get_interest_certificate",
            domain="statements/documents",
            description="retrieve interest certificate",
            steps=[
                RecipeStep(
                    step_id="get_interest_certificate",
                    action="retrieve",
                    capability_id="get_interest_certificate",
                    args={
                        "account_id": "ACC-1001",
                        "financial_year": "2025-26",
                    },
                    checkpoints=["interest certificate generated"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.annual_summary",
            intent_family="get_annual_summary",
            domain="statements/documents",
            description="generate annual account summary report",
            steps=[
                RecipeStep(
                    step_id="get_annual_summary",
                    action="retrieve",
                    capability_id="get_annual_summary",
                    args={"account_id": "ACC-1001", "year": 2025},
                    checkpoints=["annual summary ready"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="document.income_proof",
            intent_family="get_income_proof",
            domain="statements/documents",
            description="generate customer proof of income",
            steps=[
                RecipeStep(
                    step_id="get_income_proof",
                    action="retrieve",
                    capability_id="get_income_proof",
                    args={"customer_id": "CUST-0001", "year": 2026},
                    checkpoints=["income proof generated"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    # =========================================================================
    # 4. CARDS (8 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="card.freeze",
            intent_family="freeze_card",
            domain="cards",
            description="temporarily freeze a card",
            steps=[
                RecipeStep(
                    step_id="freeze_card",
                    action="freeze",
                    capability_id="freeze_card",
                    args={"card_id": "CARD-9001"},
                    checkpoints=["card frozen"],
                )
            ],
            success_conditions=["card status is frozen"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.replace",
            intent_family="replace_card",
            domain="cards",
            description="order replacement card",
            steps=[
                RecipeStep(
                    step_id="replace_card",
                    action="replace",
                    capability_id="replace_card",
                    args={
                        "card_id": "CARD-9001",
                        "reason": "damaged",
                        "new_number": True,
                    },
                    checkpoints=["replacement submitted"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.change_pin",
            intent_family="change_pin",
            domain="cards",
            description="change card PIN",
            steps=[
                RecipeStep(
                    step_id="change_pin",
                    action="update_pin",
                    capability_id="change_pin",
                    args={"card_id": "CARD-9001", "new_pin": "1234"},
                    checkpoints=["pin updated"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.details",
            intent_family="get_card_details",
            domain="cards",
            description="fetch card details and limits",
            steps=[
                RecipeStep(
                    step_id="get_card_details",
                    action="retrieve",
                    capability_id="get_card_details",
                    args={"card_id": "CARD-9001"},
                    checkpoints=["card details returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.list",
            intent_family="list_cards",
            domain="cards",
            description="list customer cards",
            steps=[
                RecipeStep(
                    step_id="list_cards",
                    action="retrieve",
                    capability_id="list_cards",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["cards listed"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.set_limits",
            intent_family="set_card_limits",
            domain="cards",
            description="configure card transaction limits",
            steps=[
                RecipeStep(
                    step_id="set_card_limits",
                    action="update_limits",
                    capability_id="set_card_limits",
                    args={
                        "card_id": "CARD-9001",
                        "limits": {"daily_limit": 1500.0, "monthly_limit": 8000.0},
                    },
                    checkpoints=["limits saved"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.report_lost",
            intent_family="report_card_lost",
            domain="cards",
            description="report lost card and block immediately",
            steps=[
                RecipeStep(
                    step_id="report_card_lost",
                    action="block",
                    capability_id="report_card_lost",
                    args={"card_id": "CARD-9001"},
                    checkpoints=["card blocked"],
                )
            ],
            success_conditions=["card status is blocked"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="card.activate",
            intent_family="activate_card",
            domain="cards",
            description="activate newly issued card",
            steps=[
                RecipeStep(
                    step_id="activate_card",
                    action="activate",
                    capability_id="activate_card",
                    args={"card_id": "CARD-9001"},
                    checkpoints=["card active"],
                )
            ],
        )
    )

    # =========================================================================
    # 5. LOANS (6 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="loan.status",
            intent_family="loan_status",
            domain="loans",
            description="check loan status and balance",
            steps=[
                RecipeStep(
                    step_id="loan_status",
                    action="retrieve",
                    capability_id="loan_status",
                    args={"loan_id": "LOAN-5001"},
                    checkpoints=["loan status returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="loan.emi_schedule",
            intent_family="emi_schedule",
            domain="loans",
            description="retrieve EMI repayment schedule",
            steps=[
                RecipeStep(
                    step_id="emi_schedule",
                    action="retrieve",
                    capability_id="emi_schedule",
                    args={"loan_id": "LOAN-5001"},
                    checkpoints=["schedule returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="loan.apply",
            intent_family="apply_for_loan",
            domain="loans",
            description="apply for a new loan",
            steps=[
                RecipeStep(
                    step_id="apply_for_loan",
                    action="apply",
                    capability_id="apply_for_loan",
                    args={
                        "loan_type": "personal",
                        "amount": 10000.0,
                        "tenure_months": 24,
                    },
                    checkpoints=["application submitted"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="loan.offers",
            intent_family="get_loan_offers",
            domain="loans",
            description="retrieve pre-approved loan offers",
            steps=[
                RecipeStep(
                    step_id="get_loan_offers",
                    action="retrieve",
                    capability_id="get_loan_offers",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["offers listed"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="loan.prepay",
            intent_family="prepay_loan",
            domain="loans",
            description="prepay loan installment",
            steps=[
                RecipeStep(
                    step_id="prepay_loan",
                    action="prepay",
                    capability_id="prepay_loan",
                    args={"loan_id": "LOAN-5001", "amount": 1000.0},
                    checkpoints=["prepayment processed"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="loan.balance",
            intent_family="get_loan_balance",
            domain="loans",
            description="check outstanding loan balance",
            steps=[
                RecipeStep(
                    step_id="get_loan_balance",
                    action="retrieve",
                    capability_id="get_loan_balance",
                    args={"loan_id": "LOAN-5001"},
                    checkpoints=["loan balance returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    # =========================================================================
    # 6. INVESTMENTS (6 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="investment.portfolio",
            intent_family="get_portfolio",
            domain="investments",
            description="retrieve investment portfolio",
            steps=[
                RecipeStep(
                    step_id="get_portfolio",
                    action="retrieve",
                    capability_id="get_portfolio",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["portfolio returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="investment.market_rates",
            intent_family="get_market_rates",
            domain="investments",
            description="fetch current investment market rates",
            steps=[
                RecipeStep(
                    step_id="get_market_rates",
                    action="retrieve",
                    capability_id="get_market_rates",
                    args={"product_type": "mutual_fund"},
                    checkpoints=["rates fetched"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="investment.buy",
            intent_family="buy_investment",
            domain="investments",
            description="purchase an investment product",
            steps=[
                RecipeStep(
                    step_id="buy_investment",
                    action="buy",
                    capability_id="buy_investment",
                    args={"product_id": "PROD-1", "amount": 500.0},
                    checkpoints=["order placed"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="investment.sell",
            intent_family="sell_investment",
            domain="investments",
            description="sell units of an investment holding",
            steps=[
                RecipeStep(
                    step_id="sell_investment",
                    action="sell",
                    capability_id="sell_investment",
                    args={"holding_id": "H-1", "units": 10.0},
                    checkpoints=["order executed"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="investment.performance",
            intent_family="get_investment_performance",
            domain="investments",
            description="check holding performance metrics",
            steps=[
                RecipeStep(
                    step_id="get_investment_performance",
                    action="retrieve",
                    capability_id="get_investment_performance",
                    args={"holding_id": "H-1"},
                    checkpoints=["performance returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="investment.fd_details",
            intent_family="get_fd_details",
            domain="investments",
            description="view fixed deposit details",
            steps=[
                RecipeStep(
                    step_id="get_fd_details",
                    action="retrieve",
                    capability_id="get_fd_details",
                    args={"fd_id": "FD-3001"},
                    checkpoints=["fd details returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    # =========================================================================
    # 7. INSURANCE (5 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="insurance.policies",
            intent_family="get_insurance_policies",
            domain="insurance",
            description="list customer insurance policies",
            steps=[
                RecipeStep(
                    step_id="get_insurance_policies",
                    action="retrieve",
                    capability_id="get_insurance_policies",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["policies listed"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="insurance.policy_details",
            intent_family="get_policy_details",
            domain="insurance",
            description="retrieve specific policy details",
            steps=[
                RecipeStep(
                    step_id="get_policy_details",
                    action="retrieve",
                    capability_id="get_policy_details",
                    args={"policy_id": "POL-1"},
                    checkpoints=["policy details returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="insurance.claim",
            intent_family="file_insurance_claim",
            domain="insurance",
            description="file an insurance claim",
            steps=[
                RecipeStep(
                    step_id="file_insurance_claim",
                    action="submit_claim",
                    capability_id="file_insurance_claim",
                    args={
                        "policy_id": "POL-1",
                        "claim_details": {"reason": "hospitalization"},
                    },
                    checkpoints=["claim submitted"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="insurance.renew",
            intent_family="renew_policy",
            domain="insurance",
            description="renew an insurance policy",
            steps=[
                RecipeStep(
                    step_id="renew_policy",
                    action="renew",
                    capability_id="renew_policy",
                    args={"policy_id": "POL-1"},
                    checkpoints=["policy renewed"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="insurance.cover",
            intent_family="get_insurance_cover",
            domain="insurance",
            description="check insurance coverage terms",
            steps=[
                RecipeStep(
                    step_id="get_insurance_cover",
                    action="retrieve",
                    capability_id="get_insurance_cover",
                    args={"policy_id": "POL-1"},
                    checkpoints=["cover details returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    # =========================================================================
    # 8. KYC / PROFILE (6 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="kyc.change_address",
            intent_family="change_address",
            domain="KYC/profile",
            description="update residential address",
            steps=[
                RecipeStep(
                    step_id="change_address",
                    action="update",
                    capability_id="change_address",
                    args={
                        "address": {
                            "line1": "2 Oak Avenue",
                            "city": "Springfield",
                            "postcode": "12345",
                        }
                    },
                    checkpoints=["address updated"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="kyc.update_contact",
            intent_family="update_contact_details",
            domain="KYC/profile",
            description="update phone and email details",
            steps=[
                RecipeStep(
                    step_id="update_contact_details",
                    action="update",
                    capability_id="update_contact_details",
                    args={
                        "phone": "+1-555-0100",
                        "email": "customer@example.com",
                    },
                    checkpoints=["contact details updated"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="kyc.get_profile",
            intent_family="get_profile",
            domain="KYC/profile",
            description="retrieve customer profile information",
            steps=[
                RecipeStep(
                    step_id="get_profile",
                    action="retrieve",
                    capability_id="get_profile",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["profile returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="kyc.upload_document",
            intent_family="upload_kyc_document",
            domain="KYC/profile",
            description="upload identity or address document for KYC",
            steps=[
                RecipeStep(
                    step_id="upload_kyc_document",
                    action="upload",
                    capability_id="upload_kyc_document",
                    args={
                        "document_type": "passport",
                        "file_name": "passport.pdf",
                    },
                    checkpoints=["document uploaded"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="kyc.check_status",
            intent_family="check_kyc_status",
            domain="KYC/profile",
            description="check KYC verification status",
            steps=[
                RecipeStep(
                    step_id="check_kyc_status",
                    action="retrieve",
                    capability_id="check_kyc_status",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["status returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="kyc.update_nominee",
            intent_family="update_nominee",
            domain="KYC/profile",
            description="set or change account nominee",
            steps=[
                RecipeStep(
                    step_id="update_nominee",
                    action="update",
                    capability_id="update_nominee",
                    args={
                        "account_id": "ACC-1001",
                        "nominee": {"name": "Alex Smith", "relation": "spouse"},
                    },
                    checkpoints=["nominee updated"],
                )
            ],
        )
    )

    # =========================================================================
    # 9. SUPPORT (5 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="support.create_ticket",
            intent_family="create_support_ticket",
            domain="support",
            description="open a support ticket",
            steps=[
                RecipeStep(
                    step_id="create_support_ticket",
                    action="create",
                    capability_id="create_support_ticket",
                    args={
                        "subject": "Card not working",
                        "description": "My card was declined at a store.",
                        "category": "cards",
                    },
                    checkpoints=["ticket opened"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="support.ticket_status",
            intent_family="get_support_ticket_status",
            domain="support",
            description="check support ticket status",
            steps=[
                RecipeStep(
                    step_id="get_support_ticket_status",
                    action="retrieve",
                    capability_id="get_support_ticket_status",
                    args={"ticket_id": "TKT-1"},
                    checkpoints=["ticket status returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="support.chat",
            intent_family="chat_with_agent",
            domain="support",
            description="initiate chat with a support agent",
            steps=[
                RecipeStep(
                    step_id="chat_with_agent",
                    action="connect",
                    capability_id="chat_with_agent",
                    args={"topic": "general"},
                    checkpoints=["session connected"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="support.faq",
            intent_family="get_faq",
            domain="support",
            description="search frequently asked questions",
            steps=[
                RecipeStep(
                    step_id="get_faq",
                    action="retrieve",
                    capability_id="get_faq",
                    args={"query": "how do I freeze my card"},
                    checkpoints=["faqs retrieved"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="support.call_back",
            intent_family="schedule_call_back",
            domain="support",
            description="request a callback from customer support",
            steps=[
                RecipeStep(
                    step_id="schedule_call_back",
                    action="schedule",
                    capability_id="schedule_call_back",
                    args={
                        "preferred_time": "2026-09-11T10:00:00Z",
                        "topic": "general",
                    },
                    checkpoints=["callback booked"],
                )
            ],
        )
    )

    # =========================================================================
    # 10. OFFERS (5 capabilities)
    # =========================================================================
    recipes.append(
        _make_recipe(
            recipe_id="offers.list",
            intent_family="get_offers",
            domain="offers",
            description="list available customer offers and promotions",
            steps=[
                RecipeStep(
                    step_id="get_offers",
                    action="retrieve",
                    capability_id="get_offers",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["offers listed"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="offers.details",
            intent_family="get_offer_details",
            domain="offers",
            description="retrieve specific offer terms and conditions",
            steps=[
                RecipeStep(
                    step_id="get_offer_details",
                    action="retrieve",
                    capability_id="get_offer_details",
                    args={"offer_id": "OFF-1"},
                    checkpoints=["offer details returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="offers.redeem",
            intent_family="redeem_offer",
            domain="offers",
            description="redeem an offer against an account",
            steps=[
                RecipeStep(
                    step_id="redeem_offer",
                    action="redeem",
                    capability_id="redeem_offer",
                    args={"offer_id": "OFF-1", "account_id": "ACC-1001"},
                    checkpoints=["redemption confirmed"],
                )
            ],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="offers.rewards",
            intent_family="get_rewards",
            domain="offers",
            description="check rewards points balance and history",
            steps=[
                RecipeStep(
                    step_id="get_rewards",
                    action="retrieve",
                    capability_id="get_rewards",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["points returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    recipes.append(
        _make_recipe(
            recipe_id="offers.cashback",
            intent_family="get_cashback",
            domain="offers",
            description="check earned cashback",
            steps=[
                RecipeStep(
                    step_id="get_cashback",
                    action="retrieve",
                    capability_id="get_cashback",
                    args={"customer_id": "CUST-0001"},
                    checkpoints=["cashback returned"],
                )
            ],
            invariants=["read-only operation"],
        )
    )

    return recipes
