"""End-to-end SAP consultant: retrieval, generation, and memory."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from rag.config.settings import AppSettings
from rag.generation.generator import ResponseGenerator
from rag.generation.prompt_builder import build_retrieval_query, summarize_sources
from rag.memory.conversation import ConversationMemory, ConversationStore
from rag.retriever.retriever import SemanticRetriever

logger = logging.getLogger(__name__)


@dataclass
class SAPConsultant:
    """Grounded SAP consultant with multi-turn memory."""

    settings: AppSettings | None = None
    session_store: ConversationStore = field(default_factory=ConversationStore)
    memory: ConversationMemory | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = AppSettings.from_env()
        self.retriever = SemanticRetriever(settings=self.settings)
        self.generator = ResponseGenerator(settings=self.settings)
        if self.memory is None:
            self.memory = self.session_store.get_or_create(max_turns=self.settings.max_history_turns)

    def reset_conversation(self) -> None:
        self.memory.clear()

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
        retrieval_query = build_retrieval_query(cleaned_query, history)

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
                "execution_time_seconds": round(time.perf_counter() - start, 4),
            }

        generation = self.generator.generate(
            query=cleaned_query,
            context=retrieval.get("context", ""),
            history=history,
        )

        answer = generation["answer"]
        self.memory.add_user_message(cleaned_query)
        self.memory.add_assistant_message(answer)

        sources = summarize_sources(retrieval.get("results", []))

        return {
            "session_id": self.memory.session_id,
            "query": cleaned_query,
            "answer": answer,
            "sources": sources,
            "context": retrieval.get("context", ""),
            "context_size": retrieval.get("context_size", 0),
            "top_k": retrieval.get("top_k"),
            "filters": retrieval.get("filters"),
            "model": generation.get("model"),
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

        yield {"type": "status", "message": "Searching knowledge base..."}

        history = self.memory.get_messages()
        retrieval_query = build_retrieval_query(cleaned_query, history)
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

        answer_parts: list[str] = []
        for token in self.generator.stream(
            query=cleaned_query,
            context=retrieval.get("context", ""),
            history=history,
        ):
            answer_parts.append(token)
            yield {"type": "token", "content": token}

        answer = "".join(answer_parts).strip()
        self.memory.add_user_message(cleaned_query)
        self.memory.add_assistant_message(answer)

        yield {
            "type": "done",
            "session_id": self.memory.session_id,
            "query": cleaned_query,
            "answer": answer,
            "sources": sources,
            "model": self.settings.llm_model,
            "history_length": len(self.memory.get_messages()),
            "execution_time_seconds": round(time.perf_counter() - start, 4),
        }
