# FoundersMax Challenge — AI Customer Support Agent

## What this project is

A hands-on vertical slice for the FoundersMax AI Engineer interview: a fully functional web app where an AI agent processes or denies e-commerce refund requests using an LLM with tool calling. The primary deliverable is a **7–10 minute Loom walkthrough** plus a **public GitHub repo with a clean README**.

**Deadline: 2026-07-16** (7 calendar days from receipt on 2026-07-09).

## Challenge requirements (verbatim scope)

1. **Mock data** — a CRM database with **15 customer profiles** and a **strict refund policy document**.
2. **Agent backend** — an agent loop (LangGraph, CrewAI, or raw function calling) that dynamically calls tools to validate policy rules. *Bonus:* voice pipeline (OpenAI Realtime API, ElevenLabs, or LiveKit).
3. **Frontend UI** — a clean customer chat interface **and a mic voice component**, plus an admin dashboard showing real-time agent reasoning logs.

The Loom must show:
- **Live demo**: a standard refund approval AND an edge case / policy violation where the agent "holds the line" (refuses politely, citing policy). Includes a live spoken interaction via the voice pipeline.
- **Code tour**: repo architecture, tool orchestration, voice stream handling.
- **Reasoning logs**: where the agent handles failures/retries, visible in the admin panel or terminal trace.

**Voice is a required feature for this build** (not treated as optional bonus scope) — see Architecture decisions below.

## Architecture decisions

- **Agent loop: LangGraph.** The agent is built as a LangGraph graph (state machine of nodes: `agent` node calls the model with bound tools, conditional edge routes to a `tools` node on `tool_calls`, loops back to `agent` until the model returns a plain response). Rationale: LangGraph gives us explicit, inspectable graph state and built-in support for interrupts/retries, and each node transition maps cleanly to a reasoning-log event for the admin dashboard. Use `langgraph` + `langchain-anthropic` for the Claude tool-calling integration.
- **Model:** `claude-haiku-4-5` (latest Haiku; configurable via `ANTHROPIC_MODEL` env var). Chosen for speed/cost given Haiku 4.5 is now near-Sonnet-4 quality on agentic tool use — good fit for a fast, responsive support agent, and keeps the voice round-trip latency low. API key comes from `ANTHROPIC_API_KEY` — never hardcode it.
- **Backend: Python + FastAPI.** REST endpoint for chat turns, **WebSocket** channel broadcasting reasoning-log events to the admin dashboard in real time, plus the voice pipeline's audio stream handling (see Voice below).
- **Frontend: React (Vite) + Tailwind.** Three surfaces: customer chat, a mic voice component on the same chat view, and an admin dashboard (live log stream with event types color-coded: thinking, tool call, tool result, retry/error, final decision).
- **Mock data: plain JSON + Markdown, no real database.** `data/crm.json` (15 profiles with orders, purchase dates, order status, refund history, customer tier) and `data/refund_policy.md` (strict rules: e.g. 30-day window, non-refundable categories, max refunds per year, final-sale items, fraud flags). Keeping it file-based makes the repo instantly runnable — a deliberate, defensible scoping choice for a vertical slice.
- **Voice (required): OpenAI Realtime API.** Handles STT/TTS over a WebSocket session, layered over the same LangGraph agent backend. Rationale: single-vendor round trip (speech in → speech out) with low latency, and it hands us a text transcript we can feed straight into the existing graph invocation — no separate STT/TTS vendor wiring like a split ElevenLabs setup would need. The agent graph must not depend on the transport — text and voice share one code path; `voice.py` only handles the Realtime API session, audio in/out, and transcript hand-off into the same graph invocation used by the text chat endpoint. Requires `OPENAI_API_KEY` in addition to `ANTHROPIC_API_KEY`.

## Agent design

Tools the agent can call (each validates against the policy doc / CRM — the LLM never decides from memory alone):

| Tool | Purpose |
|---|---|
| `lookup_customer` | Fetch profile + order history from CRM by email/order ID |
| `get_order_details` | Fetch a specific order (date, amount, category, status) |
| `check_refund_eligibility` | Deterministic policy engine: applies the written rules to an order and returns pass/fail per rule with reasons |
| `process_refund` | Executes the refund (mutates mock CRM state, returns confirmation ID) |
| `deny_refund` | Records a denial with the policy clause cited |
| `escalate_to_human` | For cases the policy says the agent must not decide |

Key principle: **policy enforcement is deterministic code, not LLM judgment.** The LLM gathers info, calls `check_refund_eligibility`, and communicates the result empathetically. This is what makes "holding the line" reliable and demoable.

The system prompt embeds the refund policy verbatim and instructs the agent to never promise a refund before eligibility passes, and to cite the specific policy clause when denying.

## Reasoning logs (admin dashboard)

Every agent-loop event is a structured record pushed over WebSocket and kept in an in-memory session store:

```json
{"ts": "...", "session_id": "...", "type": "tool_call | tool_result | thinking | retry | error | decision | message", "payload": {...}}
```

Failure/retry handling to explicitly demo: tool errors returned as `tool_result` with `is_error: true` (agent recovers and adjusts), API errors with exponential backoff (SDK `max_retries`), and a deliberately-triggerable failure case (e.g. customer not found → agent asks for correct email instead of hallucinating).

## Planned repo layout

```
FoundersMax/
├── CLAUDE.md
├── README.md                 # setup, architecture diagram, demo script
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, chat endpoint, WS log stream, voice endpoints
│   │   ├── agent_graph.py    # LangGraph graph definition (agent node + tools node + routing)
│   │   ├── tools.py          # tool definitions + implementations
│   │   ├── policy.py         # deterministic refund-eligibility engine
│   │   ├── logs.py           # reasoning-log event bus / session store
│   │   ├── voice.py          # STT/TTS pipeline, audio stream handling into agent_graph
│   │   └── data/
│   │       ├── crm.json      # 15 mock customer profiles
│   │       └── refund_policy.md
│   ├── tests/                # policy engine + tool unit tests
│   └── requirements.txt      # fastapi, uvicorn, anthropic, langgraph, langchain-anthropic, openai, websockets, pytest
└── frontend/
    ├── src/
    │   ├── ChatView.tsx      # customer chat + mic voice component
    │   ├── VoiceControl.tsx  # mic capture / playback UI
    │   ├── AdminDashboard.tsx# live reasoning logs
    │   └── ...
    └── package.json
```

## Commands

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000

# Frontend
cd frontend && npm install && npm run dev  # http://localhost:5173

# Tests
cd backend && pytest
```

(Adjust as the code lands — keep this section current.)

## Demo scenarios to script for the Loom

1. **Happy path:** eligible customer, recent order within window → agent looks up, verifies, processes refund, confirms with ID.
2. **Hold the line:** order outside the 30-day window (or final-sale item, or refund-count exceeded) → agent denies politely, cites the exact policy clause, offers alternatives, and **does not cave when the customer pushes back / pleads / claims exceptions**.
3. **Failure recovery:** wrong email or order ID → tool returns an error, agent recovers gracefully (visible in admin logs as retry/error events).
4. **Voice:** live spoken interaction for scenario 1 or 2, using the mic component end-to-end through the same LangGraph agent.

## Working conventions

- Keep the vertical slice lean: no auth, no real DB, no deployment infra — call these out as deliberate scope cuts in the README.
- Every scoping decision should be defensible on camera; when we cut a corner, document why.
- Tool inputs/outputs flow through LangChain's `@tool`-decorated functions and typed args — rely on LangGraph's `ToolNode` to execute tool calls and append `ToolMessage`s rather than hand-rolling `tool_result` block assembly.
- Commit early and often with clear messages — the repo history is part of the work sample.
