"""Offline-only conversation presentation; real rules and FastAPI requests."""

import pytest
from fastapi.testclient import TestClient

from offline_demo.application import create_app
from offline_demo.responses import SOURCE_TITLES


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def ask(client, query, session=None):
    response = client.post("/chat", json={"query": query, "session_id": session})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("reply", ["not sure", "unknown", "I don't know"])
def test_receipt_unknown_acknowledgement_then_summary(client, reply):
    first = ask(client, "What should I do if a goods receipt fails?")
    sid = first["session_id"]
    assert "screen or transaction" in first["answer"]
    second = ask(client, reply, sid)
    assert "That's okay" in second["answer"]
    assert "message on screen" in second["answer"]
    third = ask(client, "no error message", sid)
    assert third["phase"] == "preliminary"
    assert "pause the questions" in third["answer"]
    assert "goods receipt" in third["answer"]
    assert "Still unavailable or not provided" in third["answer"]
    assert "share the on-screen message" in third["answer"]
    assert "?" not in third["answer"]
    state = client.app.state.engine.diagnosis_store.get(sid)
    assert not state.answers
    assert set(state.unknown_fields) == {"transaction", "error_message"}
    assert "po_number" not in state.unknown_fields  # Not asked is not confirmed absent.
    followup = ask(client, reply, sid)
    assert followup["phase"] == "preliminary"
    assert "?" not in followup["answer"]
    assert not followup["answer"].startswith("DEMO")


@pytest.mark.parametrize(
    "query,topic,code",
    [
        (
            "My supplier invoice is not processing. What should I check?",
            "invoice",
            "MIRO",
        ),
        ("My purchase order is not releasing", "release", "ME29N"),
        ("My user is not authorized", "authorization", "ME29N"),
        ("My sales order is not visible", "sales", "VA03"),
    ],
)
def test_other_troubleshooting_scenarios_pause_and_accept_correction(
    client, query, topic, code
):
    first = ask(client, query)
    sid = first["session_id"]
    assert first["phase"] == "clarifying"
    ask(client, code, sid)
    ask(client, "no error message", sid)
    summary = ask(client, "unknown", sid)
    assert summary["phase"] == "preliminary"
    assert code in summary["answer"]
    assert summary["sources"][0]["title"] == SOURCE_TITLES[topic]
    assert "?" not in summary["answer"]
    corrected = ask(client, "Actually transaction is ME23N", sid)
    state = client.app.state.engine.diagnosis_store.get(sid)
    assert state.answers["transaction"] == "ME23N"
    assert code not in corrected["answer"]
    assert "ME23N" in corrected["answer"]


@pytest.mark.parametrize(
    "query,topic",
    [
        ("What is a payment block in SAP?", "invoice"),
        ("What is an inspection lot?", "inspection"),
    ],
)
def test_concept_answers_keep_exact_ids_with_readable_titles(client, query, topic):
    response = ask(client, query)
    source = response["sources"][0]
    assert source["title"] == SOURCE_TITLES[topic]
    assert source["citation_handle"].startswith("SRC-")
    assert source["citation_handle"] in response["answer"]
    assert not response["answer"].startswith("DEMO")
    stored = client.app.state.engine.session_store.get_or_create(response["session_id"])
    assert stored.messages[-1]["content"] == response["answer"]


def test_offline_controller_only_applies_safe_presentation_adapter(client):
    response = client.get("/static/js/app.js")
    assert response.status_code == 200
    assert "OFFLINE_CITATION_TITLES" in response.text
    assert "chip.dataset.citationHandle" in response.text
    assert "chip.textContent = source.title" in response.text
    assert "text = readableReferences(text)" in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "TEST_ONLY / DEMO / SIMULATED" in client.get("/").text
