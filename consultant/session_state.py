"""Conversation state for interactive diagnosis flows."""

from __future__ import annotations

import re
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
    opening_message: str = ""
    unknown_fields: dict[str, str] = field(default_factory=dict)
    conflicts: dict[str, list[str]] = field(default_factory=dict)
    invalid_replies: dict[str, int] = field(default_factory=dict)
    followups: list[str] = field(default_factory=list)
    symptom_corrected: bool = False

    def record_answer(self, field_name: str, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            return
        previous = self.answers.get(field_name)
        if previous and previous != cleaned:
            self.opening_message = re.sub(
                rf"(?<!\w){re.escape(previous)}(?!\w)",
                lambda _: cleaned,
                self.opening_message,
                flags=re.I,
            )
        self.answers[field_name] = cleaned
        self.unknown_fields.pop(field_name, None)
        self.conflicts.pop(field_name, None)
        self.invalid_replies.pop(field_name, None)
        if field_name not in self.asked_fields:
            self.asked_fields.append(field_name)
        if self.pending_field == field_name:
            self.pending_field = None

    def mark_unknown(self, field_name: str, reason: str) -> None:
        previous = self.answers.pop(field_name, None)
        if previous:
            self.opening_message = re.sub(
                rf"(?<!\w){re.escape(previous)}(?!\w)",
                "[unavailable]",
                self.opening_message,
                flags=re.I,
            )
        self.unknown_fields[field_name] = reason
        self.conflicts.pop(field_name, None)
        if field_name not in self.asked_fields:
            self.asked_fields.append(field_name)
        if self.pending_field == field_name:
            self.pending_field = None

    def mark_conflict(self, field_name: str, values: list[str]) -> None:
        self.answers.pop(field_name, None)
        self.unknown_fields.pop(field_name, None)
        self.conflicts[field_name] = list(dict.fromkeys(values))
        for value in values:
            self.opening_message = re.sub(
                rf"(?<!\w){re.escape(value)}(?!\w)",
                "[unconfirmed]",
                self.opening_message,
                flags=re.I,
            )

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
        self.opening_message = ""
        self.unknown_fields.clear()
        self.conflicts.clear()
        self.invalid_replies.clear()
        self.followups.clear()
        self.symptom_corrected = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "tree_id": self.tree_id,
            "answers": dict(self.answers),
            "asked_fields": list(self.asked_fields),
            "pending_field": self.pending_field,
            "status": self.status,
            "first_question_asked": self.first_question_asked,
            "opening_message": self.opening_message,
            "symptom_corrected": self.symptom_corrected,
            "unknown_fields": dict(self.unknown_fields),
            "conflicts": {key: list(value) for key, value in self.conflicts.items()},
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
