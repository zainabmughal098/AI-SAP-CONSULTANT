"""Local review boundary and citation checks. Never trusts approval flags in vectors."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parent / "approved_sources.json"
INSUFFICIENT = (
    "I do not have enough reviewed public SAP evidence to answer this question safely. "
    "Legacy or unrelated records are not verified documentation. This is a DEMO prototype; "
    "I have not accessed a live SAP system or executed a transaction. "
    "FFC policies, suppliers and operational records are unavailable."
)
WITHHELD = (
    "I could not validate the answer's source references or evidence boundaries, so I withheld it. "
    "Please consult reviewed public SAP documentation. No SAP transaction was executed."
)


def record_digest(record: dict[str, Any]) -> str:
    """Bind approval to exact content AND every metadata value, not a filename."""
    identity = {key: record.get(key) for key in ("id", "content", "metadata")}
    return hashlib.sha256(
        json.dumps(
            identity, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def citation_handle(record: dict[str, Any]) -> str:
    return "SRC-" + record_digest(record)[:20]


class SourcePolicy:
    """Only repository-reviewed, hash-bound records may leave retrieval.

    Registry changes require human provenance/confidentiality/licensing review.
    Empty by default: legacy vectors cannot self-declare themselves approved.
    """

    def __init__(self, entries: dict[str, dict[str, Any]] | None = None):
        self.entries = (
            entries
            if entries is not None
            else json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]
        )

    def approve(self, record: dict[str, Any]) -> dict[str, Any] | None:
        review = self.entries.get(record_digest(record))
        if not review or review.get("reviewed") is not True:
            return None
        kind = review.get("kind")
        if kind == "public_sap":
            url = urlsplit(review.get("source_url", ""))
            if (
                url.scheme != "https"
                or url.hostname != "help.sap.com"
                or url.username
                or url.password
            ):
                return None
            if (
                review.get("original_summary") is not True
                or not review.get("usage_review")
                or not review.get("scope")
            ):
                return None
        elif kind != "synthetic":
            return None
        approved = dict(record)
        approved.update(
            citation_handle=citation_handle(record),
            source_kind=kind,
            authority="Reviewed public SAP summary"
            if kind == "public_sap"
            else "DEMO / SIMULATED — not SAP documentation",
            source_url=review.get("source_url") if kind == "public_sap" else None,
            applicability=review.get("scope", "DEMO only"),
            reviewed=True,
        )
        return approved


def grounding_failure(answer: str, results: list[dict[str, Any]]) -> bool:
    """Structural checks, not a semantic proof of SAP factual correctness."""
    allowed = {item["citation_handle"] for item in results}
    cited = set(re.findall(r"\[(SRC-[^\]\s]+)\]", answer))
    if not cited or not cited <= allowed:
        return True
    public_handles = {
        item["citation_handle"]
        for item in results
        if item.get("source_kind") == "public_sap"
    }
    if not cited & public_handles:
        return True
    # Require each non-heading claim paragraph/list line to carry a source.
    # This deliberately over-abstains; it cannot establish textual entailment.
    for paragraph in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\d+\.)\s)", answer):
        claim = re.sub(r"(?m)^\s*#+[^\n]*$", "", paragraph).strip()
        if claim and not re.search(r"\[SRC-[^\]\s]+\]", claim):
            return True
        paragraph_handles = set(re.findall(r"\[(SRC-[^\]\s]+)\]", claim))
        if paragraph_handles - public_handles and not re.search(
            r"\b(?:DEMO|SIMULATED)\b", claim
        ):
            return True
    approved_urls = {
        item.get("source_url") for item in results if item.get("source_url")
    }
    urls = re.findall(r"https?://[^\s<>()\[\]]+", answer)
    if any(url.rstrip(".,;") not in approved_urls for url in urls):
        return True
    if any(
        not 1 <= int(number) <= len(results)
        for number in re.findall(r"\bDocument\s+(\d+)\b", answer)
    ):
        return True
    # Protect against fabricated code-shaped identifiers. Recognition is syntax,
    # not a SAP catalog lookup. Tables/procedural entailment still need review.
    evidence = "\n".join(item.get("content", "") for item in results).upper()
    without_citations = re.sub(r"\[SRC-[^\]]*\]", "", answer)
    codes = re.findall(r"\b[A-Z]{1,8}\d{2,}[A-Z0-9_]*\b", without_citations.upper())
    generic = {"SAP", "DEMO", "SIMULATED", "FFC", "LLM", "RAG", "API", "PDF", "CSV"}
    codes += [
        token
        for token in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", without_citations)
        if token not in generic
    ]
    if any(not re.search(rf"\b{re.escape(code)}\b", evidence) for code in codes):
        return True
    if re.search(
        r"\b(?:I|we)\s+(?:have\s+)?(?:executed|posted|released|accessed|connected to)\b",
        answer,
        re.I,
    ):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*%", answer):
        return True
    return False


def evidence_refusal(query: str, retrieval: dict[str, Any]) -> str | None:
    # Production SemanticRetriever always supplies this versioned contract.
    # Older isolated test doubles do not exercise the Stage 4 evidence layer.
    if retrieval.get("evidence_contract") != 1:
        return None
    if re.search(r"\bFFC\b|Fauji Fertilizer", query, re.I):
        return INSUFFICIENT
    if not re.search(
        r"\b(?:DEMO|SIMULATED|SYNTHETIC|FICTIONAL)\b", query, re.I
    ) and re.search(
        r"\b(?:our|company|internal|corporate)\b.{0,100}\b(?:polic\w*|approval limit|supplier\w*|price\w*|employee\w*|approver\w*|role assignment\w*)\b",
        query,
        re.I,
    ):
        return INSUFFICIENT
    results = retrieval.get("results", [])
    if not results or not any(
        item.get("source_kind") == "public_sap" for item in results
    ):
        return INSUFFICIENT
    if retrieval.get("contradiction"):
        return INSUFFICIENT
    return None
