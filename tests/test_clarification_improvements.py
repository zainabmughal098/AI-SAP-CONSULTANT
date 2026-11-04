"""Stage 2 regressions: real routing/state logic, no live service calls."""

from unittest.mock import patch

import pytest

from consultant.diagnosis_manager import DiagnosisManager
from consultant.diagnosis_tree_loader import DiagnosisTreeLoader
from consultant.intent_classifier import IntentClassifier
from consultant.message_parser import extract_details, is_unknown
from consultant.session_state import DiagnosisState
from rag.config.settings import AppSettings
from rag.consultant import SAPConsultant
from rag.retriever.query_processor import QueryProcessor


@pytest.fixture
def manager():
    return DiagnosisManager(intent_classifier=IntentClassifier(use_llm=False))


@pytest.mark.parametrize(
    "question,intent",
    [
        ("Explain goods issue", "Knowledge Lookup"),
        ("goods issue", "General SAP Query"),
        ("What is error M7 021?", "Knowledge Lookup"),
        ("Explain authorization errors", "Knowledge Lookup"),
        ("What is SU53?", "Authorization"),
        ("Explain PFCG", "Authorization"),
        ("What is VBAK?", "SAP Table Explanation"),
        ("Explain ME21N", "T-Code Explanation"),
        ("MIGO", "T-Code Explanation"),
        ("MIRO", "T-Code Explanation"),
        ("How to create a purchase order?", "Business Process"),
        ("How do I create a purchase order?", "Business Process"),
        ("What is SU53 and why am I not authorized?", "Issue Diagnosis"),
        ("Explain why my PO is not releasing", "Issue Diagnosis"),
        ("Why can't I create a purchase order?", "Issue Diagnosis"),
        ("My goods receipt failed in MIGO", "Issue Diagnosis"),
        ("How can I fix a purchase order release error?", "Issue Diagnosis"),
    ],
)
def test_information_vs_incident_rules(manager, question, intent):
    assert manager.intent_classifier.classify(question)["intent"] == intent


@pytest.mark.parametrize(
    "question,tree_id",
    [
        ("I cannot create a purchase order in ME21N", "generic_issue"),
        ("My purchase order is not releasing", "po_release"),
        ("Goods receipt failed for purchase order DEMO in MIGO", "goods_receipt"),
        ("MIGO goods issue failed", "generic_issue"),
        ("I am not authorized to release my purchase order in ME29N", "authorization"),
    ],
)
def test_process_appropriate_tree(manager, question, tree_id):
    assert manager.tree_loader.match_tree(question).id == tree_id


def test_all_opening_details_skip_questionnaire(manager):
    turn = manager.handle_turn(
        "demo",
        'My PO is not releasing in ME29N; error: "Synthetic symptom"; release group 02 and release code 03',
    )
    assert turn.mode == "diagnose"
    assert turn.answers == {
        "transaction": "ME29N",
        "error_message": "Synthetic symptom",
        "release_group": "02",
        "release_code": "03",
    }
    assert "Reported issue:" in turn.enriched_query
    assert turn.preliminary is False


def test_multiple_goods_receipt_details_skip_already_supplied_fields(manager):
    turn = manager.handle_turn(
        "demo", "In MIGO goods receipt failed; PO DEMO_PO; material DEMO_MAT"
    )
    assert turn.answers == {
        "transaction": "MIGO",
        "po_number": "DEMO_PO",
        "material": "DEMO_MAT",
    }
    assert manager.session_store.get("demo").pending_field == "error_message"
    turn = manager.handle_turn("demo", "Synthetic error text")
    assert turn.mode == "diagnose"


@pytest.mark.parametrize(
    "tree_id,text,expected",
    [
        (
            "sales_order",
            'transaction: VA03; error: "Synthetic symptom"; sales area: DEMO / 01 / 02; order number: DEMO_ORDER',
            {
                "sales_area": "DEMO / 01 / 02",
                "order_number": "DEMO_ORDER",
                "transaction": "VA03",
            },
        ),
        (
            "invoice_posting",
            'in MIRO; error: "Synthetic symptom"; company code: DEMO; G/L account: DEMO_ACCOUNT',
            {"transaction": "MIRO", "company_code": "DEMO", "account": "DEMO_ACCOUNT"},
        ),
        (
            "authorization",
            'in ME29N; error: "Synthetic denied message"; user ID: DEMO_USER; authorization object: DEMO_OBJECT',
            {
                "transaction": "ME29N",
                "user_id": "DEMO_USER",
                "su53_object": "DEMO_OBJECT",
            },
        ),
        (
            "delivery_creation",
            "transaction: VL01N; shipping point: DEMO; sales order number: DEMO_ORDER",
            {
                "transaction": "VL01N",
                "shipping_point": "DEMO",
                "sales_order": "DEMO_ORDER",
            },
        ),
    ],
)
def test_other_labeled_details(tree_id, text, expected):
    tree = DiagnosisTreeLoader().get_tree(tree_id)
    details = extract_details(text, tree.required_fields)
    for name, value in expected.items():
        assert details.values[name] == value


@pytest.mark.parametrize(
    "reply",
    [
        "I don't know",
        "not sure",
        "no error message",
        "I'm not sure",
        "I don’t know",
        "unknown",
        "n/a",
        "maybe 02",
        "I think 02",
    ],
)
def test_unknowns_are_not_confirmed_evidence(manager, reply):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", reply)
    assert "error_message" not in turn.answers
    state = manager.session_store.get("demo")
    assert "error_message" in state.unknown_fields
    assert state.pending_field == "release_group"


def test_unknowns_finish_as_preliminary_without_repeating_questions(manager):
    manager.handle_turn("demo", "My PO is not releasing")
    asked = []
    for reply in ["I don't know", "no error message", "not sure", "unknown"]:
        asked.append(manager.session_store.get("demo").pending_field)
        turn = manager.handle_turn("demo", reply)
    assert len(set(asked)) == 4
    assert turn.phase == "preliminary"
    assert turn.answers == {}
    assert len(turn.unknown_fields) == 4
    assert "Transaction: I don't know" not in turn.enriched_query


def test_labeled_unknown_opening_values_are_not_facts(manager):
    turn = manager.handle_turn(
        "demo",
        "My PO is not releasing; transaction: not sure; error: no error message; release group: unknown; release code: n/a",
    )
    assert turn.mode == "diagnose"
    assert turn.preliminary
    assert turn.answers == {}


def test_repeated_transaction_does_not_become_error_message(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "ME29N")
    assert "error_message" not in turn.answers
    assert "error message" in turn.message
    turn = manager.handle_turn("demo", "ME29N")
    assert "error_message" not in turn.answers
    assert "error_message" in manager.session_store.get("demo").unknown_fields


def test_side_question_does_not_fill_or_destroy_pending_field(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "What is a release group?")
    assert turn.mode == "direct"
    assert turn.include_history is False
    state = manager.session_store.get("demo")
    assert state.pending_field == "error_message"
    assert state.answers == {"transaction": "ME29N"}
    turn = manager.handle_turn("demo", "Synthetic error")
    assert turn.answers["error_message"] == "Synthetic error"
    assert state.pending_field == "release_group"


@pytest.mark.parametrize(
    "message",
    ["Explain VA01 instead", "Now explain VA01", "New question: Explain VA01"],
)
def test_explicit_topic_change_clears_old_diagnosis(manager, message):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", message)
    assert turn.mode == "direct"
    assert turn.include_history is False
    assert manager.session_store.get("demo").tree_id is None
    assert (
        turn.standalone_query == "Explain VA01"
        or turn.standalone_query == "explain VA01"
    )


def test_different_incident_starts_clean_context(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "My invoice posting failed in MIRO")
    assert turn.tree_id == "invoice_posting"
    assert turn.answers["transaction"] == "MIRO"
    assert "ME29N" not in str(manager.session_store.get("demo").to_dict())


@pytest.mark.parametrize(
    "command", ["cancel", "reset", "start over", "cancel this diagnosis"]
)
def test_cancel_does_not_become_field_evidence(manager, command):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", command)
    assert turn.phase == "answering"
    assert manager.session_store.get("demo").tree_id is None
    assert manager.session_store.get("demo").answers == {}


def test_explicit_resume_returns_pending_question_without_new_answers(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    manager.handle_turn("demo", "What is a release group?")
    turn = manager.handle_turn("demo", "resume diagnosis")
    assert turn.phase == "clarifying"
    assert "exact error" in turn.message
    assert turn.answers == {"transaction": "ME29N"}


@pytest.mark.parametrize(
    "message",
    ["Actually transaction is ME23N", "Correction: ME23N", "Use ME23N instead"],
)
def test_explicit_correction_replaces_old_detail_not_pending_answer(manager, message):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", message)
    state = manager.session_store.get("demo")
    assert turn.answers["transaction"] == "ME23N"
    assert "error_message" not in turn.answers
    assert "ME29N" not in state.opening_message
    assert state.tree_id == "po_release"


def test_contradiction_requires_confirmation_and_excludes_both_values(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "I am using ME23N")
    assert "conflicting values" in turn.message
    assert "transaction" not in turn.answers
    assert manager.session_store.get("demo").conflicts["transaction"] == [
        "ME29N",
        "ME23N",
    ]
    turn = manager.handle_turn("demo", "ME23N")
    assert turn.answers["transaction"] == "ME23N"
    assert manager.session_store.get("demo").conflicts == {}
    assert manager.session_store.get("demo").pending_field == "error_message"


def test_conflicting_values_in_opening_are_not_silently_chosen(manager):
    turn = manager.handle_turn(
        "demo", "My PO is not releasing; transaction: ME29N; transaction: ME23N"
    )
    assert "conflicting values" in turn.message
    assert "transaction" not in turn.answers


def test_uncertain_conflict_resolution_can_advance(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    manager.handle_turn("demo", "I am using ME23N")
    turn = manager.handle_turn("demo", "not sure")
    assert "transaction" not in turn.answers
    assert "transaction" in manager.session_store.get("demo").unknown_fields


def test_can_request_guidance_early_then_supply_more_details(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "Give preliminary guidance")
    assert turn.preliminary
    assert len(turn.unknown_fields) == 3
    manager.mark_completed("demo")
    turn = manager.handle_turn("demo", "release group: 02")
    assert turn.answers["release_group"] == "02"
    assert turn.answers["transaction"] == "ME29N"
    assert turn.preliminary


def test_diagnosis_context_survives_completed_response_and_history_loss(manager):
    turn = manager.handle_turn(
        "demo",
        'My PO is not releasing in ME29N; error: "Synthetic error"; release group: 02; release code: 03',
    )
    manager.mark_completed("demo")
    turn = manager.handle_turn("demo", "It still fails", history=[])
    assert turn.mode == "diagnose"
    assert "ME29N" in turn.enriched_query
    assert "Synthetic error" in turn.enriched_query
    assert "It still fails" in turn.enriched_query
    assert turn.include_history is False


def test_clear_removes_retained_context_and_unknown_values(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    manager.handle_turn("demo", "not sure")
    manager.clear_session("demo")
    state = manager.session_store.get("demo")
    assert state.opening_message == ""
    assert state.unknown_fields == {}
    assert state.answers == {}


@pytest.fixture
def engine():
    settings = AppSettings(
        pinecone_api_key="DEMO", pinecone_index_name="DEMO", groq_api_key="DEMO"
    )
    with (
        patch("rag.consultant.ResponseGenerator"),
        patch("rag.consultant.SemanticRetriever") as retriever,
    ):
        retriever.return_value.query_processor = QueryProcessor()
        retriever.return_value.retrieve.return_value = {
            "results": [
                {
                    "id": "demo",
                    "source_file": "synthetic.txt",
                    "content": "Synthetic approved check",
                    "title": "Demo reference",
                }
            ],
            "context": "Document 1: Synthetic approved check",
            "context_size": 42,
        }
        result = SAPConsultant(
            settings=settings,
            diagnosis_manager=DiagnosisManager(
                intent_classifier=IntentClassifier(use_llm=False)
            ),
        )
        result.generator.generate.return_value = {
            "answer": "Document 1 supports the synthetic check."
        }
        result.generator.stream.side_effect = lambda **kwargs: iter(
            ["Document 1 supports the synthetic check."]
        )
        return result


def ask(engine, text, streaming):
    return list(engine.ask_stream(text))[-1] if streaming else engine.ask(text)


@pytest.mark.parametrize("streaming", [False, True])
def test_preliminary_guidance_uses_sources_and_marks_missing_details(engine, streaming):
    ask(engine, "My PO is not releasing in ME29N", streaming)
    payload = ask(engine, "Give preliminary guidance", streaming)
    assert payload["phase"] == "preliminary"
    assert payload["answer"].startswith("Preliminary guidance only.")
    assert payload["sources"][0]["source_file"] == "synthetic.txt"
    generator_call = (
        engine.generator.stream.call_args
        if streaming
        else engine.generator.generate.call_args
    )
    assert generator_call.kwargs["history"] == []
    prompt = str(generator_call.kwargs["messages"])
    assert "PRELIMINARY GUIDANCE ONLY" in prompt
    assert "unavailable (not evidence)" in prompt


@pytest.mark.parametrize("streaming", [False, True])
def test_preliminary_without_retrieved_evidence_does_not_call_llm(engine, streaming):
    engine.retriever.retrieve.return_value = {
        "results": [],
        "context": "",
        "context_size": 0,
    }
    ask(engine, "My PO is not releasing in ME29N", streaming)
    payload = ask(engine, "Give preliminary guidance", streaming)
    assert "do not have enough retrieved knowledge" in payload["answer"]
    assert payload["sources"] == []
    engine.generator.generate.assert_not_called()
    engine.generator.stream.assert_not_called()


@pytest.mark.parametrize("streaming", [False, True])
def test_topic_switch_does_not_send_old_diagnosis_to_retrieval_or_generation(
    engine, streaming
):
    ask(engine, "My PO is not releasing in ME29N", streaming)
    ask(engine, "Explain VA01 instead", streaming)
    assert engine.retriever.retrieve.call_args.kwargs["query"] == "Explain VA01"
    generator_call = (
        engine.generator.stream.call_args
        if streaming
        else engine.generator.generate.call_args
    )
    assert generator_call.kwargs["history"] == []


@pytest.mark.parametrize("streaming", [False, True])
def test_corrected_context_does_not_reintroduce_superseded_values(engine, streaming):
    ask(
        engine,
        'My PO is not releasing in ME29N; error: "Synthetic error"; release group 02; release code 03',
        streaming,
    )
    payload = ask(engine, "Actually transaction is ME23N", streaming)
    assert payload["phase"] == "diagnosing"
    assert "ME29N" not in engine.retriever.retrieve.call_args.kwargs["query"]
    generator_call = (
        engine.generator.stream.call_args
        if streaming
        else engine.generator.generate.call_args
    )
    assert "ME29N" not in str(generator_call.kwargs["messages"])
    assert "ME23N" in str(generator_call.kwargs["messages"])


def test_unknowns_do_not_make_is_complete_true():
    from consultant.clarification_engine import ClarificationEngine

    state = DiagnosisState(unknown_fields={"transaction": "not sure"})
    tree = DiagnosisTreeLoader().get_tree("po_release")
    assert ClarificationEngine().is_complete(tree, state) is False
    assert is_unknown("I don't know the transaction")


def test_named_unknown_is_not_assigned_to_wrong_pending_field(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    manager.handle_turn("demo", "Synthetic error")
    manager.handle_turn("demo", "I don't know the release code")
    state = manager.session_store.get("demo")
    assert "release_code" in state.unknown_fields
    assert "release_group" not in state.unknown_fields
    assert state.pending_field == "release_group"


def test_deictic_side_question_uses_canonical_details_not_transcript(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "What is that transaction code?")
    assert turn.mode == "direct"
    assert "ME29N" in turn.standalone_query
    assert turn.include_history is False
    assert manager.session_store.get("demo").pending_field == "error_message"


def test_deictic_failure_question_preserves_diagnostic_context(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "Why is it still not working?")
    assert turn.mode == "diagnose"
    assert "ME29N" in turn.enriched_query
    assert turn.preliminary


def test_unresolved_conflict_does_not_loop_forever(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    manager.handle_turn("demo", "I am using ME23N")
    turn = manager.handle_turn("demo", "yes")
    assert "conflicting values" not in (turn.message or "")
    assert "transaction" in manager.session_store.get("demo").unknown_fields


def test_classifier_provider_failure_falls_back_without_leaking_details(caplog):
    settings = AppSettings(
        pinecone_api_key="DEMO", pinecone_index_name="DEMO", groq_api_key="DEMO"
    )
    with patch(
        "consultant.intent_classifier.Groq",
        side_effect=RuntimeError("PRIVATE_PROVIDER_DETAILS"),
    ):
        result = IntentClassifier(settings=settings).classify("A neutral SAP topic")
    assert result["intent"] == "General SAP Query"
    assert "PRIVATE_PROVIDER_DETAILS" not in caplog.text


def test_unrelated_request_is_not_recorded_as_error_message(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "Tell me a joke")
    assert turn.mode == "direct"
    assert "error_message" not in manager.session_store.get("demo").answers
    assert manager.session_store.get("demo").pending_field == "error_message"


@pytest.mark.parametrize("streaming", [False, True])
def test_stage2_preliminary_behavior_through_real_fastapi_routes(
    engine, monkeypatch, streaming
):
    import importlib
    import json

    from fastapi.testclient import TestClient

    with (
        patch.object(AppSettings, "from_env", return_value=engine.settings),
        patch("rag.consultant.ResponseGenerator"),
    ):
        api = importlib.import_module("api.main")
    monkeypatch.setattr(api, "get_active_consultant", lambda session_id: engine)
    route = "/chat/stream" if streaming else "/chat"
    with TestClient(api.app, raise_server_exceptions=False) as client:
        for question in [
            "My PO is not releasing in ME29N",
            "no error message",
            "not sure",
            "I don't know",
        ]:
            response = client.post(
                route, json={"query": question, "session_id": engine.memory.session_id}
            )
            assert response.status_code == 200
        payload = (
            [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ][-1]
            if streaming
            else response.json()
        )
    assert payload["phase"] == "preliminary"
    assert payload["complete"] is True
    assert payload["answer"].startswith("Preliminary guidance only.")
    assert payload["sources"]


@pytest.mark.parametrize("streaming", [False, True])
def test_stage1_failure_rollback_keeps_stage2_unknown_state(engine, streaming):
    for message in ["My PO is not releasing in ME29N", "no error message", "not sure"]:
        ask(engine, message, streaming)
    before = engine.diagnosis_store.get(engine.memory.session_id).to_dict()
    memory_before = engine.memory.get_messages()
    if streaming:
        engine.generator.stream.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAILS")
    else:
        engine.generator.generate.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAILS")
    payload = ask(engine, "I don't know", streaming)
    assert payload["complete"] is False
    assert "PRIVATE_PROVIDER_DETAILS" not in str(payload)
    assert engine.diagnosis_store.get(engine.memory.session_id).to_dict() == before
    assert engine.memory.get_messages() == memory_before


def test_correction_in_same_message_as_followup_is_applied_first(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "Actually transaction is ME23N; it still fails")
    assert turn.answers["transaction"] == "ME23N"
    assert "ME29N" not in turn.enriched_query


def test_guidance_request_does_not_discard_same_message_details(manager):
    manager.handle_turn("demo", "My PO is not releasing")
    turn = manager.handle_turn("demo", "transaction: ME29N; give preliminary guidance")
    assert turn.answers["transaction"] == "ME29N"
    assert turn.preliminary


def test_authorization_error_reply_is_not_mistaken_for_a_separate_incident(manager):
    manager.handle_turn("demo", "My PO is not releasing in ME29N")
    turn = manager.handle_turn("demo", "No authorization")
    assert turn.tree_id == "po_release"
    assert turn.answers["error_message"] == "No authorization"
    assert turn.answers["transaction"] == "ME29N"


def test_field_names_inside_quoted_error_are_not_separate_answers():
    details = extract_details(
        'In MIGO; error: "Check material: EXAMPLE and transaction: VA01"',
        ("transaction", "error_message", "material"),
    )
    assert details.values["transaction"] == "MIGO"
    assert (
        details.values["error_message"]
        == "Check material: EXAMPLE and transaction: VA01"
    )
    assert "material" not in details.values


def test_quoted_report_and_explicit_module_are_extracted(manager):
    turn = manager.handle_turn(
        "demo",
        'In SAP MM I cannot create a purchase order in ME21N; SAP shows "Synthetic error text"',
    )
    assert turn.answers["module"] == "MM"
    assert turn.answers["transaction"] == "ME21N"
    assert turn.answers["error_message"] == "Synthetic error text"


@pytest.mark.parametrize(
    "question",
    ['My PO is not releasing in "ME29N"', "My PO is not releasing using 'ME29N'"],
)
def test_quoted_transaction_context_is_supplied_not_missing(manager, question):
    turn = manager.handle_turn("demo", question)
    assert turn.answers["transaction"] == "ME29N"
    assert manager.session_store.get("demo").pending_field == "error_message"
