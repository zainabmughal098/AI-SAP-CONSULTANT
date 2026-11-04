"""Actual local session routes/stores; no providers or persisted SAP data."""

import pytest
from fastapi.testclient import TestClient

from offline_demo.application import OfflineConsultant, create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def ask(client, query, session_id=None):
    result = client.post("/chat", json={"query": query, "session_id": session_id})
    assert result.status_code == 200
    return result.json()


def test_new_conversation_has_no_previous_fields_or_topic(client):
    old = ask(client, "My PO is not releasing in ME29N")
    old_sid = old["session_id"]
    for reply in ["no error message", "not sure"]:
        ask(client, reply, old_sid)
    new = ask(
        client, "What should I do if a goods receipt fails?", "TEST_ONLY_NEW_CHAT"
    )
    engine = client.app.state.engine
    old_state = engine.diagnosis_store.get(old_sid)
    new_state = engine.diagnosis_store.get(new["session_id"])
    assert new["session_id"] != old_sid
    assert old_state.tree_id == "po_release"
    assert new_state.tree_id == "goods_receipt"
    assert new_state.answers == {} and new_state.unknown_fields == {}
    assert new_state.pending_field == "transaction"
    assert "ME29N" not in new["answer"]
    assert (
        engine.session_store.get_or_create(new["session_id"])
        .get_messages()[0]["content"]
        .startswith("What should")
    )
    resumed = ask(client, "Actually transaction is ME23N", old_sid)
    assert old_state.answers["transaction"] == "ME23N"
    assert new_state.answers == {}
    assert resumed["session_id"] == old_sid


def test_delete_removes_memory_diagnosis_turns_and_fault_state(client):
    first = ask(client, "My PO is not releasing in ME29N", "TEST_ONLY_DELETE")
    sid = first["session_id"]
    engine = client.app.state.engine
    memory = engine.session_store.get_or_create(sid)
    engine.fault_state[sid] = True
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert memory.messages == []
    assert sid not in engine.session_store._sessions
    assert engine.diagnosis_store.get(sid) is None
    assert sid not in engine.diagnosis_manager.turns
    assert sid not in engine.fault_state
    assert (
        client.post("/chat", json={"query": "not sure", "session_id": sid}).status_code
        == 404
    )


def test_delete_while_delayed_stream_is_open_cannot_recreate_state(client):
    result = ask(client, "My invoice fails in MIRO")
    sid = result["session_id"]
    engine = client.app.state.engine
    active = OfflineConsultant(
        session_store=engine.session_store,
        diagnosis_manager=engine.diagnosis_manager,
        memory=engine.session_store.get_or_create(sid),
    )
    active.fault_state = engine.fault_state
    events = active.ask_stream("TEST_ONLY delayed response")
    assert next(events)["type"] == "session"
    assert next(events)["type"] == "status"
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert list(events) == []
    assert sid not in engine.session_store._sessions
    assert engine.diagnosis_store.get(sid) is None
    assert sid not in engine.diagnosis_manager.turns


def test_delete_before_first_request_arrives_prevents_late_creation(client):
    assert client.delete("/sessions/TEST_ONLY_NOT_STARTED").status_code == 404
    result = client.post(
        "/chat",
        json={"query": "My PO is not releasing", "session_id": "TEST_ONLY_NOT_STARTED"},
    )
    assert result.status_code == 404
    assert client.app.state.engine.diagnosis_store.get("TEST_ONLY_NOT_STARTED") is None


def test_deleting_one_session_leaves_another_conversation_usable(client):
    first = ask(client, "My PO is not releasing in ME29N")
    other = ask(client, "My goods receipt failed in MIGO")
    assert client.delete(f"/sessions/{first['session_id']}").status_code == 200
    answer = ask(client, "no error message", other["session_id"])
    assert answer["session_id"] == other["session_id"]
    state = client.app.state.engine.diagnosis_store.get(other["session_id"])
    assert state.tree_id == "goods_receipt"
    assert state.answers["transaction"] == "MIGO"
