"""Deterministic refund-eligibility engine.

Mirrors the rules written in ``app/data/refund_policy.md``. The LLM never
decides refund eligibility itself — it calls :func:`check_refund_eligibility`
and reports the result. Keep the constants and precedence order below in
sync with the markdown; each rule cites its section number so the agent can
quote the policy verbatim when it denies or escalates a request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

STANDARD_WINDOW_DAYS = 30
PLATINUM_WINDOW_DAYS = 45
MAX_REFUNDS_PER_ROLLING_YEAR = 3
NON_REFUNDABLE_CATEGORIES = {"Gift Cards", "Digital Downloads"}
ELIGIBLE_ORDER_STATUS = "delivered"

Decision = Literal["approve", "deny", "escalate"]


@dataclass
class RuleResult:
    rule: str
    passed: bool
    detail: str
    policy_section: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "detail": self.detail,
            "policy_section": self.policy_section,
        }


@dataclass
class EligibilityResult:
    order_id: str
    decision: Decision
    reason: str
    policy_section: str
    rules: list[RuleResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "decision": self.decision,
            "reason": self.reason,
            "policy_section": self.policy_section,
            "rules": [r.to_dict() for r in self.rules],
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _return_window_days(tier: str) -> int:
    return PLATINUM_WINDOW_DAYS if tier == "Platinum" else STANDARD_WINDOW_DAYS


def _refunds_in_trailing_year(refund_history: list[dict], today: date) -> int:
    cutoff = today - timedelta(days=365)
    count = 0
    for entry in refund_history:
        refunded_on = _parse_date(entry.get("date"))
        if refunded_on and refunded_on > cutoff:
            count += 1
    return count


def check_refund_eligibility(
    customer: dict,
    order: dict,
    today: date | None = None,
) -> EligibilityResult:
    """Apply the written refund policy to one order for one customer.

    Evaluates rules in the precedence order defined in
    ``refund_policy.md`` ("Decision Precedence"): fraud review first
    (escalates and overrides everything else), then order status, final
    sale, non-refundable category, return window, and finally the rolling
    refund limit. The first failing rule determines the outcome; every
    rule's pass/fail is still returned so the caller (and the admin log)
    can see the full evaluation, not just the deciding one.
    """
    today = today or date.today()
    order_id = order["order_id"]
    rules: list[RuleResult] = []

    fraud_flag = bool(customer.get("fraud_flag"))
    rules.append(
        RuleResult(
            rule="fraud_review",
            passed=not fraud_flag,
            detail=(
                "Account is flagged for fraud review."
                if fraud_flag
                else "Account is not flagged for fraud review."
            ),
            policy_section="Section 6: Fraud Review",
        )
    )
    if fraud_flag:
        return EligibilityResult(
            order_id=order_id,
            decision="escalate",
            reason="Account is flagged for fraud review and must be handled by a human agent.",
            policy_section="Section 6: Fraud Review",
            rules=rules,
        )

    status = order.get("status")
    status_ok = status == ELIGIBLE_ORDER_STATUS
    rules.append(
        RuleResult(
            rule="order_status",
            passed=status_ok,
            detail=f"Order status is '{status}'; refunds require status '{ELIGIBLE_ORDER_STATUS}'.",
            policy_section="Section 2: Order Status",
        )
    )

    final_sale = bool(order.get("final_sale"))
    rules.append(
        RuleResult(
            rule="final_sale",
            passed=not final_sale,
            detail=(
                "Item was marked final sale at time of purchase."
                if final_sale
                else "Item was not marked final sale."
            ),
            policy_section="Section 4: Final-Sale / Clearance Items",
        )
    )

    category = order.get("category")
    category_ok = category not in NON_REFUNDABLE_CATEGORIES
    rules.append(
        RuleResult(
            rule="refundable_category",
            passed=category_ok,
            detail=(
                f"Category '{category}' is non-refundable."
                if not category_ok
                else f"Category '{category}' is refundable."
            ),
            policy_section="Section 3: Non-Refundable Categories",
        )
    )

    tier = customer.get("tier", "Standard")
    window_days = _return_window_days(tier)
    delivered_on = _parse_date(order.get("delivered_date"))
    if delivered_on is None:
        within_window = False
        window_detail = "Order has not been delivered yet; no delivery date to measure the return window from."
    else:
        days_since_delivery = (today - delivered_on).days
        within_window = 0 <= days_since_delivery <= window_days
        window_detail = (
            f"Delivered {days_since_delivery} day(s) ago; {tier} tier window is {window_days} days."
        )
    rules.append(
        RuleResult(
            rule="return_window",
            passed=within_window,
            detail=window_detail,
            policy_section="Section 1: Return Window",
        )
    )

    refund_count = _refunds_in_trailing_year(customer.get("refund_history", []), today)
    under_limit = refund_count < MAX_REFUNDS_PER_ROLLING_YEAR
    rules.append(
        RuleResult(
            rule="refund_limit",
            passed=under_limit,
            detail=(
                f"Customer has {refund_count} refund(s) in the trailing 12 months "
                f"(limit is {MAX_REFUNDS_PER_ROLLING_YEAR})."
            ),
            policy_section="Section 5: Refund Limit",
        )
    )

    for rule in rules[1:]:
        if not rule.passed:
            return EligibilityResult(
                order_id=order_id,
                decision="deny",
                reason=rule.detail,
                policy_section=rule.policy_section,
                rules=rules,
            )

    return EligibilityResult(
        order_id=order_id,
        decision="approve",
        reason="Order satisfies every refund policy rule.",
        policy_section="N/A",
        rules=rules,
    )
