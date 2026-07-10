"""Tool definitions the agent can call.

Every tool is backed by the mock CRM (``app/data/crm.json``, loaded into an
in-memory store) and, where a refund decision is involved, by the
deterministic engine in ``app/policy.py``. The LLM never approves or denies
a refund from memory alone: ``process_refund`` re-validates eligibility
itself before mutating any state, so a hallucinated approval can't actually
execute.

State is mutated in memory only and not persisted back to ``crm.json`` —
there's no real database in this vertical slice (see README "scope cuts").
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

from langchain_core.tools import tool

from app.policy import check_refund_eligibility as _evaluate_eligibility

DATA_DIR = Path(__file__).resolve().parent / "data"
CRM_PATH = DATA_DIR / "crm.json"


class CRMStore:
    """In-memory copy of crm.json, mutable so process_refund can update state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.data: dict = {}
        self.reload()

    def reload(self) -> None:
        self.data = json.loads(self._path.read_text())

    def find_customer(self, *, email: str | None = None, customer_id: str | None = None) -> dict | None:
        for customer in self.data["customers"]:
            if email and customer["email"].lower() == email.lower():
                return customer
            if customer_id and customer["customer_id"] == customer_id:
                return customer
        return None

    def find_order(self, order_id: str) -> tuple[dict | None, dict | None]:
        for customer in self.data["customers"]:
            for order in customer["orders"]:
                if order["order_id"] == order_id:
                    return customer, order
        return None, None


store = CRMStore(CRM_PATH)


@tool
def lookup_customer(email: str) -> str:
    """Look up a customer's profile and order history in the CRM by email address.

    Returns the customer's tier, fraud flag, refund history, and their
    orders. Call this first for any refund request so you have the
    customer's context before checking a specific order. If no customer is
    found, ask the customer to confirm their email rather than guessing.
    """
    customer = store.find_customer(email=email)
    if customer is None:
        return json.dumps(
            {
                "found": False,
                "error": f"No customer found with email '{email}'. Ask the customer to confirm their email address.",
            }
        )
    return json.dumps({"found": True, "customer": customer})


@tool
def get_order_details(order_id: str) -> str:
    """Fetch a specific order by order ID.

    Returns the order date, delivered date, amount, category, item, and
    status. If no order is found, ask the customer to confirm their order ID
    rather than guessing.
    """
    customer, order = store.find_order(order_id)
    if order is None:
        return json.dumps(
            {
                "found": False,
                "error": f"No order found with ID '{order_id}'. Ask the customer to confirm their order ID.",
            }
        )
    return json.dumps({"found": True, "order": order, "customer_id": customer["customer_id"]})


@tool
def check_refund_eligibility(order_id: str, customer_email: str) -> str:
    """Deterministically apply the refund policy to one order for one customer.

    Returns pass/fail for every policy rule plus an overall decision
    ("approve", "deny", or "escalate") and the exact policy section to cite.
    This is the only source of truth for refund eligibility — always call
    this before promising, denying, or processing a refund.
    """
    customer = store.find_customer(email=customer_email)
    if customer is None:
        return json.dumps({"error": f"No customer found with email '{customer_email}'."})
    _, order = store.find_order(order_id)
    if order is None:
        return json.dumps({"error": f"No order found with ID '{order_id}'."})

    result = _evaluate_eligibility(customer, order)
    return json.dumps(result.to_dict())


@tool
def process_refund(order_id: str, customer_email: str) -> str:
    """Execute an approved refund.

    Mutates the mock CRM (marks the order refunded, appends to the
    customer's refund history) and returns a confirmation ID. Re-validates
    eligibility server-side before executing, so this only succeeds if
    check_refund_eligibility would currently return decision "approve" —
    never call this speculatively.
    """
    customer = store.find_customer(email=customer_email)
    if customer is None:
        return json.dumps({"success": False, "error": f"No customer found with email '{customer_email}'."})
    _, order = store.find_order(order_id)
    if order is None:
        return json.dumps({"success": False, "error": f"No order found with ID '{order_id}'."})

    eligibility = _evaluate_eligibility(customer, order)
    if eligibility.decision != "approve":
        return json.dumps(
            {
                "success": False,
                "error": (
                    f"Refund blocked by policy: {eligibility.reason} ({eligibility.policy_section}). "
                    "This order is not eligible for process_refund."
                ),
            }
        )

    confirmation_id = f"RF-{uuid.uuid4().hex[:8].upper()}"
    order["status"] = "refunded"
    customer["refund_history"].append(
        {"order_id": order_id, "date": date.today().isoformat(), "amount": order["amount"]}
    )
    return json.dumps(
        {
            "success": True,
            "confirmation_id": confirmation_id,
            "order_id": order_id,
            "amount": order["amount"],
            "currency": order.get("currency", "USD"),
        }
    )


@tool
def deny_refund(order_id: str, customer_email: str, policy_section: str, reason: str) -> str:
    """Record a refund denial, citing the exact policy section that was violated.

    Does not mutate order state. Always pass the policy_section and reason
    returned by check_refund_eligibility so the customer gets an accurate
    citation — never invent a policy clause.
    """
    customer = store.find_customer(email=customer_email)
    if customer is None:
        return json.dumps({"success": False, "error": f"No customer found with email '{customer_email}'."})
    _, order = store.find_order(order_id)
    if order is None:
        return json.dumps({"success": False, "error": f"No order found with ID '{order_id}'."})

    denial_id = f"DN-{uuid.uuid4().hex[:8].upper()}"
    return json.dumps(
        {
            "success": True,
            "denial_id": denial_id,
            "order_id": order_id,
            "policy_section": policy_section,
            "reason": reason,
        }
    )


@tool
def escalate_to_human(order_id: str, customer_email: str, reason: str) -> str:
    """Escalate a refund request to a human agent instead of deciding it.

    Use this whenever the policy requires human review (e.g. a
    fraud-flagged account) or the situation falls outside what the policy
    covers. Do not approve or deny the refund yourself in these cases.
    """
    customer = store.find_customer(email=customer_email)
    ticket_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
    return json.dumps(
        {
            "success": True,
            "ticket_id": ticket_id,
            "order_id": order_id,
            "customer_found": customer is not None,
            "reason": reason,
        }
    )


TOOLS = [
    lookup_customer,
    get_order_details,
    check_refund_eligibility,
    process_refund,
    deny_refund,
    escalate_to_human,
]
