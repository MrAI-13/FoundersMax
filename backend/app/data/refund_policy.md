# FoundersMax Refund Policy

This document is the single source of truth for refund eligibility. It is
embedded verbatim in the agent's system prompt and mirrored in code by
`app/policy.py`. The agent must never approve or deny a refund from memory or
persuasion alone — every decision is produced by `check_refund_eligibility`
and cited by section number below.

## Section 1: Return Window

Refund requests must be submitted within **30 days of the delivery date**.

**Exception — Platinum tier customers:** the return window is extended to
**45 days** from the delivery date.

Requests submitted after the applicable window has closed are denied,
regardless of reason, item condition, or customer tier below Platinum.

## Section 2: Order Status

Only orders with status **`delivered`** are eligible for refund. Orders that
are `pending`, `shipped`, `cancelled`, or already `refunded` are not eligible:

- `pending` / `shipped` — the order has not been delivered yet; nothing to
  refund. Ask the customer to try again after delivery.
- `cancelled` — the order was already cancelled before fulfillment; there is
  no charge to refund.
- `refunded` — a refund has already been issued for this order. Duplicate
  refund requests are denied.

## Section 3: Non-Refundable Categories

The following product categories are **never refundable**, regardless of
window or order status:

- `Gift Cards`
- `Digital Downloads`

## Section 4: Final-Sale / Clearance Items

Items marked `final_sale: true` at time of purchase are sold as-is and are
**not refundable**, even if the order is otherwise within the return window
and has status `delivered`.

## Section 5: Refund Limit

Customers may receive at most **3 approved refunds in any rolling 12-month
period**. A 4th (or later) refund request within that window is denied
citing the limit, even if the underlying order is otherwise eligible.

## Section 6: Fraud Review

Customer accounts flagged `fraud_flag: true` must be **escalated to a human
agent**. The AI agent must not approve or deny refunds for flagged accounts
under any circumstances — this overrides every other rule in this document.

## Section 7: Refund Amount

The refunded amount can never exceed the original order amount. Partial
refunds are out of scope for this policy; refunds are issued for the full
order amount only.

## Decision Precedence

When multiple rules apply, evaluate in this order — the first failing rule
determines the outcome:

1. Section 6 (fraud) → if flagged, **escalate** and stop.
2. Section 2 (order status) → if not `delivered`, **deny**.
3. Section 4 (final sale) → if flagged final sale, **deny**.
4. Section 3 (non-refundable category) → if category is non-refundable, **deny**.
5. Section 1 (return window) → if outside the applicable window, **deny**.
6. Section 5 (refund limit) → if the customer already has 3+ approved
   refunds in the trailing 12 months, **deny**.
7. If every rule above passes, **approve**.

Agents must cite the exact section number when denying or escalating a
request.
