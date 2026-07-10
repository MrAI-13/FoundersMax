"""Reasoning-log event bus for the admin dashboard.

Every agent-loop event (thinking, tool call/result, retry, error, decision,
final message) is appended to a per-session in-memory list and broadcast to
subscribed listeners. ``main.py`` subscribes a listener per WebSocket
connection to stream events live; tests read ``bus.history(session_id)``
directly without needing a socket.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

EventType = Literal["thinking", "tool_call", "tool_result", "retry", "error", "decision", "message"]
Listener = Callable[["LogEvent"], None]

_seq = itertools.count(1)


@dataclass(frozen=True)
class LogEvent:
    ts: str
    session_id: str
    type: EventType
    payload: dict
    seq: int

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "session_id": self.session_id,
            "type": self.type,
            "payload": self.payload,
            "seq": self.seq,
        }


class LogBus:
    def __init__(self) -> None:
        self._sessions: dict[str, list[LogEvent]] = {}
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self, session_id: str, type: EventType, payload: dict) -> LogEvent:
        event = LogEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            type=type,
            payload=payload,
            seq=next(_seq),
        )
        self._sessions.setdefault(session_id, []).append(event)
        for listener in list(self._listeners):
            listener(event)
        return event

    def history(self, session_id: str) -> list[dict]:
        return [e.to_dict() for e in self._sessions.get(session_id, [])]

    def all_history(self) -> list[dict]:
        """Every event across every session, in emission order — used to
        replay the full transcript to a freshly-connected admin dashboard."""
        events = [event for session_events in self._sessions.values() for event in session_events]
        events.sort(key=lambda e: e.seq)
        return [e.to_dict() for e in events]

    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._sessions.clear()
        else:
            self._sessions.pop(session_id, None)


bus = LogBus()


def emit(session_id: str, type: EventType, payload: dict) -> LogEvent:
    return bus.emit(session_id, type, payload)
