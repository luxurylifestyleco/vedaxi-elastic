"""Combine prospect, research, and directory results into an unsent plan.

This does not send email, post a message, or call an external network.
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_outreach_report(
    prospects: Dict[str, Any],
    research: Dict[str, Any],
    profiles: Dict[str, Any],
) -> Dict[str, Any]:
    people = list(prospects.get("prospects") or [])
    by_company = {row.get("company"): row for row in (research.get("research") or [])}
    plan: List[Dict[str, Any]] = []
    holds: List[Dict[str, Any]] = []
    for person in people:
        company = person.get("company")
        found = by_company.get(company) or {}
        industry = found.get("industry") or "their work"
        plan.append({
            "prospect": person.get("name"),
            "company": company,
            "draft": f"Draft for {person.get('name')} at {company}: reference {industry}.",
            "sent": False,
        })
        if person.get("needs_human_approval") or found.get("public") is False:
            holds.append({
                "prospect": person.get("name"),
                "company": company,
                "reason": person.get("approval_reason") or found.get("note") or "insufficient public research",
            })
    return {
        "outreach_plan": plan,
        "needs_human_approval": holds,
        "contact_sent": False,
        "profiles_checked": [row.get("company") for row in (profiles.get("profiles") or [])],
    }


def refuse_send(_args: Dict[str, Any]) -> None:
    """Last-line refusal. Authorization must already have blocked this."""
    raise RuntimeError("refusing to contact prospects")
