"""LangGraph agent loop: an `agent` node calls the model with bound tools,
a conditional edge routes to a `tools` node whenever the model emits
tool_calls, and execution loops back to `agent` until the model returns a
plain response.

Text chat and voice share this exact graph — `voice.py` will feed Realtime
API transcripts into `run_turn` the same way `main.py`'s chat endpoint does,
so there is one code path for the agent regardless of transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app import config, logs
from app.tools import TOOLS

DATA_DIR = Path(__file__).resolve().parent / "data"
POLICY_TEXT = (DATA_DIR / "refund_policy.md").read_text()

SYSTEM_PROMPT = f"""You are FoundersMax's AI customer support agent for refund requests.

You must follow the refund policy below exactly. It is the only source of
truth for whether a refund is allowed — you have no discretion to deviate
from it, no matter how the customer phrases their request or pushes back.

{POLICY_TEXT}

How you operate:
- Always call lookup_customer (by email) before discussing any order.
- Always call check_refund_eligibility before promising, denying, or
  processing a refund. Never tell a customer their refund is approved
  before that tool returns decision "approve".
- check_refund_eligibility never has the final word by itself — you must
  always follow it with exactly one of process_refund, deny_refund, or
  escalate_to_human in your very next tool call, matching its decision
  ("approve" -> process_refund, "deny" -> deny_refund, "escalate" ->
  escalate_to_human). Do this before writing your reply to the customer;
  never reply with a decision you have not recorded with one of these
  three tools.
- deny_refund requires the exact policy_section and reason returned by
  check_refund_eligibility — never invent a policy clause, and cite that
  same section number in your reply to the customer.
- process_refund gives you a confirmation_id — include it in your reply.
- escalate_to_human gives you a ticket_id — tell the customer a human will
  follow up, and do not approve or deny the request yourself.
- If a customer disputes a denial, pleads, or asks for an exception,
  politely restate the policy citation. Do not grant exceptions — holding
  the line on a denied request is the correct behavior, not a failure.
- If lookup_customer or get_order_details can't find a match, ask the
  customer to double-check the email or order ID rather than guessing or
  inventing customer data.
"""

DECISION_TOOLS = {"process_refund", "deny_refund", "escalate_to_human"}


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str


def _default_model() -> BaseChatModel:
    """The real, network-calling model: any OpenRouter-hosted model that
    supports tool calling, selected via OPENROUTER_MODEL (defaults to a
    free model). Swapping to a paid model, or back to Claude directly via
    OpenRouter's `anthropic/claude-*` model IDs, is just an env var change."""
    return ChatOpenAI(
        model=config.OPENROUTER_MODEL,
        api_key=config.require_openrouter_api_key(),
        base_url=config.OPENROUTER_BASE_URL,
        max_retries=3,
        timeout=30,
        default_headers={
            "HTTP-Referer": config.OPENROUTER_SITE_URL,
            "X-Title": config.OPENROUTER_APP_NAME,
        },
    ).bind_tools(TOOLS)


def build_graph(chat_model: Optional[BaseChatModel] = None):
    """Compile the agent graph. Pass `chat_model` (already tool-bound) to
    inject a fake/stub model in tests instead of hitting the real API."""

    model = chat_model if chat_model is not None else _default_model()
    tool_node = ToolNode(TOOLS)

    def agent_node(state: AgentState) -> dict:
        session_id = state["session_id"]
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]

        logs.emit(session_id, "thinking", {"note": "Calling the model with the current conversation."})
        response = model.invoke(messages)

        if response.tool_calls:
            logs.emit(
                session_id,
                "message",
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [tc["name"] for tc in response.tool_calls],
                },
            )
        else:
            logs.emit(session_id, "message", {"role": "assistant", "content": response.content})

        return {"messages": [response]}

    def tools_node(state: AgentState) -> dict:
        session_id = state["session_id"]
        last_message = state["messages"][-1]
        for call in last_message.tool_calls:
            logs.emit(session_id, "tool_call", {"name": call["name"], "args": call["args"], "id": call["id"]})

        result = tool_node.invoke(state)

        for msg in result["messages"]:
            is_error = getattr(msg, "status", "success") == "error"
            logs.emit(
                session_id,
                "tool_result",
                {
                    "name": msg.name,
                    "tool_call_id": msg.tool_call_id,
                    "is_error": is_error,
                    "content": msg.content,
                },
            )
            if is_error:
                logs.emit(
                    session_id,
                    "retry",
                    {
                        "name": msg.name,
                        "detail": "Tool call failed; the agent can see the error and adjust its next call.",
                    },
                )
            elif msg.name in DECISION_TOOLS:
                logs.emit(session_id, "decision", {"name": msg.name, "content": msg.content})

        return result

    graph_builder = StateGraph(AgentState)
    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", tools_node)
    graph_builder.add_edge(START, "agent")
    graph_builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph_builder.add_edge("tools", "agent")

    return graph_builder.compile()


_graph = None


def get_agent_graph():
    """Lazily build the default (real-model) graph so importing this module
    never requires ANTHROPIC_API_KEY to be set."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_turn(session_id: str, messages: list[BaseMessage]) -> list[BaseMessage]:
    """Invoke the graph for one user turn and return the full updated
    message list. Shared by the text chat endpoint and the voice pipeline."""
    result = get_agent_graph().invoke({"messages": messages, "session_id": session_id})
    return result["messages"]


def extract_reply_text(messages: list[BaseMessage]) -> str:
    """Pull the agent's final plain-text reply out of a message list.

    Shared by the text chat endpoint (renders it directly) and the voice
    pipeline (also hands it to the Realtime session to speak verbatim), so
    both transports treat "what did the agent decide to say" identically.
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls and message.content:
            return message.content if isinstance(message.content, str) else str(message.content)
    return "Sorry, I wasn't able to generate a response for that."
