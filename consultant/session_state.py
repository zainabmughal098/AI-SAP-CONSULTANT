"""Conversation state for interactive diagnosis flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DiagnosisStatus = Literal["idle", "collecting", "ready", "completed"]


@dataclass
class DiagnosisState:
    """Tracks an in-progress diagnostic clarification flow for one session."""

    intent: str | None = None
    tree_id: str | None = None
    answers: dict[str, str] = field(default_factory=dict)
    asked_fields: list[str] = field(default_factory=list)
    pending_field: str | None = None
    status: DiagnosisStatus = "idle"
    first_question_asked: bool = False

    def record_answer(self, field_name: str, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            return
        self.answers[field_name] = cleaned
        if field_name not in self.asked_fields:
            self.asked_fields.append(field_name)
        if self.pending_field == field_name:
            self.pending_field = None

    def mark_asked(self, field_name: str) -> None:
        if field_name not in self.asked_fields:
            self.asked_fields.append(field_name)
        self.pending_field = field_name
        self.first_question_asked = True
        self.status = "collecting"

    def reset(self) -> None:
        self.intent = None
        self.tree_id = None
        self.answers.clear()
        self.asked_fields.clear()
        self.pending_field = None
        self.status = "idle"
        self.first_question_asked = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "tree_id": self.tree_id,
            "answers": dict(self.answers),
            "asked_fields": list(self.asked_fields),
            "pending_field": self.pending_field,
            "status": self.status,
            "first_question_asked": self.first_question_asked,
        }


class DiagnosisSessionStore:
    """In-memory registry of diagnosis state keyed by chat session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, DiagnosisState] = {}

    def get_or_create(self, session_id: str) -> DiagnosisState:
        if session_id not in self._sessions:
            self._sessions[session_id] = DiagnosisState()
        return self._sessions[session_id]

    def get(self, session_id: str) -> DiagnosisState | None:
        return self._sessions.get(session_id)

    def clear(self, session_id: str) -> bool:
        state = self._sessions.get(session_id)
        if state is None:
            return False
        state.reset()
        return True

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None
