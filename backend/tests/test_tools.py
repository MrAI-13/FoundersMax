import json
from datetime import date

import pytest

from app import policy as policy_module
from app.tools import (
    check_refund_eligibility,
    deny_refund,
    escalate_to_human,
    get_order_details,
    lookup_customer,
    process_refund,
    store,
)


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return date(2026, 7, 9)


@pytest.fixture(autouse=True)
def _isolate_crm(monkeypatch):
    """Reset the in-memory CRM and freeze 'today' before every test so
    process_refund mutations and window calculations don't bleed across
    tests or drift as real time passes."""
    store.reload()
    monkeypatch.setattr(policy_module, "date", _FrozenDate)
    yield
    store.reload()


def _invoke(tool, **kwargs):
    return json.loads(tool.invoke(kwargs))


def test_lookup_customer_found():
    result = _invoke(lookup_customer, email="ava.thompson@example.com")
    assert result["found"] is True
    assert result["customer"]["customer_id"] == "CUST-001"


def test_lookup_customer_not_found_returns_error_not_exception():
    result = _invoke(lookup_customer, email="nobody@example.com")
    assert result["found"] is False
    assert "No customer found" in result["error"]


def test_get_order_details_found():
    result = _invoke(get_order_details, order_id="ORD-1001")
    assert result["found"] is True
    assert result["order"]["category"] == "Electronics"


def test_get_order_details_not_found():
    result = _invoke(get_order_details, order_id="ORD-9999")
    assert result["found"] is False


def test_check_refund_eligibility_happy_path_approves():
    result = _invoke(check_refund_eligibility, order_id="ORD-1001", customer_email="ava.thompson@example.com")
    assert result["decision"] == "approve"


def test_check_refund_eligibility_denies_outside_window():
    result = _invoke(check_refund_eligibility, order_id="ORD-1002", customer_email="marcus.chen@example.com")
    assert result["decision"] == "deny"
    assert result["policy_section"] == "Section 1: Return Window"


def test_check_refund_eligibility_escalates_fraud():
    result = _invoke(check_refund_eligibility, order_id="ORD-1007", customer_email="linda.nguyen@example.com")
    assert result["decision"] == "escalate"


def test_process_refund_succeeds_for_eligible_order_and_mutates_state():
    result = _invoke(process_refund, order_id="ORD-1001", customer_email="ava.thompson@example.com")
    assert result["success"] is True
    assert result["confirmation_id"].startswith("RF-")

    customer, order = store.find_order("ORD-1001")
    assert order["status"] == "refunded"
    assert any(h["order_id"] == "ORD-1001" for h in customer["refund_history"])


def test_process_refund_blocks_ineligible_order_even_if_called_directly():
    # Guards against a hallucinated approval: process_refund re-checks
    # eligibility itself rather than trusting the caller.
    result = _invoke(process_refund, order_id="ORD-1002", customer_email="marcus.chen@example.com")
    assert result["success"] is False
    assert "blocked by policy" in result["error"]

    _, order = store.find_order("ORD-1002")
    assert order["status"] == "delivered"  # untouched


def test_process_refund_blocks_final_sale_item():
    result = _invoke(process_refund, order_id="ORD-1004", customer_email="diego.ramirez@example.com")
    assert result["success"] is False


def test_deny_refund_records_denial_without_mutating_order():
    result = _invoke(
        deny_refund,
        order_id="ORD-1002",
        customer_email="marcus.chen@example.com",
        policy_section="Section 1: Return Window",
        reason="Delivered 60 days ago; window is 30 days.",
    )
    assert result["success"] is True
    assert result["denial_id"].startswith("DN-")

    _, order = store.find_order("ORD-1002")
    assert order["status"] == "delivered"


def test_escalate_to_human_returns_ticket():
    result = _invoke(
        escalate_to_human,
        order_id="ORD-1007",
        customer_email="linda.nguyen@example.com",
        reason="Account flagged for fraud review.",
    )
    assert result["success"] is True
    assert result["ticket_id"].startswith("ESC-")
