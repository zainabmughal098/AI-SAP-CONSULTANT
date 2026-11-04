"""End-to-end SAP consultant: retrieval, generation, memory, and HITL diagnosis."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from consultant.diagnosis_manager import DiagnosisManager, TurnResult
from consultant.response_builder import build_diagnosis_messages
from consultant.session_state import DiagnosisSessionStore, DiagnosisState
from rag.config.settings import AppSettings
from rag.errors import ConsultantError, service_error
from rag.evidence import WITHHELD, evidence_refusal, grounding_failure
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
    diagnosis_store: DiagnosisSessionStore = field(
        default_factory=DiagnosisSessionStore
    )
    diagnosis_manager: DiagnosisManager | None = None
    memory: ConversationMemory | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = AppSettings.from_env()
        self.retriever = SemanticRetriever(settings=self.settings)
        self.generator = ResponseGenerator(settings=self.settings)
        if self.memory is None:
            self.memory = self.session_store.get_or_create(
                max_turns=self.settings.max_history_turns
            )
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
        snapshot = deepcopy(self.diagnosis_store.get(self.memory.session_id))
        try:
            return self._ask(query, filters, top_k)
        except Exception as exc:
            self._restore_diagnosis(snapshot)
            error = service_error(exc, "generation")
            logger.warning("Chat failed: %s", error.code)
            return {
                "session_id": self.memory.session_id,
                "query": query,
                "answer": error.message,
                "sources": [],
                "error": error.message,
                "error_code": error.code,
                "http_status": error.status_code,
                "retryable": error.retryable,
                "complete": False,
            }

    def _ask(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        cleaned_query = self.retriever.query_processor.clean_query(query)

        if not cleaned_query:
            raise ConsultantError(
                "invalid_query", "Please enter a SAP-related question.", 400, False
            )

        history = self.memory.get_messages()
        turn = self.diagnosis_manager.handle_turn(
            session_id=self.memory.session_id,
            user_message=cleaned_query,
            history=history,
        )
        if not turn.include_history:
            history = []

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
        retrieval = self._retrieve(
            query=retrieval_query,
            filters=filters,
            top_k=top_k,
        )

        context = retrieval.get("context", "")
        fallback = evidence_refusal(
            cleaned_query, retrieval
        ) or self._unsupported_diagnosis(turn, context)
        generation = (
            {"answer": fallback}
            if fallback
            else self.generator.generate(
                query=turn.standalone_query or cleaned_query,
                context=context,
                history=history,
                messages=self._generation_messages(turn, context, history),
            )
        )

        generated = generation["answer"]
        if not fallback and retrieval.get("evidence_contract") == 1:
            generated = self._grounded_answer(generated, retrieval)
        answer = self._preliminary_notice(turn) + generated
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
        snapshot = deepcopy(self.diagnosis_store.get(self.memory.session_id))
        completed = False
        events = self._ask_stream(query, filters, top_k)
        try:
            for event in events:
                if event.get("type") == "done":
                    completed = True
                yield event
        except GeneratorExit:
            if not completed:
                self._restore_diagnosis(snapshot)
            raise
        except Exception as exc:
            self._restore_diagnosis(snapshot)
            error = service_error(exc, "generation")
            logger.warning("Chat stream failed: %s", error.code)
            yield {
                "type": "error",
                "session_id": self.memory.session_id,
                "message": error.message,
                "error_code": error.code,
                "retryable": error.retryable,
                "complete": False,
            }
        finally:
            events.close()

    def _ask_stream(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        start = time.perf_counter()
        cleaned_query = self.retriever.query_processor.clean_query(query)

        yield {"type": "session", "session_id": self.memory.session_id}

        if not cleaned_query:
            raise ConsultantError(
                "invalid_query", "Please enter a SAP-related question.", 400, False
            )

        history = self.memory.get_messages()
        turn = self.diagnosis_manager.handle_turn(
            session_id=self.memory.session_id,
            user_message=cleaned_query,
            history=history,
        )
        if not turn.include_history:
            history = []

        if turn.mode == "clarify":
            yield {"type": "status", "message": "Gathering details..."}
            answer = (turn.message or "").strip()
            yield {"type": "token", "content": answer}
            self.memory.add_user_message(cleaned_query)
            self.memory.add_assistant_message(answer)
            yield {
                "type": "done",
                "complete": True,
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
        retrieval = self._retrieve(
            query=retrieval_query,
            filters=filters,
            top_k=top_k,
        )

        sources = summarize_sources(retrieval.get("results", []))
        yield {"type": "sources", "sources": sources}
        yield {"type": "status", "message": "Generating answer..."}

        context = retrieval.get("context", "")
        answer_parts: list[str] = []
        notice = self._preliminary_notice(turn)
        if notice:
            answer_parts.append(notice)
            yield {"type": "token", "content": notice}
        fallback = evidence_refusal(
            cleaned_query, retrieval
        ) or self._unsupported_diagnosis(turn, context)
        tokens = (
            [fallback]
            if fallback
            else self.generator.stream(
                query=turn.standalone_query or cleaned_query,
                context=context,
                history=history,
                messages=self._generation_messages(turn, context, history),
            )
        )
        # Reviewed-evidence answers are buffered until provider completion and
        # structural grounding checks pass. Existing status/SSE protocol stays.
        guarded = retrieval.get("evidence_contract") == 1 and not fallback
        buffered = []
        try:
            for token in tokens:
                if guarded:
                    buffered.append(token)
                else:
                    answer_parts.append(token)
                    yield {"type": "token", "content": token}
        finally:
            if hasattr(tokens, "close"):
                tokens.close()
        if guarded:
            validated = self._grounded_answer("".join(buffered), retrieval)
            answer_parts.append(validated)
            yield {"type": "token", "content": validated}

        answer = "".join(answer_parts).strip()
        self.memory.add_user_message(cleaned_query)
        self.memory.add_assistant_message(answer)

        if turn.mode == "diagnose":
            self.diagnosis_manager.mark_completed(self.memory.session_id)

        yield {
            "type": "done",
            "complete": True,
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

    def _restore_diagnosis(self, snapshot: DiagnosisState | None) -> None:
        """Allow retrying a failed final clarification without losing collected details."""
        state = self.diagnosis_store.get_or_create(self.memory.session_id)
        if snapshot is None:
            state.reset()
        else:
            state.__dict__.update(deepcopy(snapshot.__dict__))

    @staticmethod
    def _grounded_answer(answer: str, retrieval: dict[str, Any]) -> str:
        results = retrieval.get("results", [])
        if grounding_failure(answer, results):
            return WITHHELD
        if any(item.get("source_kind") == "synthetic" for item in results):
            return (
                "DEMO / SIMULATED scenario. No actual FFC data or live SAP operations.\n\n"
                + answer
            )
        return answer

    def _retrieve(self, **kwargs) -> dict[str, Any]:
        try:
            result = self.retriever.retrieve(**kwargs)
            if result.get("error"):
                raise ConsultantError(
                    "retrieval_unavailable",
                    "The knowledge search is temporarily unavailable. Please retry.",
                )
            return result
        except Exception as exc:
            raise service_error(exc, "retrieval") from None

    def _retrieval_query(
        self,
        cleaned_query: str,
        history: list[dict[str, str]],
        turn: TurnResult,
    ) -> str:
        if turn.mode == "diagnose" and turn.enriched_query:
            return turn.enriched_query
        return build_retrieval_query(turn.standalone_query or cleaned_query, history)

    def _preliminary_notice(self, turn: TurnResult) -> str:
        if not turn.preliminary:
            return ""
        missing = ", ".join(key.replace("_", " ") for key in turn.unknown_fields)
        return f"Preliminary guidance only. Unavailable details: {missing}. These are not confirmed evidence.\n\n"

    def _unsupported_diagnosis(self, turn: TurnResult, context: str) -> str | None:
        if turn.mode == "diagnose" and not context.strip():
            return (
                "I do not have enough retrieved knowledge to provide source-grounded troubleshooting steps. "
                "I cannot confirm a root cause or recommend SAP configuration changes from the available evidence. "
                "You can provide missing details or approved documentation to continue."
            )
        return None

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
            history=[],
            unknown_fields=turn.unknown_fields,
            preliminary=turn.preliminary,
        )
