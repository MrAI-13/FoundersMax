import json
from datetime import date
from pathlib import Path

import pytest

from app.policy import check_refund_eligibility

TODAY = date(2026, 7, 9)
CRM_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "crm.json"


@pytest.fixture(scope="module")
def crm() -> dict:
    return json.loads(CRM_PATH.read_text())


def _customer(crm: dict, customer_id: str) -> dict:
    return next(c for c in crm["customers"] if c["customer_id"] == customer_id)


@pytest.mark.parametrize(
    "customer_id, expected_decision, expected_section",
    [
        ("CUST-001", "approve", "N/A"),  # happy path, well within window
        ("CUST-002", "deny", "Section 1: Return Window"),  # 60 days ago
        ("CUST-003", "approve", "N/A"),  # Platinum, 34 days within 45-day window
        ("CUST-004", "deny", "Section 4: Final-Sale / Clearance Items"),
        ("CUST-005", "deny", "Section 3: Non-Refundable Categories"),  # Gift Cards
        ("CUST-006", "deny", "Section 5: Refund Limit"),  # 3 refunds already this year
        ("CUST-007", "escalate", "Section 6: Fraud Review"),
        ("CUST-008", "deny", "Section 2: Order Status"),  # shipped, not delivered
        ("CUST-009", "deny", "Section 2: Order Status"),  # already refunded
        ("CUST-010", "deny", "Section 3: Non-Refundable Categories"),  # Digital Downloads
        ("CUST-011", "approve", "N/A"),
        ("CUST-012", "deny", "Section 1: Return Window"),  # Platinum but 99 days ago
        ("CUST-013", "approve", "N/A"),  # 2 prior refunds, under the limit of 3
        ("CUST-014", "deny", "Section 2: Order Status"),  # cancelled
        ("CUST-015", "approve", "N/A"),
    ],
)
def test_all_crm_scenarios(crm, customer_id, expected_decision, expected_section):
    customer = _customer(crm, customer_id)
    order = customer["orders"][0]
    result = check_refund_eligibility(customer, order, today=TODAY)
    assert result.decision == expected_decision
    assert result.policy_section == expected_section


def test_fraud_overrides_every_other_rule():
    customer = {
        "tier": "Standard",
        "fraud_flag": True,
        "refund_history": [],
    }
    order = {
        "order_id": "ORD-TEST",
        "status": "cancelled",
        "final_sale": True,
        "category": "Gift Cards",
        "delivered_date": None,
    }
    result = check_refund_eligibility(customer, order, today=TODAY)
    assert result.decision == "escalate"
    assert result.policy_section == "Section 6: Fraud Review"


def test_platinum_window_boundary_is_inclusive():
    customer = {"tier": "Platinum", "fraud_flag": False, "refund_history": []}
    order = {
        "order_id": "ORD-TEST",
        "status": "delivered",
        "final_sale": False,
        "category": "Electronics",
        "delivered_date": "2026-05-25",  # exactly 45 days before TODAY
    }
    result = check_refund_eligibility(customer, order, today=TODAY)
    assert result.decision == "approve"


def test_standard_window_boundary_excludes_46th_day():
    customer = {"tier": "Standard", "fraud_flag": False, "refund_history": []}
    order = {
        "order_id": "ORD-TEST",
        "status": "delivered",
        "final_sale": False,
        "category": "Electronics",
        "delivered_date": "2026-06-08",  # 31 days before TODAY
    }
    result = check_refund_eligibility(customer, order, today=TODAY)
    assert result.decision == "deny"
    assert result.policy_section == "Section 1: Return Window"


def test_refund_history_outside_rolling_year_does_not_count():
    customer = {
        "tier": "Standard",
        "fraud_flag": False,
        "refund_history": [
            {"order_id": "ORD-OLD-1", "date": "2024-01-01", "amount": 10.0},
            {"order_id": "ORD-OLD-2", "date": "2024-06-01", "amount": 10.0},
            {"order_id": "ORD-OLD-3", "date": "2024-12-01", "amount": 10.0},
        ],
    }
    order = {
        "order_id": "ORD-TEST",
        "status": "delivered",
        "final_sale": False,
        "category": "Electronics",
        "delivered_date": "2026-07-01",
    }
    result = check_refund_eligibility(customer, order, today=TODAY)
    assert result.decision == "approve"


def test_rules_list_reports_every_rule_not_just_the_deciding_one():
    customer = {"tier": "Standard", "fraud_flag": False, "refund_history": []}
    order = {
        "order_id": "ORD-TEST",
        "status": "delivered",
        "final_sale": False,
        "category": "Electronics",
        "delivered_date": "2026-07-01",
    }
    result = check_refund_eligibility(customer, order, today=TODAY)
    rule_names = {r.rule for r in result.rules}
    assert rule_names == {
        "fraud_review",
        "order_status",
        "final_sale",
        "refundable_category",
        "return_window",
        "refund_limit",
    }
