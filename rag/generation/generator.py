"""LLM response generation using Groq."""

from __future__ import annotations

import logging
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

    def generate(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        messages = build_messages(query=query, context=context, history=history)

        logger.info("Generating grounded response with model %s", self.settings.llm_model)
        completion = self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=messages,
            temperature=self.settings.llm_temperature,
            max_tokens=self.settings.llm_max_tokens,
        )

        answer = completion.choices[0].message.content.strip()
        usage = getattr(completion, "usage", None)

        return {
            "answer": answer,
            "model": self.settings.llm_model,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
