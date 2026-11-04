"""Public error contract. Provider exception text must not reach the browser."""

from __future__ import annotations

from groq import APITimeoutError


class ConsultantError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 503, retryable: bool = True
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def service_error(exc: Exception, stage: str) -> ConsultantError:
    """Translate failures without copying URLs, headers, keys or provider bodies."""
    if isinstance(exc, ConsultantError):
        return exc
    status = getattr(exc, "status_code", None)
    if status == 429:
        return ConsultantError(
            "rate_limited", "The service is busy. Please wait a moment and retry.", 429
        )
    if isinstance(exc, (TimeoutError, APITimeoutError)):
        return ConsultantError(
            "provider_timeout", "The service took too long to respond. Please retry.", 504
        )
    if status in (401, 403):
        return ConsultantError(
            "provider_configuration_error",
            "A required service is unavailable. Please contact the application administrator.",
            503,
            False,
        )
    message = (
        "The knowledge search is temporarily unavailable. Please retry."
        if stage == "retrieval"
        else "The answer service is temporarily unavailable. Please retry."
    )
    return ConsultantError(f"{stage}_unavailable", message)


def incomplete_response() -> ConsultantError:
    return ConsultantError(
        "incomplete_response",
        "The answer was incomplete and has not been saved as a completed response. "
        "Please retry, or ask a shorter question.",
        502,
    )
