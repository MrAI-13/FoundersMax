"""In-memory per-session chat history, shared by the text chat endpoint and
the voice pipeline so a given session_id carries the same conversation
regardless of which transport is used. In-memory only, matching the rest of
the app's "no real database" scope cut.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage

_sessions: dict[str, list[BaseMessage]] = {}


def get(session_id: str) -> list[BaseMessage]:
    return _sessions.setdefault(session_id, [])


def replace(session_id: str, messages: list[BaseMessage]) -> None:
    _sessions[session_id] = messages


def clear() -> None:
    _sessions.clear()


def session_ids() -> list[str]:
    return list(_sessions.keys())
