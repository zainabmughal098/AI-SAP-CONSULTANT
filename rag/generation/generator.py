"""LLM response generation using Groq."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from groq import Groq

from rag.config.settings import AppSettings
from rag.errors import ConsultantError, incomplete_response, service_error
from rag.generation.prompt_builder import build_messages

logger = logging.getLogger(__name__)


@dataclass
class ResponseGenerator:
    """Generate grounded answers from retrieved context."""

    settings: AppSettings

    def __post_init__(self) -> None:
        self.client = Groq(api_key=self.settings.groq_api_key, timeout=30.0, max_retries=0)

    def _completion_kwargs(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
        messages: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return {
            "model": self.settings.llm_model,
            "messages": messages
            if messages is not None
            else build_messages(query=query, context=context, history=history),
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }

    def generate(
        self,
        query: str,
        context: str,
        history: list[dict[str, str]] | None = None,
        messages: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        logger.info("Generating grounded response with model %s", self.settings.llm_model)
        try:
            completion = self.client.chat.completions.create(
                **self._completion_kwargs(query, context, history, messages=messages),
            )
            choice = completion.choices[0]
            if choice.finish_reason != "stop":
                raise incomplete_response()
            answer = (choice.message.content or "").strip()
            if not answer:
                raise ConsultantError(
                    "empty_response", "The answer service returned no answer. Please retry.", 502
                )
            usage = getattr(completion, "usage", None)
        except Exception as exc:
            raise service_error(exc, "generation") from None

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
        messages: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        logger.info("Streaming grounded response with model %s", self.settings.llm_model)
        stream = None
        try:
            stream = self.client.chat.completions.create(
                **self._completion_kwargs(query, context, history, messages=messages),
                stream=True,
            )
            finished = False
            has_text = False
            for chunk in stream:
                # Providers may send a final usage-only chunk with no choices.
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta.content
                if delta:
                    has_text = has_text or bool(delta.strip())
                    yield delta
                if choice.finish_reason is not None:
                    if choice.finish_reason != "stop":
                        raise incomplete_response()
                    finished = True
            if not finished:
                raise incomplete_response()
            if not has_text:
                raise ConsultantError(
                    "empty_response", "The answer service returned no answer. Please retry.", 502
                )
        except Exception as exc:
            raise service_error(exc, "generation") from None
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    # Cleanup must not hide an existing failure or expose provider details.
                    logger.warning("Could not close answer stream")
