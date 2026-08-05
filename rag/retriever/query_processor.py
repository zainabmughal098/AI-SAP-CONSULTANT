"""Query preprocessing and embedding generation."""

from __future__ import annotations

import re
from typing import Any

from ingestion.embedding import get_model


class QueryProcessor:
    """Prepare user queries for semantic search."""

    def clean_query(self, query: str | None) -> str:
        if query is None:
            return ""
        cleaned = re.sub(r"\s+", " ", query).strip()
        return cleaned

    def validate_query(self, query: str) -> None:
        if not query:
            raise ValueError("Query cannot be empty")

    def embed_query(self, query: str) -> list[float]:
        self.validate_query(query)
        model = get_model()
        embedding = model.encode(query)
        return embedding.tolist()

    def normalize_filters(self, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None

        normalized: dict[str, Any] = {}
        for key, value in filters.items():
            if value is None:
                continue
            normalized_key = re.sub(r"[^a-z0-9_]+", "_", str(key).strip().lower()).strip("_")
            if not normalized_key:
                continue
            if isinstance(value, str):
                cleaned_value = value.strip()
                if not cleaned_value:
                    continue
                normalized[normalized_key] = cleaned_value
            else:
                normalized[normalized_key] = value

        return normalized or None

    def to_pinecone_filter(self, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None

        clauses = [{key: {"$eq": value}} for key, value in filters.items()]
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}
