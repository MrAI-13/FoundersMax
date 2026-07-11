import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import logs, main, session_store
from app.tools import store


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


def _fake_run_turn(reply_text: str = "Hello from the fake agent"):
    def _run(session_id, messages):
        logs.emit(session_id, "thinking", {"note": "fake turn"})
        logs.emit(session_id, "message", {"role": "assistant", "content": reply_text})
        return messages + [AIMessage(content=reply_text, tool_calls=[])]

    return _run


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_returns_session_id_and_reply(client, monkeypatch):
    monkeypatch.setattr(main, "run_turn", _fake_run_turn("Hi there!"))

    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Hi there!"
    assert data["session_id"]


def test_chat_persists_history_across_calls(client, monkeypatch):
    captured_lengths = []

    def _run(session_id, messages):
        captured_lengths.append(len(messages))
        return messages + [AIMessage(content=f"turn {len(captured_lengths)}", tool_calls=[])]

    monkeypatch.setattr(main, "run_turn", _run)

    r1 = client.post("/api/chat", json={"message": "first"})
    session_id = r1.json()["session_id"]
    assert r1.json()["reply"] == "turn 1"

    r2 = client.post("/api/chat", json={"session_id": session_id, "message": "second"})
    assert r2.json()["reply"] == "turn 2"
    assert r2.json()["session_id"] == session_id

    # second call's history included first turn's human + AI messages plus the new human message
    assert captured_lengths == [1, 3]


def test_chat_new_session_id_when_omitted(client, monkeypatch):
    monkeypatch.setattr(main, "run_turn", _fake_run_turn())

    r1 = client.post("/api/chat", json={"message": "hi"})
    r2 = client.post("/api/chat", json={"message": "hi again"})
    assert r1.json()["session_id"] != r2.json()["session_id"]


def test_chat_agent_failure_returns_502_and_logs_error(client, monkeypatch):
    def _boom(session_id, messages):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(main, "run_turn", _boom)

    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 502

    # session_id was generated before the failure, so the error was logged
    # under some session; there should be exactly one error event recorded.
    all_events = logs.bus.all_history()
    assert any(e["type"] == "error" and "upstream exploded" in e["payload"]["detail"] for e in all_events)


def test_reset_clears_sessions_logs_and_crm(client, monkeypatch):
    monkeypatch.setattr(main, "run_turn", _fake_run_turn())
    client.post("/api/chat", json={"message": "hi"})
    assert session_store.session_ids()
    assert logs.bus.all_history()

    _, order = store.find_order("ORD-1001")
    order["status"] = "refunded"  # simulate a mutation from a prior demo take

    resp = client.post("/api/reset")
    assert resp.status_code == 200
    assert session_store.session_ids() == []
    assert logs.bus.all_history() == []

    _, order_after = store.find_order("ORD-1001")
    assert order_after["status"] == "delivered"


def test_chat_logs_the_users_text_message(client, monkeypatch):
    """Regression: the text chat endpoint used to only log the assistant's
    side of the turn, so the admin dashboard never showed what the customer
    actually typed (voice already logged its transcript in voice.py)."""
    monkeypatch.setattr(main, "run_turn", _fake_run_turn("Hi there!"))

    resp = client.post("/api/chat", json={"message": "hello from the customer"})
    session_id = resp.json()["session_id"]

    events = logs.bus.history(session_id)
    assert events[0]["type"] == "message"
    assert events[0]["payload"] == {"role": "user", "content": "hello from the customer"}


def test_websocket_receives_live_log_events(client, monkeypatch):
    monkeypatch.setattr(main, "run_turn", _fake_run_turn("Streamed reply"))

    with client.websocket_connect("/ws/logs") as ws:
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200

        seen_types = [ws.receive_json()["type"], ws.receive_json()["type"], ws.receive_json()["type"]]
        assert seen_types == ["message", "thinking", "message"]


def test_websocket_replays_history_on_connect(client, monkeypatch):
    monkeypatch.setattr(main, "run_turn", _fake_run_turn("Replayed"))

    client.post("/api/chat", json={"message": "hello before connecting"})

    with client.websocket_connect("/ws/logs") as ws:
        first = ws.receive_json()
        assert first["type"] == "message"
        assert first["payload"]["role"] == "user"
        second = ws.receive_json()
        assert second["type"] == "thinking"
        third = ws.receive_json()
        assert third["type"] == "message"
        assert third["payload"]["role"] == "assistant"
