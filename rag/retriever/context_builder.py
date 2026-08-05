"""Build retrieval context from ranked Pinecone results."""

from __future__ import annotations

from typing import Any


class ContextBuilder:
    """Combine retrieved records into a single context block."""

    def build(self, results: list[dict[str, Any]]) -> str:
        if not results:
            return ""

        blocks: list[str] = []
        separator = "-" * 32

        for position, result in enumerate(results, start=1):
            metadata = result.get("metadata") or {}
            title = (
                result.get("title")
                or metadata.get("title")
                or metadata.get("tcode")
                or metadata.get("identifier")
                or metadata.get("source_file")
                or "Unknown"
            )
            document_type = result.get("document_type") or metadata.get("document_type") or "unknown"
            module = result.get("module") or metadata.get("module") or "unknown"
            source_file = result.get("source_file") or metadata.get("source_file") or metadata.get("filename") or "unknown"
            content = result.get("content") or metadata.get("text") or ""
            score = result.get("score")
            score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "unknown"

            block_lines = [
                separator,
                f"Document {position}",
                f"Score: {score_text}",
                f"Source File: {source_file}",
                f"Document Type: {document_type}",
                f"Module: {module}",
                f"Title: {title}",
                "Content:",
                content.strip(),
            ]
            blocks.append("\n".join(block_lines).strip())

        return "\n\n".join(blocks)
