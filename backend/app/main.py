"""FastAPI app: chat REST endpoint, WebSocket reasoning-log stream for the
admin dashboard, the voice WebSocket, and a dev-only reset endpoint. Text
chat and voice both go through `agent_graph.run_turn` and share session
history via `session_store`, so a session_id carries the same conversation
regardless of transport.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import logs, session_store
from app.agent_graph import extract_reply_text, run_turn
from app.tools import store
from app.voice import handle_voice_session

app = FastAPI(title="FoundersMax Customer Support")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    logs.emit(session_id, "message", {"role": "user", "content": req.message})

    history = session_store.get(session_id)
    history.append(HumanMessage(content=req.message))

    try:
        messages = await run_in_threadpool(run_turn, session_id, history)
    except Exception as exc:  # noqa: BLE001 - deliberately broad: surface any agent failure to the client and the admin log
        logs.emit(session_id, "error", {"detail": str(exc)})
        raise HTTPException(
            status_code=502, detail="The agent failed to respond. Please try again."
        ) from exc

    session_store.replace(session_id, messages)
    return ChatResponse(session_id=session_id, reply=extract_reply_text(messages))


@app.post("/api/reset")
def reset() -> dict:
    """Dev convenience: wipe chat history, reasoning logs, and CRM mutations
    so a demo scenario can be re-run from a clean slate without restarting
    the server."""
    session_store.clear()
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


@app.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket, session_id: Optional[str] = None) -> None:
    await handle_voice_session(websocket, session_id or str(uuid.uuid4()))
