"""Query preprocessing and embedding generation."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Any


class QueryProcessor:
    """Prepare user queries for semantic search."""

    def __init__(
        self,
        embedding_api_url: str | None = None,
        embedding_api_key: str | None = None,
        expected_dimension: int = 384,
    ):
        if type(expected_dimension) is not int or expected_dimension < 1:
            raise ValueError("Embedding dimension must be a positive integer")
        self.expected_dimension = expected_dimension
        self.embedding_api_url = (
            embedding_api_url or os.environ.get("EMBEDDING_API_URL", "").strip()
        )
        self.embedding_api_key = (
            embedding_api_key or os.environ.get("EMBEDDING_API_KEY", "").strip()
        )

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
        if self.embedding_api_url:
            return self._embed_with_api(query)

        return self._embed_locally(query)

    def _embed_with_api(self, query: str) -> list[float]:
        headers = {"Content-Type": "application/json"}
        if self.embedding_api_key:
            headers["Authorization"] = f"Bearer {self.embedding_api_key}"

        request = urllib.request.Request(
            self.embedding_api_url,
            data=json.dumps(
                {"inputs": query, "options": {"wait_for_model": True}}
            ).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
        ):
            raise RuntimeError("Embedding service request failed") from None

        # Only a flat sentence vector is supported. A matrix is ambiguous: it
        # may contain token embeddings, even when it has only one row.
        return self.validate_embedding(payload)

    def validate_embedding(self, embedding: Any) -> list[float]:
        if not isinstance(embedding, list) or len(embedding) != self.expected_dimension:
            raise RuntimeError("Embedding service returned an invalid vector")
        try:
            valid = all(
                type(value) in (int, float) and math.isfinite(value)
                for value in embedding
            )
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise RuntimeError("Embedding service returned an invalid vector")
        return [float(value) for value in embedding]

    def _embed_locally(self, query: str) -> list[float]:
        from ingestion.embedding import get_model

        model = get_model()
        embedding = model.encode(query)
        return self.validate_embedding(embedding.tolist())

    def normalize_filters(
        self, filters: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not filters:
            return None

        normalized: dict[str, Any] = {}
        for key, value in filters.items():
            if value is None:
                continue
            normalized_key = re.sub(
                r"[^a-z0-9_]+", "_", str(key).strip().lower()
            ).strip("_")
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

    def to_pinecone_filter(
        self, filters: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not filters:
            return None

        clauses = [{key: {"$eq": value}} for key, value in filters.items()]
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}
