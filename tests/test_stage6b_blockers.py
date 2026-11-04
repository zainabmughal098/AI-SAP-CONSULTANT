"""Real rule-only parsing/orchestration; fictional fixtures, no provider calls."""

import json
from pathlib import Path

import pytest

from consultant.clarification_engine import ClarificationEngine
from consultant.diagnosis_manager import DiagnosisManager
from consultant.intent_classifier import IntentClassifier
from consultant.message_parser import extract_details, is_unknown
from consultant.session_state import DiagnosisState


def manager():
    return DiagnosisManager(intent_classifier=IntentClassifier(use_llm=False))


@pytest.mark.parametrize(
    "text",
    [
        "I don't know the configured tolerance",
        "I do not know the company code",
        "No authorization trace is available",
        "No SU53 output is provided",
        "There is no real SAP error number",
        "I don't know the authorization object",
        "Company code is not supplied",
        "No authorization object was provided",
    ],
)
def test_absence_cannot_be_extracted_as_a_value(text):
    assert is_unknown(text)
    assert (
        extract_details(
            text, ("transaction", "error_message", "company_code", "su53_object")
        ).values
        == {}
    )


@pytest.mark.parametrize(
    "pending,text,unknown",
    [
        ("company_code", "I don't know the configured tolerance", False),
        ("company_code", "I do not know the company code", True),
        ("su53_object", "No authorization trace is available", True),
        ("su53_object", "No SU53 output is provided", True),
        ("error_message", "There is no real SAP error number", True),
        ("company_code", "I don't know", True),
        ("user_id", "No authorization trace is available", False),
        ("company_code", "No authorization trace is available", False),
    ],
)
def test_shared_clarification_scopes_unavailable_information(pending, text, unknown):
    state = DiagnosisState(pending_field=pending)
    ClarificationEngine().apply_user_answer(state, text)
    assert not state.answers
    assert (pending in state.unknown_fields) is unknown


@pytest.mark.parametrize("field", ["company_code", "su53_object", "account", "user_id"])
def test_arbitrary_sentence_does_not_fill_identifier(field):
    state = DiagnosisState(pending_field=field)
    ClarificationEngine().apply_user_answer(
        state, "A fictional detail has not been supplied"
    )
    assert not state.answers


@pytest.mark.parametrize(
    "field,value",
    [
        ("company_code", "1000"),
        ("su53_object", "DEMO_OBJECT_A"),
        ("user_id", "DEMO_USER_A (fictional)"),
    ],
)
def test_supplied_identifiers_remain_user_reports(field, value):
    state = DiagnosisState(pending_field=field)
    ClarificationEngine().apply_user_answer(state, value)
    assert state.answers[field] == value


def test_invoice_symptom_correction_and_unrelated_tolerance_do_not_supply_company():
    dm = manager()
    dm.handle_turn("demo", "DEMO invoice DEMO_INV_003 has a problem in MIRO.")
    dm.handle_turn("demo", "SIMULATED: invoice needs review")
    corrected = "Actually it posted in the fictional scenario, but payment is blocked"
    result = dm.handle_turn("demo", corrected)
    assert result.preliminary
    assert corrected in result.enriched_query
    assert "invoice needs review" not in result.enriched_query
    assert "Account Determination" not in result.enriched_query
    assert "Invoice Posting Error" not in result.enriched_query
    unavailable = dm.handle_turn("demo", "I don't know the configured tolerance")
    assert unavailable.mode == "diagnose" and unavailable.preliminary
    assert corrected in unavailable.enriched_query
    state = dm.session_store.get("demo")
    assert state.answers == {"transaction": "MIRO"}
    assert state.opening_message == corrected
    assert "error_message" in state.unknown_fields
    assert "company_code" not in state.unknown_fields  # tolerance is a different field
    dm.mark_completed("demo")
    followup = dm.handle_turn("demo", "What should I check next?")
    assert corrected in followup.enriched_query
    assert "Account Determination" not in followup.enriched_query
    dm.clear_session("demo")
    assert not state.symptom_corrected


def test_unrelated_unknown_while_collecting_is_not_assigned_to_pending_field():
    dm = manager()
    dm.handle_turn("demo", "My DEMO invoice fails in MIRO")
    dm.handle_turn("demo", "SIMULATED: review pending")
    result = dm.handle_turn("demo", "I don't know the configured tolerance")
    state = dm.session_store.get("demo")
    assert result.mode == "clarify"
    assert state.pending_field == "company_code"
    assert "company_code" not in state.answers
    assert "company_code" not in state.unknown_fields


def test_exact_authorization_script_stays_preliminary_without_trace():
    dm = manager()
    for text in [
        "In a DEMO scenario I am not authorized to change DEMO_PO_001 in ME22N.",
        "SIMULATED: requested activity denied",
        "DEMO_USER_A (fictional)",
        "No authorization trace is available",
    ]:
        result = dm.handle_turn("demo", text)
    assert result.mode == "diagnose" and result.preliminary
    assert "su53_object" in result.unknown_fields
    assert "su53_object" not in result.answers
    assert "SU53: No authorization" not in result.enriched_query


@pytest.mark.parametrize(
    "opening,tree",
    [
        (
            "DEMO goods receipt for DEMO_PO_002 fails in MIGO; material DEMO_MAT_BOLT_A.",
            "goods_receipt",
        ),
        ("DEMO sales order DEMO_SO_004 is not visible in VA03.", "sales_order"),
    ],
)
def test_demo_incident_openings_seed_canonical_state(opening, tree):
    dm = manager()
    result = dm.handle_turn("demo", opening)
    assert result.mode == "clarify"
    assert result.tree_id == tree
    assert result.answers["transaction"] in {"MIGO", "VA03"}
    assert dm.session_store.get("demo").opening_message == opening
    expected = (
        {"po_number": "DEMO_PO_002", "material": "DEMO_MAT_BOLT_A"}
        if tree == "goods_receipt"
        else {"order_number": "DEMO_SO_004"}
    )
    assert expected.items() <= result.answers.items()


@pytest.mark.parametrize(
    "text",
    [
        "Company code is a fictional placeholder",
        "Authorization object is a missing detail",
    ],
)
def test_labeled_prose_is_not_truncated_into_an_identifier(text):
    assert not extract_details(text, ("company_code", "su53_object")).values


def test_mixed_unknown_and_supplied_field_remain_separate():
    details = extract_details(
        "I don't know the company code; transaction is MIRO",
        ("company_code", "transaction"),
    )
    assert details.values == {"transaction": "MIRO"}
    assert "company_code" in details.unknown


@pytest.mark.parametrize(
    "query",
    [
        "Explain goods receipt failures",
        "What does not visible mean?",
        "Explain MIGO",
        "What is error M7 021?",
    ],
)
def test_information_requests_still_do_not_start_incidents(query):
    assert manager().handle_turn("demo", query).mode == "direct"


def test_sales_correction_unknown_and_topic_switch():
    dm = manager()
    for text in [
        "DEMO sales order DEMO_SO_004 is not visible in VA03.",
        "SIMULATED: document is not shown",
        "Actually transaction is VA02",
        "I do not know the sales area",
    ]:
        dm.handle_turn("demo", text)
    state = dm.session_store.get("demo")
    assert state.answers["transaction"] == "VA02"
    assert "sales_area" not in state.answers
    assert "sales_area" in state.unknown_fields
    assert dm.handle_turn("demo", "Explain VA01 instead").mode == "direct"
    assert not state.answers and state.tree_id is None


def test_all_original_scenario_turns_replay_without_live_services():
    scenarios = json.loads(
        (Path(__file__).resolve().parents[1] / "demo_corpus/scenarios.json").read_text(
            encoding="utf-8"
        )
    )["scenarios"]
    for scenario in scenarios:
        dm = manager()
        for text in [scenario["opening_question"], *scenario["user_replies"]]:
            result = dm.handle_turn("demo", text)
            assert result.mode in {"direct", "clarify", "diagnose"}
        assert all(
            not is_unknown(value)
            for value in dm.session_store.get("demo").answers.values()
        )
