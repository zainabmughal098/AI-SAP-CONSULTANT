"""Offline regressions using real SDK imports and mocked external service calls."""

from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import httpx
import pytest
from groq import APITimeoutError, AuthenticationError, RateLimitError

from consultant.diagnosis_manager import DiagnosisManager
from consultant.intent_classifier import IntentClassifier
from rag.config.settings import AppSettings
from rag.consultant import SAPConsultant
from rag.errors import ConsultantError
from rag.generation.generator import ResponseGenerator


@pytest.fixture
def settings():
    return AppSettings(
        pinecone_api_key="AUDIT_DUMMY", pinecone_index_name="AUDIT_DUMMY",
        groq_api_key="AUDIT_DUMMY",
    )


@pytest.fixture
def generator(settings):
    with patch("rag.generation.generator.Groq") as client:
        result = ResponseGenerator(settings)
        client.assert_called_once_with(api_key="AUDIT_DUMMY", timeout=30.0, max_retries=0)
        return result


def completion(text="Supported answer", finish="stop"):
    return NS(choices=[NS(message=NS(content=text), finish_reason=finish)], usage=None)


def chunk(text=None, finish=None):
    return NS(choices=[NS(delta=NS(content=text), finish_reason=finish)])


def fake_stream(generator, chunks):
    stream = Mock()
    stream.__iter__ = Mock(return_value=iter(chunks))
    generator.client.chat.completions.create.return_value = stream
    return stream


@pytest.mark.parametrize("finish", ["length", None, "content_filter", "tool_calls"])
def test_nonstream_rejects_unfinished_or_unusable_answer(generator, finish):
    generator.client.chat.completions.create.return_value = completion(finish=finish)
    with pytest.raises(ConsultantError) as error:
        generator.generate("Explain ME21N", "Synthetic context")
    assert error.value.code == "incomplete_response"


@pytest.mark.parametrize("text", [None, "", "   "])
def test_nonstream_rejects_empty_answer(generator, text):
    generator.client.chat.completions.create.return_value = completion(text=text)
    with pytest.raises(ConsultantError) as error:
        generator.generate("Explain ME21N", "Synthetic context")
    assert error.value.code == "empty_response"


def test_nonstream_accepts_completed_answer(generator):
    generator.client.chat.completions.create.return_value = completion()
    assert generator.generate("Explain ME21N", "Synthetic context")["answer"] == "Supported answer"


@pytest.mark.parametrize("finish", ["length", None, "content_filter"])
def test_stream_rejects_truncation_and_missing_finish(generator, finish):
    stream = fake_stream(generator, [chunk("Partial answer"), chunk(finish=finish)])
    output = generator.stream("Explain ME21N", "Synthetic context")
    assert next(output) == "Partial answer"
    with pytest.raises(ConsultantError) as error:
        list(output)
    assert error.value.code == "incomplete_response"
    stream.close.assert_called_once()


def test_stream_accepts_stop_and_usage_only_chunk(generator):
    stream = fake_stream(generator, [chunk("Supported answer"), chunk(finish="stop"), NS(choices=[])])
    assert list(generator.stream("Explain ME21N", "Synthetic context")) == ["Supported answer"]
    stream.close.assert_called_once()


def test_stream_stop_without_text_is_not_success(generator):
    fake_stream(generator, [chunk(finish="stop")])
    with pytest.raises(ConsultantError) as error:
        list(generator.stream("Explain ME21N", "Synthetic context"))
    assert error.value.code == "empty_response"


def test_disconnected_stream_is_closed(generator):
    stream = fake_stream(generator, [chunk("First token"), chunk(finish="stop")])
    output = generator.stream("Explain ME21N", "Synthetic context")
    next(output)
    output.close()
    stream.close.assert_called_once()


def provider_exception(kind):
    request = httpx.Request("POST", "https://example.invalid")
    if kind == "timeout":
        return APITimeoutError(request=request)
    status = 429 if kind == "quota" else 401
    cls = RateLimitError if kind == "quota" else AuthenticationError
    return cls("PRIVATE_PROVIDER_DETAILS", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize("kind,code,status", [
    ("quota", "rate_limited", 429),
    ("auth", "provider_configuration_error", 503),
    ("timeout", "provider_timeout", 504),
])
@pytest.mark.parametrize("streaming", [False, True])
def test_provider_failures_are_sanitized(generator, kind, code, status, streaming):
    generator.client.chat.completions.create.side_effect = provider_exception(kind)
    with pytest.raises(ConsultantError) as error:
        if streaming:
            list(generator.stream("Explain ME21N", "Synthetic context"))
        else:
            generator.generate("Explain ME21N", "Synthetic context")
    assert error.value.code == code
    assert error.value.status_code == status
    assert "PRIVATE_PROVIDER_DETAILS" not in str(error.value)


def test_midstream_exception_is_sanitized_and_closed(generator):
    def interrupted():
        yield chunk("Partial")
        raise RuntimeError("PRIVATE_PROVIDER_DETAILS")

    stream = fake_stream(generator, [])
    stream.__iter__ = Mock(return_value=interrupted())
    output = generator.stream("Explain ME21N", "Synthetic context")
    assert next(output) == "Partial"
    with pytest.raises(ConsultantError, match="temporarily unavailable"):
        list(output)
    stream.close.assert_called_once()


@pytest.fixture
def consultant(settings):
    # Real orchestration and diagnosis logic; the retriever and generator are test doubles.
    with patch("rag.consultant.SemanticRetriever") as retriever, patch("rag.consultant.ResponseGenerator"):
        from rag.retriever.query_processor import QueryProcessor

        retriever.return_value.query_processor = QueryProcessor()
        retriever.return_value.retrieve.return_value = {
            "results": [], "context": "Synthetic context", "context_size": 17,
        }
        return SAPConsultant(
            settings=settings,
            diagnosis_manager=DiagnosisManager(intent_classifier=IntentClassifier(use_llm=False)),
        )


@pytest.mark.parametrize("streaming", [False, True])
def test_generation_failure_does_not_pollute_memory(consultant, streaming):
    if streaming:
        def interrupted(**kwargs):
            yield "Partial answer"
            raise RuntimeError("PRIVATE_PROVIDER_DETAILS")
        consultant.generator.stream.side_effect = interrupted
        events = list(consultant.ask_stream("Explain ME21N"))
        assert events[-1]["type"] == "error"
        assert not any(event["type"] == "done" for event in events)
        payload = events[-1]
    else:
        consultant.generator.generate.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAILS")
        payload = consultant.ask("Explain ME21N")
        assert payload["http_status"] == 503
    assert payload["complete"] is False
    assert "PRIVATE_PROVIDER_DETAILS" not in str(payload)
    assert consultant.memory.get_messages() == []


@pytest.mark.parametrize("streaming", [False, True])
def test_retrieval_failure_does_not_leak_details_or_call_llm(consultant, streaming):
    consultant.retriever.retrieve.return_value = {"error": "PRIVATE_PROVIDER_DETAILS", "results": []}
    payload = list(consultant.ask_stream("Explain ME21N"))[-1] if streaming else consultant.ask("Explain ME21N")
    assert payload["error_code"] == "retrieval_unavailable"
    assert "PRIVATE_PROVIDER_DETAILS" not in str(payload)
    consultant.generator.generate.assert_not_called()
    consultant.generator.stream.assert_not_called()


@pytest.mark.parametrize("streaming", [False, True])
def test_failed_final_clarification_can_be_retried(consultant, streaming):
    ask = (lambda q: list(consultant.ask_stream(q))[-1]) if streaming else consultant.ask
    for q in ["My Purchase Order is not releasing", "ME29N", "Synthetic error", "DEMO_GROUP"]:
        ask(q)
    before = consultant.memory.get_messages()
    if streaming:
        consultant.generator.stream.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAILS")
    else:
        consultant.generator.generate.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAILS")
    failed = ask("DEMO_CODE")
    assert failed["complete"] is False
    state = consultant.diagnosis_store.get(consultant.memory.session_id)
    assert state.pending_field == "release_code"
    assert state.answers["release_group"] == "DEMO_GROUP"
    assert consultant.memory.get_messages() == before
    consultant.generator.generate.side_effect = None
    consultant.generator.generate.return_value = {"answer": "Supported diagnosis"}
    consultant.generator.stream.side_effect = None
    consultant.generator.stream.return_value = iter(["Supported diagnosis"])
    success = ask("DEMO_CODE")
    assert success["answer"] == "Supported diagnosis"
    assert len(consultant.memory.get_messages()) == len(before) + 2


@pytest.mark.parametrize("streaming", [False, True])
def test_whitespace_is_a_controlled_validation_failure(consultant, streaming):
    payload = list(consultant.ask_stream("   "))[-1] if streaming else consultant.ask("   ")
    assert payload["error_code"] == "invalid_query"
    assert payload["retryable"] is False
    assert consultant.memory.get_messages() == []


@pytest.fixture
def api_client(settings, consultant, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    with patch.object(AppSettings, "from_env", return_value=settings), patch("rag.consultant.ResponseGenerator"):
        api = importlib.import_module("api.main")
    monkeypatch.setattr(api, "get_active_consultant", lambda session_id: consultant)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        yield client, api


@pytest.mark.parametrize("streaming", [False, True])
def test_http_route_provider_failure_has_public_error_contract(api_client, consultant, streaming):
    client, _ = api_client
    if streaming:
        consultant.generator.stream.side_effect = provider_exception("quota")
    else:
        consultant.generator.generate.side_effect = provider_exception("quota")
    response = client.post("/chat/stream" if streaming else "/chat", json={"query": "Explain ME21N"})
    assert "PRIVATE_PROVIDER_DETAILS" not in response.text
    if streaming:
        import json

        assert response.status_code == 200  # SSE headers precede provider work.
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "error"
        assert not any(e["type"] == "done" for e in events)
        payload = events[-1]
    else:
        assert response.status_code == 429
        payload = response.json()
    assert payload["error_code"] == "rate_limited"
    assert payload["complete"] is False
    assert payload["retryable"] is True


def test_http_retrieval_failure_is_not_success(api_client, consultant):
    client, _ = api_client
    consultant.retriever.retrieve.return_value = {"error": "PRIVATE_PROVIDER_DETAILS"}
    response = client.post("/chat", json={"query": "Explain ME21N"})
    assert response.status_code == 503
    assert response.json()["error_code"] == "retrieval_unavailable"
    assert "PRIVATE_PROVIDER_DETAILS" not in response.text


def test_http_success_contract_preserves_existing_answer_fields(api_client, consultant):
    client, _ = api_client
    consultant.generator.generate.return_value = {"answer": "Supported answer", "model": "mock"}
    response = client.post("/chat", json={"query": "Explain ME21N"})
    assert response.status_code == 200
    assert response.json()["complete"] is True
    assert response.json()["answer"] == "Supported answer"
    assert response.json()["history_length"] == 2


def test_unexpected_route_setup_error_is_sanitized(api_client, monkeypatch):
    client, api = api_client

    def broken(session_id):
        raise RuntimeError("PRIVATE_PROVIDER_DETAILS")

    monkeypatch.setattr(api, "get_active_consultant", broken)
    response = client.post("/chat/stream", json={"query": "Explain ME21N"})
    assert response.status_code == 503
    assert "PRIVATE_PROVIDER_DETAILS" not in response.text
    assert response.json()["complete"] is False


def test_unexpected_stream_failure_has_terminal_error(api_client, consultant):
    import json

    client, _ = api_client

    def broken(**kwargs):
        yield {"type": "session", "session_id": "synthetic"}
        raise RuntimeError("PRIVATE_PROVIDER_DETAILS")

    consultant.ask_stream = broken
    response = client.post("/chat/stream", json={"query": "Explain ME21N"})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "error"
    assert "PRIVATE_PROVIDER_DETAILS" not in response.text


def test_http_whitespace_returns_bad_request(api_client):
    client, _ = api_client
    response = client.post("/chat", json={"query": "   "})
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_query"


@pytest.mark.parametrize("streaming", [False, True])
def test_truncation_reaches_request_boundary_without_committing_history(consultant, generator, streaming):
    consultant.generator = generator
    if streaming:
        fake_stream(generator, [chunk("Partial"), chunk(finish="length")])
        payload = list(consultant.ask_stream("Explain ME21N"))[-1]
        assert payload["type"] == "error"
    else:
        generator.client.chat.completions.create.return_value = completion("Partial", finish="length")
        payload = consultant.ask("Explain ME21N")
        assert payload["http_status"] == 502
    assert payload["error_code"] == "incomplete_response"
    assert consultant.memory.get_messages() == []


def test_real_retriever_sanitizes_failure_result_and_logs(settings, caplog):
    from rag.retriever.retriever import SemanticRetriever

    retriever = SemanticRetriever(settings)
    with patch.object(retriever.query_processor, "embed_query", side_effect=RuntimeError("PRIVATE_PROVIDER_DETAILS")):
        result = retriever.retrieve("Explain ME21N")
    assert result["error"]
    assert "PRIVATE_PROVIDER_DETAILS" not in str(result)
    assert "PRIVATE_PROVIDER_DETAILS" not in caplog.text


@pytest.mark.parametrize("close_after_done", [False, True])
def test_stream_cancellation_rolls_back_only_unfinished_diagnosis(consultant, close_after_done):
    for q in ["My Purchase Order is not releasing", "ME29N", "Synthetic error", "DEMO_GROUP"]:
        list(consultant.ask_stream(q))
    before = consultant.memory.get_messages()
    consultant.generator.stream.return_value = iter(["Supported diagnosis"])
    events = consultant.ask_stream("DEMO_CODE")
    for event in events:
        if event["type"] == ("done" if close_after_done else "token"):
            events.close()
            break
    state = consultant.diagnosis_store.get(consultant.memory.session_id)
    if close_after_done:
        assert state.status == "idle"
        assert len(consultant.memory.get_messages()) == len(before) + 2
    else:
        assert state.pending_field == "release_code"
        assert consultant.memory.get_messages() == before
