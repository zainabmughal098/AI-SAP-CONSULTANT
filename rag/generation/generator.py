"""LLM response generation using Groq."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from groq import Groq

from rag.config.settings import AppSettings
from rag.generation.prompt_builder import build_messages

logger = logging.getLogger(__name__)


@dataclass
class ResponseGenerator:
    """Generate grounded answers from retrieved context."""

    settings: AppSettings

    def __post_init__(self) -> None:
        self.client = Groq(api_key=self.settings.groq_api_key)

    def _completion_kwargs(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return {
            "model": self.settings.llm_model,
            "messages": build_messages(query=query, context=context, history=history),
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }

    def generate(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        logger.info("Generating grounded response with model %s", self.settings.llm_model)
        completion = self.client.chat.completions.create(
            **self._completion_kwargs(query, context, history),
        )

        answer = completion.choices[0].message.content.strip()
        usage = getattr(completion, "usage", None)

        return {
            "answer": answer,
            "model": self.settings.llm_model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }

    def stream(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        logger.info("Streaming grounded response with model %s", self.settings.llm_model)
        stream = self.client.chat.completions.create(
            **self._completion_kwargs(query, context, history),
            stream=True,
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
