"""Demo MCP tools for the Elastic Web MCP adapter.

This module provides a small set of demo-bank tools implemented as plain
Python callables with JSON-schema input/output definitions. They stand in
for tools that would normally be served by a real MCP server, so the
:class:`~mcp_adapter.MCPAdapter` has concrete tools to discover, normalize,
and invoke without any network or external dependency.

Each tool is a :class:`MCPTool` with:

    name          -- unique tool identifier (maps to Capability.id)
    description   -- plain-language description (maps to Capability.description)
    input_schema  -- JSON Schema describing accepted arguments
    output_schema -- JSON Schema describing the returned result
    callable      -- the plain Python function that executes the tool

The ``DEMO_TOOL_REGISTRY`` list is the local "tool registry" the adapter
discovers from. It mirrors the shape of the MCP SDK's ``Tool`` type
(name/description/inputSchema) so swapping in the real SDK is a thin change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class MCPTool:
    """A minimal MCP-like tool descriptor.

    Mirrors the MCP SDK ``Tool`` shape (name, description, inputSchema)
    plus an ``output_schema`` and the executable ``callable``.
    """

    name: str
    description: str
    input_schema: Dict[str, Any]
    callable: Callable[..., Any]
    output_schema: Optional[Dict[str, Any]] = None
    annotations: Dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# Demo tool implementations (plain Python callables)
# ----------------------------------------------------------------------

def _get_statement(account_id: str, from_date: str, to_date: str, format: str = "pdf") -> Dict[str, Any]:
    """Retrieve a bank statement for an account over a period."""
    return {
        "statement_id": f"stmt-{account_id}-{from_date}-{to_date}",
        "account_id": account_id,
        "file_url": f"https://demo-bank.example/statements/{account_id}/{from_date}_{to_date}.{format}",
        "format": format,
        "period": {"from": from_date, "to": to_date},
    }


def _make_payment(from_account: str, to_account: str, amount: float, currency: str = "USD", reference: str = "") -> Dict[str, Any]:
    """Initiate a single payment to a payee or account."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    return {
        "payment_id": f"pay-{from_account}-{to_account}-{amount}",
        "status": "pending",
        "amount": amount,
        "currency": currency,
        "reference": reference,
    }


def _get_balance(account_id: str) -> Dict[str, Any]:
    """Retrieve the current available and ledger balance for an account."""
    return {
        "account_id": account_id,
        "available_balance": 1250.75,
        "ledger_balance": 1300.00,
        "currency": "USD",
    }


def _freeze_card(card_id: str, reason: str = "user_request") -> Dict[str, Any]:
    """Temporarily freeze a card to prevent further transactions."""
    return {
        "card_id": card_id,
        "status": "frozen",
        "reason": reason,
        "frozen_at": "2026-09-10T12:00:00Z",
    }


# ----------------------------------------------------------------------
# Tool registry
# ----------------------------------------------------------------------

DEMO_TOOL_REGISTRY: List[MCPTool] = [
    MCPTool(
        name="get_statement",
        description="Retrieve a bank statement for an account over a period.",
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account identifier."},
                "from_date": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
                "to_date": {"type": "string", "description": "End date (YYYY-MM-DD)."},
                "format": {"type": "string", "enum": ["pdf", "csv"], "default": "pdf"},
            },
            "required": ["account_id", "from_date", "to_date"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "statement_id": {"type": "string"},
                "file_url": {"type": "string"},
                "format": {"type": "string"},
            },
        },
        callable=_get_statement,
    ),
    MCPTool(
        name="make_payment",
        description="Initiate a single payment to a payee or account.",
        input_schema={
            "type": "object",
            "properties": {
                "from_account": {"type": "string", "description": "Source account."},
                "to_account": {"type": "string", "description": "Destination account."},
                "amount": {"type": "number", "description": "Amount to pay."},
                "currency": {"type": "string", "default": "USD"},
                "reference": {"type": "string", "default": ""},
            },
            "required": ["from_account", "to_account", "amount"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "payment_id": {"type": "string"},
                "status": {"type": "string"},
                "amount": {"type": "number"},
            },
        },
        callable=_make_payment,
    ),
    MCPTool(
        name="get_balance",
        description="Retrieve the current available and ledger balance for an account.",
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Account identifier."},
            },
            "required": ["account_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "available_balance": {"type": "number"},
                "ledger_balance": {"type": "number"},
                "currency": {"type": "string"},
            },
        },
        callable=_get_balance,
    ),
    MCPTool(
        name="freeze_card",
        description="Temporarily freeze a card to prevent further transactions.",
        input_schema={
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "Card identifier."},
                "reason": {"type": "string", "default": "user_request"},
            },
            "required": ["card_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "card_id": {"type": "string"},
                "status": {"type": "string"},
            },
        },
        callable=_freeze_card,
    ),
]


def get_demo_tools() -> List[MCPTool]:
    """Return the demo tool registry (a fresh list each call)."""
    return list(DEMO_TOOL_REGISTRY)
