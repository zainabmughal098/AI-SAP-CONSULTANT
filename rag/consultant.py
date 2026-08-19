"""End-to-end SAP consultant: retrieval, generation, memory, and HITL diagnosis."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from consultant.diagnosis_manager import DiagnosisManager, TurnResult
from consultant.response_builder import build_diagnosis_messages
from consultant.session_state import DiagnosisSessionStore
from rag.config.settings import AppSettings
from rag.generation.generator import ResponseGenerator
from rag.generation.prompt_builder import build_retrieval_query, summarize_sources
from rag.memory.conversation import ConversationMemory, ConversationStore
from rag.retriever.retriever import SemanticRetriever

logger = logging.getLogger(__name__)


@dataclass
class SAPConsultant:
    """Grounded SAP consultant with multi-turn memory and interactive diagnosis."""

    settings: AppSettings | None = None
    session_store: ConversationStore = field(default_factory=ConversationStore)
    diagnosis_store: DiagnosisSessionStore = field(default_factory=DiagnosisSessionStore)
    diagnosis_manager: DiagnosisManager | None = None
    memory: ConversationMemory | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = AppSettings.from_env()
        self.retriever = SemanticRetriever(settings=self.settings)
        self.generator = ResponseGenerator(settings=self.settings)
        if self.memory is None:
            self.memory = self.session_store.get_or_create(max_turns=self.settings.max_history_turns)
        if self.diagnosis_manager is None:
            self.diagnosis_manager = DiagnosisManager(
                settings=self.settings,
                session_store=self.diagnosis_store,
            )
        else:
            self.diagnosis_store = self.diagnosis_manager.session_store

    def reset_conversation(self) -> None:
        session_id = self.memory.session_id
        self.memory.clear()
        if session_id:
            self.diagnosis_manager.clear_session(session_id)

    def ask(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        cleaned_query = self.retriever.query_processor.clean_query(query)

        if not cleaned_query:
            return {
                "session_id": self.memory.session_id,
                "query": query or "",
                "answer": "Please enter a SAP-related question.",
                "sources": [],
                "context": "",
                "error": "Query cannot be empty",
            }

        history = self.memory.get_messages()
        turn = self.diagnosis_manager.handle_turn(
            session_id=self.memory.session_id,
            user_message=cleaned_query,
            history=history,
        )

        if turn.mode == "clarify":
            answer = (turn.message or "").strip()
            self.memory.add_user_message(cleaned_query)
            self.memory.add_assistant_message(answer)
            return {
                "session_id": self.memory.session_id,
                "query": cleaned_query,
                "answer": answer,
                "sources": [],
                "context": "",
                "context_size": 0,
                "intent": turn.intent,
                "phase": turn.phase,
                "history_length": len(self.memory.get_messages()),
                "execution_time_seconds": round(time.perf_counter() - start, 4),
            }

        retrieval_query = self._retrieval_query(cleaned_query, history, turn)
        retrieval = self.retriever.retrieve(
            query=retrieval_query,
            filters=filters,
            top_k=top_k,
        )

        if retrieval.get("error") and not retrieval.get("results"):
            return {
                "session_id": self.memory.session_id,
                "query": cleaned_query,
                "answer": f"I could not retrieve knowledge for that question: {retrieval['error']}",
                "sources": [],
                "context": retrieval.get("context", ""),
                "error": retrieval["error"],
                "intent": turn.intent,
                "phase": turn.phase,
                "execution_time_seconds": round(time.perf_counter() - start, 4),
            }

        context = retrieval.get("context", "")
        generation = self.generator.generate(
            query=cleaned_query,
            context=context,
            history=history,
            messages=self._generation_messages(turn, context, history),
        )

        answer = generation["answer"]
        self.memory.add_user_message(cleaned_query)
        self.memory.add_assistant_message(answer)

        if turn.mode == "diagnose":
            self.diagnosis_manager.mark_completed(self.memory.session_id)

        sources = summarize_sources(retrieval.get("results", []))

        return {
            "session_id": self.memory.session_id,
            "query": cleaned_query,
            "answer": answer,
            "sources": sources,
            "context": context,
            "context_size": retrieval.get("context_size", 0),
            "top_k": retrieval.get("top_k"),
            "filters": retrieval.get("filters"),
            "model": generation.get("model"),
            "intent": turn.intent,
            "phase": turn.phase,
            "history_length": len(self.memory.get_messages()),
            "execution_time_seconds": round(time.perf_counter() - start, 4),
        }

    def ask_stream(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        start = time.perf_counter()
        cleaned_query = self.retriever.query_processor.clean_query(query)

        yield {"type": "session", "session_id": self.memory.session_id}

        if not cleaned_query:
            yield {
                "type": "error",
                "message": "Please enter a SAP-related question.",
            }
            return

        history = self.memory.get_messages()
        turn = self.diagnosis_manager.handle_turn(
            session_id=self.memory.session_id,
            user_message=cleaned_query,
            history=history,
        )

        if turn.mode == "clarify":
            yield {"type": "status", "message": "Gathering details..."}
            answer = (turn.message or "").strip()
            yield {"type": "token", "content": answer}
            self.memory.add_user_message(cleaned_query)
            self.memory.add_assistant_message(answer)
            yield {
                "type": "done",
                "session_id": self.memory.session_id,
                "query": cleaned_query,
                "answer": answer,
                "sources": [],
                "intent": turn.intent,
                "phase": turn.phase,
                "model": self.settings.llm_model,
                "history_length": len(self.memory.get_messages()),
                "execution_time_seconds": round(time.perf_counter() - start, 4),
            }
            return

        yield {"type": "status", "message": "Searching knowledge base..."}

        retrieval_query = self._retrieval_query(cleaned_query, history, turn)
        retrieval = self.retriever.retrieve(
            query=retrieval_query,
            filters=filters,
            top_k=top_k,
        )

        if retrieval.get("error") and not retrieval.get("results"):
            yield {
                "type": "error",
                "message": f"I could not retrieve knowledge for that question: {retrieval['error']}",
            }
            return

        sources = summarize_sources(retrieval.get("results", []))
        yield {"type": "sources", "sources": sources}
        yield {"type": "status", "message": "Generating answer..."}

        context = retrieval.get("context", "")
        answer_parts: list[str] = []
        for token in self.generator.stream(
            query=cleaned_query,
            context=context,
            history=history,
            messages=self._generation_messages(turn, context, history),
        ):
            answer_parts.append(token)
            yield {"type": "token", "content": token}

        answer = "".join(answer_parts).strip()
        self.memory.add_user_message(cleaned_query)
        self.memory.add_assistant_message(answer)

        if turn.mode == "diagnose":
            self.diagnosis_manager.mark_completed(self.memory.session_id)

        yield {
            "type": "done",
            "session_id": self.memory.session_id,
            "query": cleaned_query,
            "answer": answer,
            "sources": sources,
            "intent": turn.intent,
            "phase": turn.phase,
            "model": self.settings.llm_model,
            "history_length": len(self.memory.get_messages()),
            "execution_time_seconds": round(time.perf_counter() - start, 4),
        }

    def _retrieval_query(
        self,
        cleaned_query: str,
        history: list[dict[str, str]],
        turn: TurnResult,
    ) -> str:
        if turn.mode == "diagnose" and turn.enriched_query:
            return turn.enriched_query
        return build_retrieval_query(cleaned_query, history)

    def _generation_messages(
        self,
        turn: TurnResult,
        context: str,
        history: list[dict[str, str]],
    ) -> list[dict[str, str]] | None:
        if turn.mode != "diagnose":
            return None
        return build_diagnosis_messages(
            enriched_query=turn.enriched_query or "",
            context=context,
            answers=turn.answers,
            history=history,
        )
