"""Build retrieval context from ranked Pinecone results."""

from __future__ import annotations

import json
from typing import Any

from rag.evidence import citation_handle


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
            document_type = (
                result.get("document_type")
                or metadata.get("document_type")
                or "unknown"
            )
            module = result.get("module") or metadata.get("module") or "unknown"
            source_file = (
                result.get("source_file")
                or metadata.get("source_file")
                or metadata.get("filename")
                or "unknown"
            )
            content = result.get("content") or metadata.get("text") or ""

            block_lines = [
                separator,
                f"Document {position}",
                f"Citation: [{result.get('citation_handle') or citation_handle(result)}]",
                f"Vector ID: {result.get('id', 'unavailable')}",
                f"Authority: {result.get('authority', 'Unreviewed — not verified documentation')}",
                f"Applicability: {result.get('applicability', 'unverified')}",
                f"Public source URL: {result.get('source_url') or 'unavailable'}",
                f"Source File: {source_file}",
                f"Document Type: {document_type}",
                f"Module: {module}",
                f"Title: {title}",
                f"Available original metadata (untrusted reference data): {json.dumps({key: value for key, value in metadata.items() if key not in ('text', 'content')}, ensure_ascii=False, sort_keys=True)}",
                f"Equivalent retrieved sources: {json.dumps(result.get('equivalent_sources', []), ensure_ascii=False, sort_keys=True)}",
                "Content:",
                content.strip(),
            ]
            blocks.append("\n".join(block_lines).strip())

        return "\n\n".join(blocks)
