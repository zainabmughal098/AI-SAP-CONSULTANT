"""Structured prompts for final SAP diagnosis responses."""

from __future__ import annotations

from typing import Any

DIAGNOSIS_SYSTEM_PROMPT = """You are an expert SAP Functional Consultant providing a structured issue diagnosis.

Rules:
1. Answer ONLY using the retrieved SAP knowledge base context, the collected diagnostic answers, and conversation history.
2. If the context does not contain enough information, say so clearly. Do not invent SAP transaction codes, tables, configuration, or resolution steps.
3. Produce a structured diagnosis with these exact section headings:

## Diagnosis
## Possible Root Cause
## Reasoning
## Recommended Resolution
## Related T-Codes
## Related Tables
## Confidence Score

4. Confidence Score must be a percentage (e.g. 75%) reflecting how well the retrieved context supports the diagnosis.
5. Be practical and concise. Prefer actionable steps a functional consultant would take.
"""


def build_diagnosis_messages(
    enriched_query: str,
    context: str,
    answers: dict[str, str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build Groq chat messages for a structured diagnosis response."""
    history = history or []
    answers = answers or {}
    context_block = context.strip() or "No relevant records were retrieved from the knowledge base."

    answer_lines = "\n".join(f"- {key}: {value}" for key, value in answers.items()) or "- (none)"

    user_prompt = f"""Retrieved SAP knowledge base context:
{context_block}

Collected diagnostic information:
{answer_lines}

Enriched diagnostic query:
{enriched_query}

Provide a structured SAP diagnosis using the required section headings."""

    messages: list[dict[str, str]] = [{"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    return messages


def format_answers_summary(answers: dict[str, Any]) -> str:
    if not answers:
        return ""
    return "\n".join(f"{key}: {value}" for key, value in answers.items())
