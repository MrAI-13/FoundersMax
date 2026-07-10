"""Voice pipeline tests using a fake Realtime connection (no network calls
to OpenAI). The fake mimics just enough of the openai SDK's
`client.realtime.connect()` surface — session.update, input_audio_buffer.
append/commit/clear, response.create, and async iteration over server
events — for voice.py's event loop to run against it unmodified."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import logs, main, session_store, voice
from app.tools import store


def _event(type: str, **kwargs) -> SimpleNamespace:
    return SimpleNamespace(type=type, **kwargs)


class FakeInputAudioBuffer:
    def __init__(self, conn: "FakeConnection") -> None:
        self._conn = conn

    async def append(self, *, audio: str) -> None:
        self._conn.appended.append(audio)

    async def commit(self) -> None:
        self._conn.committed += 1
        for event in self._conn.pop_commit_events():
            await self._conn.queue.put(event)

    async def clear(self) -> None:
        self._conn.cleared += 1


class FakeSession:
    def __init__(self, conn: "FakeConnection") -> None:
        self._conn = conn

    async def update(self, *, session: dict) -> None:
        self._conn.session_updates.append(session)


class FakeResponse:
    def __init__(self, conn: "FakeConnection") -> None:
        self._conn = conn

    async def create(self, *, response: dict) -> None:
        self._conn.responses_created.append(response)
        await self._conn.queue.put(_event("response.output_audio.delta", delta="ZmFrZS1hdWRpbw=="))
        await self._conn.queue.put(_event("response.output_audio.done"))


class FakeConnection:
    """`commit_events` is a list of event-lists: the Nth commit() call
    enqueues the Nth list of fake server events (e.g. a transcription
    completed event)."""

    def __init__(self, commit_events: list[list[SimpleNamespace]] | None = None) -> None:
        # Lazily created on first async access rather than here: this object
        # is constructed in plain sync test code, before the TestClient's
        # WebSocket portal thread (with its own event loop) exists. Python
        # 3.9's asyncio.Queue binds to "the current loop" eagerly at
        # construction, so building it here would bind it to the wrong loop
        # and any await on it from the portal's loop would raise "Future
        # attached to a different loop".
        self._queue: asyncio.Queue | None = None
        self._commit_events = list(commit_events or [])
        self.appended: list[str] = []
        self.committed = 0
        self.cleared = 0
        self.session_updates: list[dict] = []
        self.responses_created: list[dict] = []
        self.session = FakeSession(self)
        self.input_audio_buffer = FakeInputAudioBuffer(self)
        self.response = FakeResponse(self)

    @property
    def queue(self) -> asyncio.Queue:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def pop_commit_events(self) -> list[SimpleNamespace]:
        if self._commit_events:
            return self._commit_events.pop(0)
        return []

    def __aiter__(self) -> "FakeConnection":
        return self

    async def __anext__(self) -> SimpleNamespace:
        return await self.queue.get()


class FakeConnectionManager:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc_info) -> bool:
        return False


def _fake_openai_client(conn: FakeConnection):
    def _factory(*, api_key: str):
        return SimpleNamespace(realtime=SimpleNamespace(connect=lambda *, model: FakeConnectionManager(conn)))

    return _factory


@pytest.fixture(autouse=True)
def _isolate():
    session_store.clear()
    logs.bus.clear()
    store.reload()
    yield
    session_store.clear()
    logs.bus.clear()
    store.reload()


@pytest.fixture
def client():
    return TestClient(main.app)


def _fake_run_turn(reply_text: str):
    def _run(session_id, messages):
        return messages + [AIMessage(content=reply_text, tool_calls=[])]

    return _run


def test_voice_happy_path_transcribes_runs_agent_and_speaks_reply(client, monkeypatch):
    conn = FakeConnection(
        commit_events=[[_event("conversation.item.input_audio_transcription.completed", transcript="I want a refund")]]
    )
    monkeypatch.setattr(voice, "AsyncOpenAI", _fake_openai_client(conn))
    monkeypatch.setattr(voice, "run_turn", _fake_run_turn("Sure, here is your confirmation."))

    with client.websocket_connect("/ws/voice?session_id=voice-happy") as ws:
        assert ws.receive_json() == {"type": "ready"}

        ws.send_json({"type": "audio", "audio": "YWJj"})
        ws.send_json({"type": "commit"})

        assert ws.receive_json() == {"type": "transcript", "text": "I want a refund"}
        assert ws.receive_json() == {"type": "reply_text", "text": "Sure, here is your confirmation."}
        assert ws.receive_json() == {"type": "audio", "audio": "ZmFrZS1hdWRpbw=="}
        assert ws.receive_json() == {"type": "audio_done"}

    assert conn.appended == ["YWJj"]
    assert conn.committed == 1
    assert conn.responses_created[0]["conversation"] == "none"
    assert "Sure, here is your confirmation." in conn.responses_created[0]["instructions"]

    # session config disabled auto turn detection so we control commits
    assert conn.session_updates[0]["audio"]["input"]["turn_detection"] is None


def test_voice_shares_session_history_with_text_chat(client, monkeypatch):
    conn = FakeConnection(
        commit_events=[[_event("conversation.item.input_audio_transcription.completed", transcript="Hi there")]]
    )
    monkeypatch.setattr(voice, "AsyncOpenAI", _fake_openai_client(conn))

    captured_lengths = []

    def _run(session_id, messages):
        captured_lengths.append(len(messages))
        return messages + [AIMessage(content="voice reply", tool_calls=[])]

    monkeypatch.setattr(voice, "run_turn", _run)
    monkeypatch.setattr(main, "run_turn", _run)

    with client.websocket_connect("/ws/voice?session_id=shared-session") as ws:
        ws.receive_json()  # ready
        ws.send_json({"type": "commit"})
        ws.receive_json()  # transcript
        ws.receive_json()  # reply_text
        ws.receive_json()  # audio
        ws.receive_json()  # audio_done

    # follow-up text message on the same session_id continues the same history
    resp = client.post("/api/chat", json={"session_id": "shared-session", "message": "and also this"})
    assert resp.status_code == 200
    # voice turn added 1 human msg, run_turn appended 1 AI msg -> history len 2
    # before the text call appends its own human message (making it 3 going in)
    assert captured_lengths == [1, 3]


def test_voice_transcription_failure_reports_error(client, monkeypatch):
    conn = FakeConnection(
        commit_events=[
            [
                _event(
                    "conversation.item.input_audio_transcription.failed",
                    error=SimpleNamespace(message="audio too quiet"),
                )
            ]
        ]
    )
    monkeypatch.setattr(voice, "AsyncOpenAI", _fake_openai_client(conn))

    with client.websocket_connect("/ws/voice?session_id=voice-fail") as ws:
        ws.receive_json()  # ready
        ws.send_json({"type": "commit"})
        error_msg = ws.receive_json()
        assert error_msg["type"] == "error"

    events = logs.bus.history("voice-fail")
    assert any(e["type"] == "error" and "audio too quiet" in e["payload"]["detail"] for e in events)


def test_voice_agent_failure_reports_error_and_skips_tts(client, monkeypatch):
    conn = FakeConnection(
        commit_events=[[_event("conversation.item.input_audio_transcription.completed", transcript="refund please")]]
    )
    monkeypatch.setattr(voice, "AsyncOpenAI", _fake_openai_client(conn))

    def _boom(session_id, messages):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(voice, "run_turn", _boom)

    with client.websocket_connect("/ws/voice?session_id=voice-agent-fail") as ws:
        ws.receive_json()  # ready
        ws.send_json({"type": "commit"})
        assert ws.receive_json() == {"type": "transcript", "text": "refund please"}
        error_msg = ws.receive_json()
        assert error_msg["type"] == "error"

    assert conn.responses_created == []  # never asked the model to speak anything
    events = logs.bus.history("voice-agent-fail")
    assert any(e["type"] == "error" and "agent exploded" in e["payload"]["detail"] for e in events)


def test_voice_missing_api_key_reports_error(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "OPENAI_API_KEY", "")

    with client.websocket_connect("/ws/voice?session_id=voice-no-key") as ws:
        error_msg = ws.receive_json()
        assert error_msg["type"] == "error"
        assert "OPEN_AI_API_KEY" in error_msg["message"]
