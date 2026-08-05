"""Conversation memory for multi-turn SAP consultant sessions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationMemory:
    """Stores recent user/assistant turns for a chat session."""

    session_id: str | None = None
    max_turns: int = 10
    messages: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = str(uuid.uuid4())

    def add_user_message(self, content: str) -> None:
        self._append("user", content)

    def add_assistant_message(self, content: str) -> None:
        self._append("assistant", content)

    def _append(self, role: str, content: str) -> None:
        cleaned = content.strip()
        if not cleaned:
            return
        self.messages.append({"role": role, "content": cleaned})
        self._trim()

    def _trim(self) -> None:
        max_messages = self.max_turns * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]

    def get_messages(self) -> list[dict[str, str]]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "messages": self.get_messages(),
        }


class ConversationStore:
    """In-memory registry of active chat sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationMemory] = {}

    def get_or_create(self, session_id: str | None = None, max_turns: int = 10) -> ConversationMemory:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        memory = ConversationMemory(session_id=session_id, max_turns=max_turns)
        self._sessions[memory.session_id] = memory
        return memory

    def clear(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._sessions[session_id].clear()
        return True

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None
