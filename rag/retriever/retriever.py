"""Semantic retrieval engine for SAP knowledge search."""

from __future__ import annotations

import re
import logging
import time
from dataclasses import dataclass
from typing import Any

from rag.config.settings import RetrievalSettings
from rag.pinecone.client import PineconeRetrievalClient
from rag.retriever.context_builder import ContextBuilder
from rag.retriever.query_processor import QueryProcessor

logger = logging.getLogger(__name__)

DOCUMENT_TYPE_BY_SOURCE = {
    "business_processes.csv": "business_process",
    "common_errors.csv": "common_error",
    "issue_resolution.csv": "issue_resolution",
    "materials.csv": "material",
    "modules.csv": "module",
    "sap_glossary.csv": "glossary",
    "tcodes.csv": "tcode",
}


@dataclass
class SemanticRetriever:
    """End-to-end retrieval engine."""

    settings: RetrievalSettings | None = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = RetrievalSettings.from_env()
        self.query_processor = QueryProcessor()
        self.context_builder = ContextBuilder()
        self.pinecone_client = PineconeRetrievalClient(self.settings)

    def _normalize_match(self, match: Any) -> dict[str, Any]:
        if isinstance(match, dict):
            score = match.get("score")
            metadata = match.get("metadata") or {}
            match_id = match.get("id")
        else:
            score = getattr(match, "score", None)
            metadata = getattr(match, "metadata", {}) or {}
            match_id = getattr(match, "id", None)

        content = metadata.get("text") or metadata.get("content") or ""
        source_file = metadata.get("source_file") or metadata.get("filename")
        document_type = metadata.get("document_type") or DOCUMENT_TYPE_BY_SOURCE.get(source_file or "", "unknown")
        title = metadata.get("title") or metadata.get("tcode") or self._extract_field(content, "title")
        module = metadata.get("module") or self._extract_field(content, "module") or self._extract_field(content, "business_process")

        return {
            "id": match_id,
            "score": float(score) if score is not None else 0.0,
            "source_file": source_file,
            "document_type": document_type,
            "module": module,
            "title": title,
            "content": content,
            "metadata": metadata,
        }

    def _extract_field(self, content: str, field_name: str) -> str | None:
        if not content:
            return None

        pattern = re.compile(rf"(?im)^\s*{re.escape(field_name)}\s*:\s*(.+?)\s*$")
        match = pattern.search(content)
        if match:
            return match.group(1).strip()

        return None

    def _matches_filters(self, result: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True

        candidate_values = {
            "source_file": result.get("source_file"),
            "filename": result.get("source_file"),
            "document_type": result.get("document_type"),
            "module": result.get("module"),
            "title": result.get("title"),
        }

        metadata = result.get("metadata") or {}
        candidate_values.update({key: value for key, value in metadata.items() if isinstance(key, str)})

        for key, expected in filters.items():
            actual = candidate_values.get(key)
            if actual is None:
                actual = self._extract_field(result.get("content", ""), key)
            if actual is None:
                return False
            if str(actual).strip().lower() != str(expected).strip().lower():
                return False

        return True

    def retrieve(
        self,
        query: str | None,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        request_start = time.perf_counter()
        cleaned_query = self.query_processor.clean_query(query)

        if not cleaned_query:
            logger.warning("Empty retrieval query received")
            return {
                "query": query or "",
                "filters": self.query_processor.normalize_filters(filters),
                "top_k": top_k or self.settings.top_k,
                "results": [],
                "context": "",
                "error": "Query cannot be empty",
            }

        normalized_filters = self.query_processor.normalize_filters(filters)
        effective_top_k = max(1, top_k or self.settings.top_k)

        try:
            logger.info("User query: %s", cleaned_query)
            embedding = self.query_processor.embed_query(cleaned_query)
            logger.info("Query embedding generated")

            search_start = time.perf_counter()
            response = self.pinecone_client.query(
                embedding=embedding,
                top_k=effective_top_k,
                metadata_filter=normalized_filters,
            )
            search_duration = time.perf_counter() - search_start

            raw_matches = getattr(response, "matches", None)
            if raw_matches is None and isinstance(response, dict):
                raw_matches = response.get("matches", [])
            raw_matches = raw_matches or []

            results = [self._normalize_match(match) for match in raw_matches]
            results.sort(key=lambda item: item["score"], reverse=True)

            if normalized_filters and not results:
                fallback_start = time.perf_counter()
                fallback_response = self.pinecone_client.query(
                    embedding=embedding,
                    top_k=max(effective_top_k * 5, effective_top_k),
                    metadata_filter=None,
                )
                fallback_duration = time.perf_counter() - fallback_start
                fallback_matches = getattr(fallback_response, "matches", None)
                if fallback_matches is None and isinstance(fallback_response, dict):
                    fallback_matches = fallback_response.get("matches", [])
                fallback_matches = fallback_matches or []
                fallback_results = [self._normalize_match(match) for match in fallback_matches]
                results = [result for result in fallback_results if self._matches_filters(result, normalized_filters)]
                results.sort(key=lambda item: item["score"], reverse=True)
                logger.info("Fallback search execution time: %.3fs", fallback_duration)

            context = self.context_builder.build(results)
            context_size = len(context)

            logger.info("Search execution time: %.3fs", search_duration)
            logger.info("Number of retrieved documents: %d", len(results))
            logger.info(
                "Similarity scores: %s",
                ", ".join(f"{result['score']:.4f}" for result in results) if results else "none",
            )
            logger.info("Context size: %d characters", context_size)

            return {
                "query": cleaned_query,
                "filters": normalized_filters,
                "top_k": effective_top_k,
                "results": results,
                "context": context,
                "context_size": context_size,
                "execution_time_seconds": round(time.perf_counter() - request_start, 4),
            }
        except Exception as exc:
            logger.exception("Retrieval failed: %s", exc)
            return {
                "query": cleaned_query,
                "filters": normalized_filters,
                "top_k": effective_top_k,
                "results": [],
                "context": "",
                "error": str(exc),
            }
