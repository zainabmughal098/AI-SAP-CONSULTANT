"""Simulated display recommendations through real offline JSON/SSE routes."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from offline_demo.application import create_app
from offline_demo.fixtures import FixtureRetriever
from offline_demo.support_areas import SUPPORT_AREAS

CASES = [
    ("My purchase order is not releasing.", "Procurement / SAP MM", "release"),
    ("My supplier invoice is not processing.", "Finance / SAP FI", "invoice"),
    ("What should I do if a goods receipt fails?", "Inventory / SAP MM", "receipt"),
    ("My sales order is not visible.", "Sales / SAP SD", "sales"),
]


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def ask(client, query, sid=None, **extra):
    response = client.post("/chat", json={"query": query, "session_id": sid, **extra})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("query,area,topic", CASES)
@pytest.mark.parametrize("stream", [False, True])
def test_recommendations_are_display_only_and_cited(
    client, monkeypatch, query, area, topic, stream
):
    def forbidden(*args, **kwargs):
        pytest.fail("A display recommendation attempted an outbound operation")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("smtplib.SMTP", forbidden)
    response = client.post("/chat/stream" if stream else "/chat", json={"query": query})
    assert response.status_code == 200
    if stream:
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        result = events[-1]
        assert result["type"] == "done"
        assert (
            "".join(e["content"] for e in events if e["type"] == "token")
            == result["answer"]
        )
        assert (
            next(e["sources"] for e in events if e["type"] == "sources")
            == result["sources"]
        )
    else:
        result = response.json()
    assert result["complete"] and result["phase"] == "clarifying"
    assert f"**Suggested support area:** {area}" in result["answer"]
    assert "Status: SIMULATED — No ticket created or forwarded." in result["answer"]
    assert (
        "Actual department assignment requires organizational verification."
        in result["answer"]
    )
    assert result["answer"].count("Suggested support area:") == 1
    assert result["sources"][0]["id"] == f"TEST_ONLY-{topic}"
    assert not {"ticket_id", "department", "assignee", "forwarded_to"}.intersection(
        result
    )
    assert "TEST_ONLY / DEMO / SIMULATED" in client.get("/").text


@pytest.mark.parametrize(
    "query",
    [
        "My order is blocked.",
        "Posting failed.",
        "My invoice and sales order both fail.",
        "My purchase order is not releasing and goods receipt fails.",
        "My inspection results are missing.",
        "I have no authorization.",
        "What is a payment block in SAP?",
        "Explain invoice posting",
        "What is ME21N?",
        "What are SAP T-codes?",
        "What is FFC's approval policy?",
        "What is ZDEMO999?",
        "DEMO fixture: receipt",
    ],
)
def test_ambiguous_unsupported_informational_or_fixture_commands_have_no_recommendation(
    client, query
):
    assert "Suggested support area:" not in ask(client, query)["answer"]


def test_side_question_followups_corrections_and_topic_switch(client):
    first = ask(client, CASES[2][0])
    sid = first["session_id"]
    engine = client.app.state.engine
    state = engine.diagnosis_store.get(sid)
    before = deepcopy(state.to_dict())
    assert "Suggested support area:" not in ask(client, "What is MIGO?", sid)["answer"]
    assert state.to_dict() == before
    for query in [
        "not sure",
        "no error message",
        "Actually transaction is MIGO",
        "What should I check next?",
    ]:
        assert "Inventory / SAP MM" in ask(client, query, sid)["answer"]
    assert state.answers["transaction"] == "MIGO"
    assert (
        "Inventory / SAP MM"
        in engine.session_store.get_or_create(sid).messages[-1]["content"]
    )
    switched = ask(client, "New question: My sales order is not visible.", sid)
    assert "Sales / SAP SD" in switched["answer"]
    assert "Inventory / SAP MM" not in switched["answer"]
    assert (
        "Suggested support area:"
        not in ask(client, "Explain VA01 instead", sid)["answer"]
    )
    assert not state.tree_id


def test_conflicting_details_suppress_recommendation(client):
    sid = ask(client, "My goods receipt fails in MIGO.")["session_id"]
    result = ask(client, "Transaction: MIRO", sid)
    assert client.app.state.engine.diagnosis_store.get(sid).conflicts
    assert "Suggested support area:" not in result["answer"]


def test_failed_source_admission_or_filter_never_acquires_recommendation(
    client, monkeypatch
):
    assert (
        "Suggested support area:"
        not in ask(client, CASES[2][0], filters={"module": "QM"})["answer"]
    )
    search = FixtureRetriever.search

    def tampered(self, *args, **kwargs):
        result = search(self, *args, **kwargs)
        for item in result:
            item["content"] += " TEST_ONLY altered"
        return result

    monkeypatch.setattr(FixtureRetriever, "search", tampered)
    result = ask(client, CASES[2][0])
    assert result["sources"] == []
    assert "Suggested support area:" not in result["answer"]


def test_no_new_chat_routes_or_persistent_assignment_state(client):
    before = {route.path for route in client.app.routes}
    first = ask(client, CASES[0][0])
    state = client.app.state.engine.diagnosis_store.get(first["session_id"])
    assert not {"department", "ticket_id", "assigned_to", "forwarded_to"}.intersection(
        state.to_dict()
    )
    assert before == {route.path for route in client.app.routes}
    assert not any("ticket" in path or "forward" in path for path in before)
    assert len(SUPPORT_AREAS) == 4
    assert "Suggested support area:" not in ask(client, "not sure")["answer"]
