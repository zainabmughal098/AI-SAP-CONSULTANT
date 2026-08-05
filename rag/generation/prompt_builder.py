"""Prompt construction for grounded SAP consultant responses."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are an expert SAP consultant assistant.

Rules:
1. Answer ONLY using the retrieved SAP knowledge base context and the ongoing conversation.
2. If the context does not contain enough information, say you do not have enough information in the knowledge base. Do not invent SAP transaction codes, tables, or processes.
3. Be concise, practical, and structured. Use bullet points or numbered steps when helpful.
4. Reference relevant SAP modules, transaction codes, tables, and resolution steps when they appear in the context.
5. For follow-up questions, use conversation history to resolve references such as "that tcode", "you mentioned", or "what about release".
6. When citing knowledge base records, mention the source type such as tcode, common error, or issue resolution when useful.
"""


def build_retrieval_query(query: str, history: list[dict[str, str]] | None = None) -> str:
    """Expand follow-up questions with recent conversation context for retrieval."""
    if not history:
        return query

    last_user = None
    last_assistant = None
    for message in reversed(history):
        if message["role"] == "assistant" and last_assistant is None:
            last_assistant = message["content"][:400]
        elif message["role"] == "user" and last_user is None:
            last_user = message["content"]
        if last_user and last_assistant:
            break

    if not last_user:
        return query

    return (
        f"Previous user question: {last_user}\n"
        f"Previous assistant answer: {last_assistant}\n"
        f"Follow-up question: {query}"
    )


def build_messages(
    query: str,
    context: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    history = history or []
    context_block = context.strip() or "No relevant records were retrieved from the knowledge base."

    user_prompt = f"""Retrieved SAP knowledge base context:
{context_block}

Current user question:
{query}

Provide a grounded answer based on the context above."""

    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    return messages


def summarize_sources(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    for result in results:
        key = result.get("id") or f"{result.get('source_file')}::{result.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "score": result.get("score"),
                "source_file": result.get("source_file"),
                "document_type": result.get("document_type"),
                "module": result.get("module"),
                "title": result.get("title"),
                "content_preview": (result.get("content") or "")[:240],
            }
        )

    return sources
