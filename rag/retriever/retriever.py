"""Semantic retrieval engine for SAP knowledge search."""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from rag.config.settings import RetrievalSettings
from rag.evidence import SourcePolicy
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
        self.query_processor = QueryProcessor(
            embedding_api_url=self.settings.embedding_api_url,
            embedding_api_key=self.settings.embedding_api_key,
        )
        self.context_builder = ContextBuilder()
        self.pinecone_client = PineconeRetrievalClient(self.settings)
        self.source_policy = SourcePolicy()

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
        document_type = metadata.get("document_type") or DOCUMENT_TYPE_BY_SOURCE.get(
            source_file or "", "unknown"
        )
        title = (
            metadata.get("title")
            or metadata.get("tcode")
            or self._extract_field(content, "title")
        )
        module = (
            metadata.get("module")
            or self._extract_field(content, "module")
            or self._extract_field(content, "business_process")
        )

        numeric_score = float(score) if score is not None else 0.0
        if not math.isfinite(numeric_score):
            raise ValueError("Invalid similarity score")
        return {
            "id": match_id,
            "score": numeric_score,
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

    def _matches_filters(
        self, result: dict[str, Any], filters: dict[str, Any] | None
    ) -> bool:
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
        candidate_values.update(
            {key: value for key, value in metadata.items() if isinstance(key, str)}
        )

        for key, expected in filters.items():
            actual = candidate_values.get(key)
            if actual is None:
                actual = self._extract_field(result.get("content", ""), key)
            if actual is None:
                return False
            if str(actual).strip().lower() != str(expected).strip().lower():
                return False

        return True

    def _dedupe_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        unique: list[dict[str, Any]] = []

        for result in results:
            content = result.get("content", "")
            # Record numbering is not knowledge. Keep transaction/error codes,
            # module, negation and diagnostic wording; never pool by title alone.
            content = re.sub(r"(?im)^\s*(?:id|record_id)\s*:.*$", "", content)
            cosmetic = re.sub(
                r"(?i)\bplease\s+(?=check\b|review\b|verify\b)", "", content
            )
            cosmetic = re.sub(r"(?i)\b(check|review|verify)\s+the\s+", r"\1 ", cosmetic)
            canonical = " ".join(
                re.findall(r"\w+|[<>]=?|!=|==|[=+*/%\-]", cosmetic.casefold())
            )
            metadata = result.get("metadata", {})
            semantic_keys = {
                key: metadata.get(key)
                for key in metadata
                if key
                not in {
                    "text",
                    "content",
                    "source",
                    "source_file",
                    "filename",
                    "row",
                    "page",
                    "page_number",
                    "csv_row",
                    "path",
                }
            }
            dedupe_key = f"{str(result.get('module')).casefold()}::{canonical}::{json.dumps(semantic_keys, sort_keys=True)}::{result.get('applicability')}::{result.get('source_kind')}"
            if dedupe_key in seen:
                if result.get("reviewed") and result.get("id") != seen[dedupe_key].get(
                    "id"
                ):
                    seen[dedupe_key].setdefault("equivalent_sources", []).append(
                        {
                            key: result.get(key)
                            for key in (
                                "id",
                                "metadata",
                                "citation_handle",
                                "source_file",
                                "source_url",
                            )
                        }
                    )
                continue
            copy = dict(result)
            seen[dedupe_key] = copy
            unique.append(copy)

        return unique

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
        pinecone_filter = self.query_processor.to_pinecone_filter(normalized_filters)
        effective_top_k = max(1, top_k or self.settings.top_k)

        try:
            logger.info("Starting knowledge search")
            embedding = self.query_processor.embed_query(cleaned_query)
            logger.info("Query embedding generated")

            search_start = time.perf_counter()
            response = self.pinecone_client.query(
                embedding=embedding,
                top_k=min(effective_top_k * 3, 100),
                metadata_filter=pinecone_filter,
            )
            search_duration = time.perf_counter() - search_start

            raw_matches = getattr(response, "matches", None)
            if raw_matches is None and isinstance(response, dict):
                raw_matches = response.get("matches", [])
            raw_matches = raw_matches or []

            results = [self._normalize_match(match) for match in raw_matches]
            results.sort(key=lambda item: item["score"], reverse=True)
            results = [
                item
                for item in results
                if self._matches_filters(item, normalized_filters)
            ]

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
                fallback_results = [
                    self._normalize_match(match) for match in fallback_matches
                ]
                results = [
                    result
                    for result in fallback_results
                    if self._matches_filters(result, normalized_filters)
                ]
                results.sort(key=lambda item: item["score"], reverse=True)
                logger.info("Fallback search execution time: %.3fs", fallback_duration)
            # Prototype exact matching against EXISTING identifier/tcode
            # metadata. Missing metadata simply leaves semantic candidates.
            numeric_codes = re.findall(
                r"\b[A-Z]{1,8}\d{2,}[A-Z0-9_]*\b", cleaned_query.upper()
            )
            alpha_codes = [
                token
                for token in re.findall(r"\b[A-Z]{4,8}\b", cleaned_query)
                if token not in {"DEMO", "SIMULATED", "SYNTHETIC"}
            ]
            codes = list(dict.fromkeys(numeric_codes + alpha_codes))[:3]
            for code in codes:
                code_filter = {
                    "$or": [{"identifier": {"$eq": code}}, {"tcode": {"$eq": code}}]
                }
                if pinecone_filter:
                    code_filter = {"$and": [pinecone_filter, code_filter]}
                try:
                    exact = self.pinecone_client.query(
                        embedding=embedding,
                        top_k=min(effective_top_k * 3, 100),
                        metadata_filter=code_filter,
                    )
                    matches = (
                        exact.get("matches", [])
                        if isinstance(exact, dict)
                        else getattr(exact, "matches", [])
                    )
                    for match in matches or []:
                        item = self._normalize_match(match)
                        metadata = item["metadata"]
                        if code in (
                            str(metadata.get("identifier", "")).upper(),
                            str(metadata.get("tcode", "")).upper(),
                        ) and self._matches_filters(item, normalized_filters):
                            results.append(item)
                except Exception:
                    logger.warning("Optional exact-code lookup unavailable")

            # Review is hash-bound to full metadata and content. Unapproved
            # commercial records never enter context, API sources or previews.
            approved = []
            for item in results:
                reviewed = self.source_policy.approve(item)
                demo_requested = re.search(
                    r"\b(?:DEMO|SIMULATED|SYNTHETIC|FICTIONAL)\b", cleaned_query, re.I
                )
                if reviewed and (
                    reviewed["source_kind"] != "synthetic" or demo_requested
                ):
                    approved.append(reviewed)
            approved.sort(
                key=lambda item: (self._exact_code(item, codes), item["score"]),
                reverse=True,
            )
            unique = self._dedupe_results(approved)
            # Lexical overlap is only a conservative contamination guard, not
            # a calibrated relevance threshold or a measured retrieval metric.
            terms = self._terms(cleaned_query)
            unique = [item for item in unique if terms & self._terms(item["content"])]
            results = self._diverse_results(unique, codes)[:effective_top_k]

            context = self.context_builder.build(results)
            context_size = len(context)

            logger.info("Search execution time: %.3fs", search_duration)
            logger.info("Number of retrieved documents: %d", len(results))
            logger.info(
                "Similarity scores: %s",
                ", ".join(f"{result['score']:.4f}" for result in results)
                if results
                else "none",
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
                "evidence_contract": 1,
                "excluded_count": len(raw_matches) - len(results)
                if len(raw_matches) >= len(results)
                else 0,
                "contradiction": self._contradiction(unique),
            }
        except Exception as exc:
            logger.warning("Retrieval failed (%s)", type(exc).__name__)
            return {
                "query": cleaned_query,
                "filters": normalized_filters,
                "top_k": effective_top_k,
                "results": [],
                "context": "",
                "error": "The knowledge search is temporarily unavailable. Please retry.",
            }

    @staticmethod
    def _diverse_results(
        results: list[dict[str, Any]], codes: list[str]
    ) -> list[dict[str, Any]]:
        """Defer repetitive action templates; do not merge differing diagnoses."""
        first, deferred, seen = [], [], set()
        for item in results:
            content = item.get("content", "")
            actions = tuple(
                re.findall(
                    r"(?im)^\s*(?:root_cause|cause|resolution|diagnostic_steps|verification)\s*:\s*(.+)$",
                    content,
                )
            )
            family = (str(item.get("module")).casefold(), actions)
            if (
                actions
                and family in seen
                and not SemanticRetriever._exact_code(item, codes)
            ):
                deferred.append(item)
            else:
                first.append(item)
                if actions:
                    seen.add(family)
        return first + deferred

    @staticmethod
    def _exact_code(item: dict[str, Any], codes: list[str]) -> bool:
        metadata = item.get("metadata", {})
        return any(
            str(metadata.get(key, "")).upper() in codes
            for key in ("identifier", "tcode")
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        stop = {
            "what",
            "which",
            "this",
            "that",
            "with",
            "from",
            "have",
            "does",
            "explain",
            "please",
            "question",
            "previous",
            "user",
            "assistant",
            "answer",
            "follow",
            "about",
            "should",
            "could",
            "would",
            "their",
            "there",
            "your",
            "will",
            "cannot",
            "error",
            "issue",
            "transaction",
            "code",
        }
        return {
            word
            for word in re.findall(r"[a-z0-9_]{3,}", text.lower())
            if word not in stop
        }

    @staticmethod
    def _contradiction(results: list[dict[str, Any]]) -> bool:
        # Only explicitly reviewed structured claims can be checked reliably.
        # Free-text contradictions remain a functional-review limitation.
        claims: dict[tuple[str, str], str] = {}
        for item in results:
            metadata = item.get("metadata", {})
            key, value = metadata.get("claim_key"), metadata.get("claim_value")
            if key is None or value is None:
                continue
            scoped_key = (str(item.get("applicability")), str(key))
            if scoped_key in claims and claims[scoped_key] != str(value):
                return True
            claims[scoped_key] = str(value)
        return False
