"""Characterize production/demo differences without real provider operations.

These reproduce failure boundaries; they do not implement or approve a deployment
mode change, nor identify which exception occurred on Vercel.
"""

import json
import urllib.error
from io import BytesIO
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import install_routes
from consultant.diagnosis_manager import DiagnosisManager
from consultant.intent_classifier import IntentClassifier
from offline_demo.application import create_app
from offline_demo.tcode_references import REFERENCES
from rag.config.settings import AppSettings
from rag.consultant import SAPConsultant
from rag.evidence import INSUFFICIENT

QUESTIONS = [
    "What is ME21N used for in SAP?",
    "What is the difference between ME21N and ME23N?",
]
SEARCH_ERROR = "The knowledge search is temporarily unavailable. Please retry."


@pytest.fixture
def production(monkeypatch):
    settings = AppSettings(
        pinecone_api_key="TEST_ONLY",
        pinecone_index_name="TEST_ONLY",
        groq_api_key="TEST_ONLY",
        embedding_api_url="https://example.invalid/TEST_ONLY",
    )
    generator = Mock()
    monkeypatch.setattr("rag.consultant.ResponseGenerator", lambda **kw: generator)
    engine = SAPConsultant(
        settings=settings,
        diagnosis_manager=DiagnosisManager(
            intent_classifier=IntentClassifier(use_llm=False)
        ),
    )
    engine.retriever.pinecone_client.query = Mock(return_value={"matches": []})
    app = FastAPI()
    install_routes(app, lambda session_id: engine, engine)
    with TestClient(app) as client:
        yield client, engine, generator


def response_payload(client, query, streaming):
    response = client.post(
        "/chat/stream" if streaming else "/chat", json={"query": query}
    )
    if streaming:
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        return response, events[-1], events
    return response, response.json(), []


@pytest.mark.parametrize("query", QUESTIONS)
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "fault", ["embedding_http_error", "embedding_matrix", "pinecone_error"]
)
def test_distinct_retrieval_failures_have_same_reported_message(
    production, monkeypatch, query, streaming, fault
):
    client, engine, generator = production
    if fault == "embedding_http_error":
        sender = Mock(
            side_effect=urllib.error.HTTPError(
                "https://example.invalid/TEST_ONLY", 410, "TEST_ONLY", None, None
            )
        )
    else:
        vector = [1.0] * 384
        payload = [vector] if fault == "embedding_matrix" else vector
        sender = Mock(return_value=BytesIO(json.dumps(payload).encode()))
    monkeypatch.setattr("rag.retriever.query_processor.urllib.request.urlopen", sender)
    if fault == "pinecone_error":
        engine.retriever.pinecone_client.query.side_effect = RuntimeError(
            "TEST_ONLY_PRIVATE_DETAIL"
        )
    response, result, events = response_payload(client, query, streaming)
    assert result["error_code"] == "retrieval_unavailable"
    assert result["complete"] is False
    assert result.get("message", result.get("answer")) == SEARCH_ERROR
    assert "TEST_ONLY_PRIVATE_DETAIL" not in response.text
    assert response.status_code == (200 if streaming else 503)
    if streaming:
        assert result["type"] == "error"
        assert not any(e["type"] == "done" for e in events)
    if fault != "pinecone_error":
        engine.retriever.pinecone_client.query.assert_not_called()
    generator.generate.assert_not_called()
    generator.stream.assert_not_called()
    assert engine.memory.get_messages() == []


@pytest.mark.parametrize("query", QUESTIONS)
@pytest.mark.parametrize("streaming", [False, True])
def test_successful_search_still_does_not_admit_demo_references_to_production(
    production, monkeypatch, query, streaming
):
    client, engine, generator = production
    monkeypatch.setattr(
        engine.retriever.query_processor, "embed_query", lambda query: [1.0] * 384
    )
    record = REFERENCES["ME21N"]
    engine.retriever.pinecone_client.query.return_value = {
        "matches": [
            {
                "id": record["id"],
                "score": 0.99,
                "metadata": {**record["metadata"], "text": record["content"]},
            }
        ]
    }
    response, result, _ = response_payload(client, query, streaming)
    assert response.status_code == 200
    assert result["complete"] is True
    assert result["answer"] == INSUFFICIENT
    assert result["sources"] == []
    assert engine.retriever.source_policy.entries == {}
    generator.generate.assert_not_called()
    generator.stream.assert_not_called()


@pytest.mark.parametrize("query", QUESTIONS)
def test_same_question_has_cited_offline_reference_without_provider_bootstrap(
    monkeypatch, query
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Provider-backed bootstrap must not run")

    monkeypatch.setattr(AppSettings, "from_env", forbidden)
    monkeypatch.setattr("rag.consultant.SemanticRetriever", forbidden)
    monkeypatch.setattr("rag.consultant.ResponseGenerator", forbidden)
    with TestClient(create_app()) as client:
        result = client.post("/chat", json={"query": query}).json()
        assert result["complete"] is True
        assert result["sources"][0]["id"] == "DEMO-REFERENCE-ME21N"
        assert "create a purchase order" in result["answer"]
        assert "[SRC-" in result["answer"]
