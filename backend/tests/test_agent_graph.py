"""Agent-loop tests using a scripted fake model (no network calls / no API
key needed). Each test drives build_graph() with a FakeMessagesListChatModel
that returns a fixed sequence of AIMessages, so we can assert on the graph's
routing and on the reasoning-log events without depending on a live LLM."""

import json
from datetime import date

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app import logs, policy as policy_module
from app.agent_graph import build_graph
from app.tools import store


class _FrozenDate(date):
    @classmethod
    def today(cls):
        return date(2026, 7, 9)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    store.reload()
    monkeypatch.setattr(policy_module, "date", _FrozenDate)
    logs.bus.clear()
    yield
    store.reload()
    logs.bus.clear()


def _run(session_id: str, responses: list[AIMessage], user_text: str) -> list:
    fake_model = FakeMessagesListChatModel(responses=responses)
    graph = build_graph(chat_model=fake_model)
    result = graph.invoke({"messages": [HumanMessage(content=user_text)], "session_id": session_id})
    return result["messages"]


def test_happy_path_approves_and_processes_refund():
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "lookup_customer", "args": {"email": "ava.thompson@example.com"}, "id": "call_1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "check_refund_eligibility",
                    "args": {"order_id": "ORD-1001", "customer_email": "ava.thompson@example.com"},
                    "id": "call_2",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "process_refund",
                    "args": {"order_id": "ORD-1001", "customer_email": "ava.thompson@example.com"},
                    "id": "call_3",
                }
            ],
        ),
        AIMessage(content="Your refund has been processed. Confirmation ID included above.", tool_calls=[]),
    ]

    messages = _run("session-happy", responses, "I'd like a refund for order ORD-1001")

    assert messages[-1].content.startswith("Your refund has been processed")
    _, order = store.find_order("ORD-1001")
    assert order["status"] == "refunded"

    event_types = [e["type"] for e in logs.bus.history("session-happy")]
    assert event_types.count("tool_call") == 3
    assert event_types.count("tool_result") == 3
    assert "decision" in event_types

    decision_events = [e for e in logs.bus.history("session-happy") if e["type"] == "decision"]
    assert decision_events[0]["payload"]["name"] == "process_refund"


def test_hold_the_line_denies_and_cites_policy_section():
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "lookup_customer", "args": {"email": "marcus.chen@example.com"}, "id": "call_1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "check_refund_eligibility",
                    "args": {"order_id": "ORD-1002", "customer_email": "marcus.chen@example.com"},
                    "id": "call_2",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "deny_refund",
                    "args": {
                        "order_id": "ORD-1002",
                        "customer_email": "marcus.chen@example.com",
                        "policy_section": "Section 1: Return Window",
                        "reason": "Delivered 60 days ago; the return window is 30 days.",
                    },
                    "id": "call_3",
                }
            ],
        ),
        AIMessage(
            content="I'm sorry, but this order is outside our 30-day return window (Section 1), so I can't process a refund.",
            tool_calls=[],
        ),
    ]

    messages = _run("session-deny", responses, "I want a refund for order ORD-1002")

    assert "Section 1" in messages[-1].content
    _, order = store.find_order("ORD-1002")
    assert order["status"] == "delivered"  # never mutated

    decision_events = [e for e in logs.bus.history("session-deny") if e["type"] == "decision"]
    assert decision_events[0]["payload"]["name"] == "deny_refund"


def test_failure_recovery_on_unknown_customer_logs_tool_error_and_retry():
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "lookup_customer", "args": {"email": "typo@example.com"}, "id": "call_1"}],
        ),
        AIMessage(content="I couldn't find that email — could you double check it for me?", tool_calls=[]),
    ]

    messages = _run("session-recover", responses, "My email is typo@example.com")

    tool_result = json.loads(messages[2].content)
    assert tool_result["found"] is False

    event_types = [e["type"] for e in logs.bus.history("session-recover")]
    assert "tool_result" in event_types
    assert messages[-1].content.startswith("I couldn't find that email")


def test_escalation_path_for_fraud_flagged_account():
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "lookup_customer", "args": {"email": "linda.nguyen@example.com"}, "id": "call_1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "check_refund_eligibility",
                    "args": {"order_id": "ORD-1007", "customer_email": "linda.nguyen@example.com"},
                    "id": "call_2",
                }
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "escalate_to_human",
                    "args": {
                        "order_id": "ORD-1007",
                        "customer_email": "linda.nguyen@example.com",
                        "reason": "Account flagged for fraud review (Section 6).",
                    },
                    "id": "call_3",
                }
            ],
        ),
        AIMessage(content="I've escalated this to a specialist who will follow up with you shortly.", tool_calls=[]),
    ]

    messages = _run("session-escalate", responses, "Can I get a refund on ORD-1007?")

    assert "escalated" in messages[-1].content.lower()
    decision_events = [e for e in logs.bus.history("session-escalate") if e["type"] == "decision"]
    assert decision_events[0]["payload"]["name"] == "escalate_to_human"


def test_process_refund_cannot_be_forced_past_policy_even_if_model_tries():
    # The model skips check_refund_eligibility and goes straight for
    # process_refund on an ineligible order. process_refund must still
    # block it server-side.
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "process_refund",
                    "args": {"order_id": "ORD-1004", "customer_email": "diego.ramirez@example.com"},
                    "id": "call_1",
                }
            ],
        ),
        AIMessage(content="That item was final sale, so I'm not able to refund it.", tool_calls=[]),
    ]

    messages = _run("session-guard", responses, "Refund my clearance hoodie, order ORD-1004")

    tool_result = json.loads(messages[2].content)
    assert tool_result["success"] is False

    _, order = store.find_order("ORD-1004")
    assert order["status"] == "delivered"  # untouched despite the attempted call
