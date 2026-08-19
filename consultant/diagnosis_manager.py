"""Orchestrate intent classification, clarification, and enriched diagnosis queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from consultant.clarification_engine import ClarificationEngine
from consultant.diagnosis_tree_loader import DiagnosisTree, DiagnosisTreeLoader, get_default_loader
from consultant.intent_classifier import ISSUE_DIAGNOSIS, IntentClassifier
from consultant.session_state import DiagnosisSessionStore, DiagnosisState
from rag.config.settings import AppSettings

TurnMode = Literal["clarify", "diagnose", "direct"]


@dataclass
class TurnResult:
    mode: TurnMode
    intent: str
    message: str | None = None
    enriched_query: str | None = None
    answers: dict[str, str] = field(default_factory=dict)
    tree_id: str | None = None
    phase: str = "answering"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "intent": self.intent,
            "message": self.message,
            "enriched_query": self.enriched_query,
            "answers": dict(self.answers),
            "tree_id": self.tree_id,
            "phase": self.phase,
        }


@dataclass
class DiagnosisManager:
    """Single entry point used by SAPConsultant before retrieval."""

    settings: AppSettings | None = None
    session_store: DiagnosisSessionStore = field(default_factory=DiagnosisSessionStore)
    tree_loader: DiagnosisTreeLoader | None = None
    intent_classifier: IntentClassifier | None = None
    clarification: ClarificationEngine = field(default_factory=ClarificationEngine)

    def __post_init__(self) -> None:
        if self.tree_loader is None:
            self.tree_loader = get_default_loader()
        if self.intent_classifier is None:
            self.intent_classifier = IntentClassifier(settings=self.settings)

    def handle_turn(
        self,
        session_id: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> TurnResult:
        del history  # Reserved for future context-aware classification
        state = self.session_store.get_or_create(session_id)

        # Continue an active clarification flow without re-classifying intent
        if state.status == "collecting" and state.tree_id and state.pending_field:
            return self._continue_collection(state, user_message)

        classification = self.intent_classifier.classify(user_message)
        intent = classification["intent"]

        if intent != ISSUE_DIAGNOSIS:
            if state.status not in ("idle", "completed"):
                state.reset()
            return TurnResult(
                mode="direct",
                intent=intent,
                phase="answering",
            )

        return self._start_or_resume_diagnosis(state, user_message, intent)

    def _start_or_resume_diagnosis(
        self,
        state: DiagnosisState,
        user_message: str,
        intent: str,
    ) -> TurnResult:
        tree = self.tree_loader.match_tree(user_message)
        state.reset()
        state.intent = tree.intent
        state.tree_id = tree.id
        state.status = "collecting"

        # Seed answers from the opening message when possible (e.g. error text)
        self._seed_from_opening_message(tree, state, user_message)

        if self.clarification.is_complete(tree, state):
            return self._ready_to_diagnose(state, tree)

        question = self.clarification.ask_next(tree, state)
        return TurnResult(
            mode="clarify",
            intent=intent,
            message=question,
            answers=dict(state.answers),
            tree_id=tree.id,
            phase="clarifying",
        )

    def _continue_collection(self, state: DiagnosisState, user_message: str) -> TurnResult:
        tree = self.tree_loader.get_tree(state.tree_id or "")
        if tree is None:
            state.reset()
            return TurnResult(mode="direct", intent="General SAP Query", phase="answering")

        self.clarification.apply_user_answer(state, user_message)

        if self.clarification.is_complete(tree, state):
            return self._ready_to_diagnose(state, tree)

        question = self.clarification.ask_next(tree, state)
        if question is None:
            # All askable fields exhausted; diagnose with what we have
            return self._ready_to_diagnose(state, tree)

        return TurnResult(
            mode="clarify",
            intent=ISSUE_DIAGNOSIS,
            message=question,
            answers=dict(state.answers),
            tree_id=tree.id,
            phase="clarifying",
        )

    def _ready_to_diagnose(self, state: DiagnosisState, tree: DiagnosisTree) -> TurnResult:
        enriched = self.build_enriched_query(tree, state)
        state.status = "ready"
        return TurnResult(
            mode="diagnose",
            intent=ISSUE_DIAGNOSIS,
            enriched_query=enriched,
            answers=dict(state.answers),
            tree_id=tree.id,
            phase="diagnosing",
        )

    def build_enriched_query(self, tree: DiagnosisTree, state: DiagnosisState) -> str:
        lines: list[str] = []
        if tree.retrieval_terms:
            lines.append(" ".join(tree.retrieval_terms))
        lines.append(tree.intent)

        label_map = {
            "transaction": "Transaction",
            "error_message": "Error",
            "release_group": "Release Group",
            "release_code": "Release Code",
            "po_created": "PO Created",
            "po_number": "PO Number",
            "material": "Material",
            "sales_area": "Sales Area",
            "order_number": "Order Number",
            "shipping_point": "Shipping Point",
            "sales_order": "Sales Order",
            "company_code": "Company Code",
            "account": "Account",
            "user_id": "User ID",
            "su53_object": "SU53",
            "module": "Module",
            "steps_taken": "Steps Taken",
        }

        for field_name in tree.required_fields:
            value = state.answers.get(field_name)
            if not value:
                continue
            label = label_map.get(field_name, field_name.replace("_", " ").title())
            lines.append(f"{label}: {value}")

        # Include any extra collected answers not in required_fields
        for field_name, value in state.answers.items():
            if field_name in tree.required_fields:
                continue
            label = label_map.get(field_name, field_name.replace("_", " ").title())
            lines.append(f"{label}: {value}")

        return "\n".join(lines)

    def mark_completed(self, session_id: str) -> None:
        state = self.session_store.get(session_id)
        if state is None:
            return
        state.status = "completed"
        # Idle so a new issue can start on the next turn
        state.reset()

    def clear_session(self, session_id: str) -> bool:
        return self.session_store.clear(session_id)

    def delete_session(self, session_id: str) -> bool:
        return self.session_store.delete(session_id)

    def _seed_from_opening_message(
        self,
        tree: DiagnosisTree,
        state: DiagnosisState,
        user_message: str,
    ) -> None:
        """Optionally pre-fill error_message from the opening complaint text."""
        if "error_message" not in tree.required_fields:
            return
        if "error_message" in state.answers:
            return
        # Do not auto-seed; asking for the exact error is intentional.
        # Keep hook for future NLP extraction without changing behavior.
        del user_message
