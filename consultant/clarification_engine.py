"""Ask clarifying questions one at a time for diagnosis trees."""

from __future__ import annotations

from consultant.diagnosis_tree_loader import DiagnosisTree
from consultant.session_state import DiagnosisState

INTRO_MESSAGE = "I need some additional information before diagnosing the issue."


class ClarificationEngine:
    """Drive single-question clarification for a diagnosis tree."""

    def next_field(self, tree: DiagnosisTree, state: DiagnosisState) -> str | None:
        """Return the next required field that still needs an answer."""
        # Keep prompting for the pending field until a non-empty answer arrives
        if (
            state.pending_field
            and state.pending_field in tree.required_fields
            and state.pending_field not in state.answers
            and state.pending_field in tree.questions
        ):
            return state.pending_field

        for field_name in tree.required_fields:
            if field_name in state.answers:
                continue
            # Never advance to a new field that was already asked and answered path
            if field_name in state.asked_fields:
                continue
            if field_name not in tree.questions:
                continue
            return field_name
        return None

    def is_complete(self, tree: DiagnosisTree, state: DiagnosisState) -> bool:
        if tree.completion_condition != "all_required_fields":
            # Unknown conditions default to requiring all required fields
            pass
        return all(field in state.answers and state.answers[field].strip() for field in tree.required_fields)

    def format_question(
        self,
        tree: DiagnosisTree,
        state: DiagnosisState,
        field_name: str,
        *,
        is_new_field: bool,
    ) -> str:
        question = tree.questions[field_name].strip()
        if is_new_field and not state.first_question_asked:
            return f"{INTRO_MESSAGE}\n\n{question}"
        return question

    def apply_user_answer(self, state: DiagnosisState, user_message: str) -> None:
        """Store the user's reply against the pending field."""
        if not state.pending_field:
            return
        cleaned = (user_message or "").strip()
        if not cleaned:
            return
        state.record_answer(state.pending_field, cleaned)

    def ask_next(self, tree: DiagnosisTree, state: DiagnosisState) -> str | None:
        """Mark and return the next clarifying question, or None if complete."""
        if self.is_complete(tree, state):
            return None

        field_name = self.next_field(tree, state)
        if field_name is None:
            return None

        is_new_field = field_name not in state.asked_fields
        question = self.format_question(tree, state, field_name, is_new_field=is_new_field)
        if is_new_field:
            state.mark_asked(field_name)
        else:
            state.pending_field = field_name
            state.status = "collecting"
        return question
