"""Unit tests for the human-in-the-loop diagnostic consultant module."""

from __future__ import annotations

import unittest

from consultant.clarification_engine import ClarificationEngine, INTRO_MESSAGE
from consultant.diagnosis_manager import DiagnosisManager
from consultant.diagnosis_tree_loader import DiagnosisTreeLoader, GENERIC_TREE_ID
from consultant.intent_classifier import ISSUE_DIAGNOSIS, IntentClassifier
from consultant.response_builder import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_messages
from consultant.session_state import DiagnosisSessionStore, DiagnosisState


class DiagnosisTreeLoaderTests(unittest.TestCase):
    def setUp(self):
        self.loader = DiagnosisTreeLoader()

    def test_loads_expected_trees(self):
        ids = {tree.id for tree in self.loader.list_trees()}
        self.assertIn("po_release", ids)
        self.assertIn(GENERIC_TREE_ID, ids)

    def test_get_tree(self):
        tree = self.loader.get_tree("po_release")
        self.assertIsNotNone(tree)
        self.assertEqual(tree.intent, "Purchase Order Release")
        self.assertIn("transaction", tree.required_fields)

    def test_match_po_release(self):
        tree = self.loader.match_tree("My Purchase Order is not releasing")
        self.assertEqual(tree.id, "po_release")

    def test_match_fallback_generic(self):
        tree = self.loader.match_tree("Something weird happened in the system today")
        self.assertEqual(tree.id, GENERIC_TREE_ID)

    def test_required_fields_have_questions(self):
        for tree in self.loader.list_trees():
            for field_name in tree.required_fields:
                self.assertIn(field_name, tree.questions)


class IntentClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = IntentClassifier(use_llm=False)

    def test_tcode_explanation(self):
        result = self.classifier.classify("Explain ME21N")
        self.assertEqual(result["intent"], "T-Code Explanation")
        self.assertEqual(result["source"], "rules")

    def test_table_explanation(self):
        result = self.classifier.classify("What is VBAK?")
        self.assertEqual(result["intent"], "SAP Table Explanation")

    def test_issue_diagnosis(self):
        result = self.classifier.classify("My Purchase Order is not releasing.")
        self.assertEqual(result["intent"], ISSUE_DIAGNOSIS)

    def test_business_process(self):
        result = self.classifier.classify("How do I create a Purchase Order?")
        self.assertEqual(result["intent"], "Business Process")


class ClarificationEngineTests(unittest.TestCase):
    def setUp(self):
        self.loader = DiagnosisTreeLoader()
        self.engine = ClarificationEngine()
        self.tree = self.loader.get_tree("po_release")

    def test_asks_one_question_at_a_time_without_duplicates(self):
        state = DiagnosisState()
        asked = []

        for _ in range(len(self.tree.required_fields)):
            question = self.engine.ask_next(self.tree, state)
            self.assertIsNotNone(question)
            field = state.pending_field
            self.assertNotIn(field, asked)
            asked.append(field)
            self.engine.apply_user_answer(state, f"answer-for-{field}")

        self.assertTrue(self.engine.is_complete(self.tree, state))
        self.assertIsNone(self.engine.ask_next(self.tree, state))
        self.assertEqual(asked, list(self.tree.required_fields))

    def test_intro_only_on_first_question(self):
        state = DiagnosisState()
        first = self.engine.ask_next(self.tree, state)
        self.assertIn(INTRO_MESSAGE, first)
        self.engine.apply_user_answer(state, "ME29N")
        second = self.engine.ask_next(self.tree, state)
        self.assertNotIn(INTRO_MESSAGE, second)


class DiagnosisManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = DiagnosisManager(
            intent_classifier=IntentClassifier(use_llm=False),
            tree_loader=DiagnosisTreeLoader(),
            session_store=DiagnosisSessionStore(),
        )

    def test_direct_for_tcode_lookup(self):
        result = self.manager.handle_turn("s1", "Explain ME21N")
        self.assertEqual(result.mode, "direct")
        self.assertEqual(result.intent, "T-Code Explanation")

    def test_direct_for_table_lookup(self):
        result = self.manager.handle_turn("s1", "What is VBAK?")
        self.assertEqual(result.mode, "direct")
        self.assertEqual(result.intent, "SAP Table Explanation")

    def test_clarification_loop_then_diagnose(self):
        session_id = "po-session"
        first = self.manager.handle_turn(session_id, "My Purchase Order is not releasing.")
        self.assertEqual(first.mode, "clarify")
        self.assertEqual(first.phase, "clarifying")
        self.assertIn(INTRO_MESSAGE, first.message or "")

        answers = {
            "transaction": "ME29N",
            "error_message": "Release strategy not found",
            "release_group": "02",
            "release_code": "03",
        }
        tree = self.manager.tree_loader.get_tree("po_release")
        result = first
        for field_name in tree.required_fields:
            self.assertEqual(result.mode, "clarify")
            result = self.manager.handle_turn(session_id, answers[field_name])

        self.assertEqual(result.mode, "diagnose")
        self.assertEqual(result.phase, "diagnosing")
        self.assertIn("ME29N", result.enriched_query)
        self.assertIn("Release strategy not found", result.enriched_query)
        self.assertIn("02", result.enriched_query)
        self.assertIn("03", result.enriched_query)
        self.assertEqual(result.answers["transaction"], "ME29N")

    def test_never_asks_same_field_twice(self):
        session_id = "dup-session"
        self.manager.handle_turn(session_id, "PO is not releasing")
        state = self.manager.session_store.get(session_id)
        first_field = state.pending_field
        self.manager.handle_turn(session_id, "ME29N")
        state = self.manager.session_store.get(session_id)
        self.assertNotEqual(state.pending_field, first_field)
        self.assertIn(first_field, state.answers)

    def test_enriched_query_composition(self):
        tree = self.manager.tree_loader.get_tree("po_release")
        state = DiagnosisState(
            intent=tree.intent,
            tree_id=tree.id,
            answers={
                "transaction": "ME29N",
                "error_message": "Release strategy not found",
                "release_group": "02",
                "release_code": "03",
            },
        )
        enriched = self.manager.build_enriched_query(tree, state)
        self.assertIn("Purchase Order", enriched)
        self.assertIn("Release Strategy", enriched)
        self.assertIn("Transaction: ME29N", enriched)
        self.assertIn("Release Group: 02", enriched)


class ResponseBuilderTests(unittest.TestCase):
    def test_build_diagnosis_messages(self):
        messages = build_diagnosis_messages(
            enriched_query="Purchase Order\nTransaction: ME29N",
            context="Release strategy not found — maintain SPRO",
            answers={"transaction": "ME29N"},
            history=[{"role": "user", "content": "help"}],
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], DIAGNOSIS_SYSTEM_PROMPT)
        self.assertIn("Diagnosis", DIAGNOSIS_SYSTEM_PROMPT)
        self.assertIn("Confidence Score", DIAGNOSIS_SYSTEM_PROMPT)
        joined = "\n".join(m["content"] for m in messages)
        self.assertIn("ME29N", joined)
        self.assertIn("Release strategy not found", joined)


class DiagnosisSessionStoreTests(unittest.TestCase):
    def test_clear_resets_state(self):
        store = DiagnosisSessionStore()
        state = store.get_or_create("abc")
        state.intent = "Purchase Order Release"
        state.status = "collecting"
        state.answers["transaction"] = "ME29N"
        self.assertTrue(store.clear("abc"))
        refreshed = store.get("abc")
        self.assertEqual(refreshed.status, "idle")
        self.assertEqual(refreshed.answers, {})


if __name__ == "__main__":
    unittest.main()
