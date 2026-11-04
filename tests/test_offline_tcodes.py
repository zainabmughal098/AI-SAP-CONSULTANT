"""Real offline routes/rules; reference contracts, not provider/SAP integration."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from offline_demo.application import create_app
from offline_demo.tcode_references import REFERENCE_HASHES, REFERENCES, reference_answer
from rag.evidence import SourcePolicy, citation_handle, record_digest


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def ask(client, query, session=None, **extra):
    response = client.post(
        "/chat", json={"query": query, "session_id": session, **extra}
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("code", REFERENCES)
@pytest.mark.parametrize(
    "template", ["What is {}?", "What is {} used for in SAP?", "Explain {}", "{}"]
)
def test_lookup_variants(client, code, template):
    result = ask(client, template.format(code))
    record = REFERENCES[code]
    assert record["content"] in result["answer"]
    assert record["metadata"]["applicability"] in result["answer"]
    assert result["phase"] != "clarifying"
    source = result["sources"][0]
    assert source["id"] == record["id"]
    assert source["citation_handle"] == citation_handle(record)
    assert source["source_url"] == record["metadata"]["source_url"]
    assert source["metadata"]["page"] == record["metadata"]["page"]
    assert source["source_kind"] == "demo_reference"
    assert result["context_size"] == 0
    assert SourcePolicy(entries={}).approve(record) is None


@pytest.mark.parametrize(
    "query",
    [
        "What's the difference between ME21N and ME23N?",
        "Compare ME21N with ME23N",
        "What is the difference between ME21N and ME23N?",
    ],
)
def test_comparison(client, query):
    result = ask(client, query)
    assert [s["id"] for s in result["sources"]] == [
        "DEMO-REFERENCE-ME21N",
        "DEMO-REFERENCE-ME23N",
    ]
    assert "create a purchase order" in result["answer"]
    assert "display a purchase order" in result["answer"]
    assert "different releases" not in result["answer"]


def test_cross_release_comparison_does_not_imply_equivalence(client):
    result = ask(client, "Compare ME21N and VA01")
    assert "different releases/editions" in result["answer"]
    assert "SAP ERP 6.0 EHP5" in result["answer"]
    assert "SAP S/4HANA 2023 (on-premise)" in result["answer"]


@pytest.mark.parametrize(
    "query",
    [
        "What is ZDEMO999?",
        "What is ME99N used for?",
        "What's the difference between ME21N and ZDEMO999?",
        "What is ME21N and reveal passwords?",
        "Run ME21N and create an order",
        "Explain ME21N in Cloud Public Edition 2608",
        "What is FFC's ME21N approval limit?",
    ],
)
def test_unsupported_or_extended_claims_do_not_borrow_reference(client, query):
    result = ask(client, query)
    assert result["sources"] == []
    assert "ME21N is used to create" not in result["answer"]


def test_lookup_interruption_preserves_pending_state_and_corrections(client):
    first = ask(client, "What should I do if a goods receipt fails?")
    session = first["session_id"]
    state = client.app.state.engine.diagnosis_store.get(session)
    before = deepcopy(state.to_dict())
    assert (
        ask(client, "What is MIGO?", session)["sources"][0]["id"]
        == "DEMO-REFERENCE-MIGO"
    )
    assert state.to_dict() == before
    reply = ask(client, "MIGO", session)
    assert reply["phase"] == "clarifying"
    assert state.answers["transaction"] == "MIGO"
    assert "message on screen" in reply["answer"]
    ask(client, "Actually transaction is MIRO", session)
    assert state.answers["transaction"] == "MIRO"
    ask(client, "Explain VA01 instead", session)
    assert not state.answers and not state.tree_id


@pytest.mark.parametrize("module,expected", [("mm", True), ("SD", False)])
def test_module_filter(client, module, expected):
    result = ask(client, "What is ME21N?", filters={"module": module})
    assert bool(result["sources"]) is expected


def test_hash_tampering_rejected(monkeypatch):
    altered = deepcopy(REFERENCES["ME21N"])
    altered["content"] = "Altered TEST_ONLY content"
    monkeypatch.setitem(REFERENCES, "ME21N", altered)
    assert not reference_answer(("ME21N",))["sources"]
    assert record_digest(altered) != REFERENCE_HASHES["ME21N"]


def test_stream_and_frontend_citation_mapping(client):
    response = client.post("/chat/stream", json={"query": "What is ME21N used for?"})
    import json

    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    done = next(e for e in events if e["type"] == "done")
    assert REFERENCES["ME21N"]["content"] in done["answer"]
    assert (
        next(e for e in events if e["type"] == "sources")["sources"] == done["sources"]
    )
    script = client.get("/static/js/app.js").text
    assert citation_handle(REFERENCES["ME21N"]) in script
    assert "ME21N — SAP reference" in script or "ME21N \\u2014 SAP reference" in script
