"""Voice pipeline: bridges a browser microphone WebSocket to the OpenAI
Realtime API for speech in / speech out, and hands the transcript to the
exact same LangGraph agent (`agent_graph.run_turn`) used by the text chat
endpoint — so voice and text share one decision-making code path and one
session history (see `session_store`).

The Realtime session here is used purely as a speech<->text peripheral, not
as a second decision-maker: `turn_detection` is disabled (we commit audio
ourselves on a push-to-talk model) and we never let the model auto-generate
a conversational reply. Once we have the user's transcript we run it
through `run_turn` ourselves, then ask the Realtime session to speak our
agent's exact reply back via an out-of-band (`conversation: "none"`)
response, rather than letting the Realtime model improvise a reply.

Wire protocol between the browser and `/ws/voice` in main.py — audio is
raw base64-encoded PCM16 mono at 24kHz in both directions, matching what
the Realtime API expects/produces directly (no server-side transcoding):

  browser -> server:
    {"type": "audio", "audio": "<base64 pcm16 24kHz mono>"}
    {"type": "commit"}   # user released push-to-talk; process what was said
    {"type": "cancel"}   # discard the in-progress buffer

  server -> browser:
    {"type": "ready"}
    {"type": "transcript", "text": "..."}       # what we heard
    {"type": "reply_text", "text": "..."}       # what the agent decided
    {"type": "audio", "audio": "<base64 ...>"}  # spoken reply, streamed
    {"type": "audio_done"}
    {"type": "error", "message": "..."}
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage
from openai import AsyncOpenAI
from starlette.concurrency import run_in_threadpool

from app import config, logs, session_store
from app.agent_graph import extract_reply_text, run_turn

AUDIO_FORMAT = {"type": "audio/pcm", "rate": 24000}


async def handle_voice_session(websocket: WebSocket, session_id: str) -> None:
    """Bridge one browser WebSocket connection to one OpenAI Realtime
    session for the lifetime of the connection."""
    await websocket.accept()

    try:
        api_key = config.require_openai_api_key()
    except RuntimeError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    client = AsyncOpenAI(api_key=api_key)

    try:
        async with client.realtime.connect(model=config.OPENAI_REALTIME_MODEL) as conn:
            await conn.session.update(
                session={
                    "type": "realtime",
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": AUDIO_FORMAT,
                            # We control commits ourselves (push-to-talk from the
                            # browser) rather than letting server VAD auto-commit.
                            "turn_detection": None,
                            "transcription": {"model": "gpt-realtime-whisper"},
                        },
                        "output": {
                            "format": AUDIO_FORMAT,
                            "voice": config.OPENAI_VOICE,
                        },
                    },
                }
            )
            await websocket.send_json({"type": "ready"})
            await _pump(websocket, conn, session_id)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - surface any transport/session failure rather than dropping silently
        logs.emit(session_id, "error", {"detail": f"Voice session failed: {exc}"})
        try:
            await websocket.send_json({"type": "error", "message": "Voice session failed. Please retry."})
        except Exception:
            pass


async def _pump(websocket: WebSocket, conn, session_id: str) -> None:
    browser_task = asyncio.create_task(_browser_to_openai(websocket, conn))
    openai_task = asyncio.create_task(_openai_to_browser(websocket, conn, session_id))

    done, pending = await asyncio.wait({browser_task, openai_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc is not None and not isinstance(exc, WebSocketDisconnect):
            raise exc


async def _browser_to_openai(websocket: WebSocket, conn) -> None:
    while True:
        msg = await websocket.receive_json()
        msg_type = msg.get("type")
        if msg_type == "audio":
            await conn.input_audio_buffer.append(audio=msg["audio"])
        elif msg_type == "commit":
            await conn.input_audio_buffer.commit()
        elif msg_type == "cancel":
            await conn.input_audio_buffer.clear()


async def _openai_to_browser(websocket: WebSocket, conn, session_id: str) -> None:
    async for event in conn:
        if event.type == "conversation.item.input_audio_transcription.completed":
            await _handle_transcript(websocket, conn, session_id, event.transcript)
        elif event.type == "conversation.item.input_audio_transcription.failed":
            detail = event.error.message if event.error else "Transcription failed."
            logs.emit(session_id, "error", {"detail": detail, "channel": "voice"})
            await websocket.send_json(
                {"type": "error", "message": "I couldn't hear that clearly — could you try again?"}
            )
        elif event.type == "response.output_audio.delta":
            await websocket.send_json({"type": "audio", "audio": event.delta})
        elif event.type == "response.output_audio.done":
            await websocket.send_json({"type": "audio_done"})
        elif event.type == "error":
            logs.emit(session_id, "error", {"detail": event.error.message, "channel": "voice"})
            await websocket.send_json({"type": "error", "message": event.error.message})


async def _handle_transcript(websocket: WebSocket, conn, session_id: str, transcript: str) -> None:
    transcript = (transcript or "").strip()
    if not transcript:
        return

    logs.emit(session_id, "message", {"role": "user", "content": transcript, "channel": "voice"})
    await websocket.send_json({"type": "transcript", "text": transcript})

    history = session_store.get(session_id)
    history.append(HumanMessage(content=transcript))

    try:
        messages = await run_in_threadpool(run_turn, session_id, history)
    except Exception as exc:  # noqa: BLE001 - same broad-catch contract as the text chat endpoint
        logs.emit(session_id, "error", {"detail": str(exc), "channel": "voice"})
        await websocket.send_json({"type": "error", "message": "The agent failed to respond. Please try again."})
        return

    session_store.replace(session_id, messages)
    reply_text = extract_reply_text(messages)
    await websocket.send_json({"type": "reply_text", "text": reply_text})

    # Out-of-band response: speak our agent's exact decision rather than
    # letting the Realtime model generate (and potentially alter) its own.
    await conn.response.create(
        response={
            "conversation": "none",
            "output_modalities": ["audio"],
            "instructions": (
                "Say exactly and only the following text, verbatim, with no "
                f"additions, omissions, or commentary: {reply_text}"
            ),
        }
    )
