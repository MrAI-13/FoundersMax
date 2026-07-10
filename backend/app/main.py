"""FastAPI app: chat REST endpoint, WebSocket reasoning-log stream for the
admin dashboard, and a dev-only reset endpoint. Voice endpoints land in a
later pass (see voice.py in the planned layout) and will call the same
`run_turn` used here, so text and voice share one agent code path.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import logs
from app.agent_graph import run_turn
from app.tools import store

app = FastAPI(title="FoundersMax Refund Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# session_id -> full LangChain message history. In-memory only, matching the
# rest of the app's "no real database" scope cut.
_chat_sessions: dict[str, list[BaseMessage]] = {}


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


def _last_reply_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls and message.content:
            return message.content if isinstance(message.content, str) else str(message.content)
    return "Sorry, I wasn't able to generate a response for that."


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    history = _chat_sessions.setdefault(session_id, [])
    history.append(HumanMessage(content=req.message))

    try:
        messages = await run_in_threadpool(run_turn, session_id, history)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: surface any agent failure to the client and the admin log
        logs.emit(session_id, "error", {"detail": str(exc)})
        raise HTTPException(
            status_code=502, detail="The agent failed to respond. Please try again."
        ) from exc

    _chat_sessions[session_id] = messages
    return ChatResponse(session_id=session_id, reply=_last_reply_text(messages))


@app.post("/api/reset")
def reset() -> dict:
    """Dev convenience: wipe chat history, reasoning logs, and CRM mutations
    so a demo scenario can be re-run from a clean slate without restarting
    the server."""
    _chat_sessions.clear()
    logs.bus.clear()
    store.reload()
    return {"status": "reset"}


@app.websocket("/ws/logs")
async def logs_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _on_event(event: logs.LogEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event.to_dict())

    for event in logs.bus.all_history():
        await websocket.send_json(event)

    unsubscribe = logs.bus.subscribe(_on_event)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe()
