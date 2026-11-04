"""Original fictional worksheets, not SAP documentation or approved sources."""

import hashlib
import math
import re
from copy import deepcopy

from rag.evidence import SourcePolicy, citation_handle, record_digest

DIMENSION = 384
LABEL = "TEST_ONLY / DEMO / SIMULATED"
TOPICS = (
    (
        "invoice",
        "MM",
        "invoice payment blocked",
        "Fictional invoice DEMO_INV_101 is reported posted and payment-blocked. Its cause is unknown.",
    ),
    (
        "inspection",
        "QM",
        "inspection lot results decision",
        "Fictional inspection DEMO_LOT_201 has no reported results or decision. No quality judgment is simulated.",
    ),
    (
        "receipt",
        "MM",
        "goods receipt material purchase order",
        "Fictional receipt DEMO_GR_301 has an unavailable error number. No inventory posting is simulated.",
    ),
    (
        "release",
        "MM",
        "purchase order release group code",
        "Fictional purchase order DEMO_PO_401 has an unknown release group and code. No approval limit is supplied.",
    ),
    (
        "authorization",
        "BC",
        "authorization trace object user",
        "Fictional user DEMO_USER_501 has no available trace or authorization object. No role grant is simulated.",
    ),
    (
        "sales",
        "SD",
        "sales order visibility sales area",
        "Fictional sales order DEMO_SO_601 has an unknown sales area. No document lookup is simulated.",
    ),
)


def records():
    return [
        {
            "id": f"TEST_ONLY-{key}",
            "content": f"{LABEL}. {text} No live SAP operation.",
            "metadata": {
                "title": f"{LABEL} {key} worksheet",
                "module": module,
                "keywords": keywords,
                "source_file": "offline_demo/fixtures.py",
                "classification": LABEL,
                "applicability": "Fictional worksheet only; no SAP product applicability",
            },
        }
        for key, module, keywords, text in TOPICS
    ]


def embed(text):
    """Explicit synthetic bag-of-words hashing; NOT MiniLM or semantic equivalence."""
    vector = [0.0] * DIMENSION
    ignored = {
        "the",
        "a",
        "an",
        "is",
        "and",
        "or",
        "no",
        "what",
        "explain",
        "demo",
        "fixture",
        "only",
        "test_only",
    }
    for token in re.findall(r"[a-z0-9_]+", text.lower()):
        if token in ignored:
            continue
        index = (
            int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big")
            % DIMENSION
        )
        vector[index] += 1
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class FixtureRetriever:
    def __init__(self):
        self._records = records()
        self.hashes = {r["id"]: record_digest(r) for r in self._records}
        self.query_processor = self
        self.policy = SourcePolicy(entries={})  # No fixture/source is approved.
        self.last_query = ""
        self.fail_once = False

    @staticmethod
    def clean_query(query):
        return re.sub(r"\s+", " ", query or "").strip()

    def search(self, query, filters=None, top_k=3):
        filters = {
            key: value.upper() if key == "module" and isinstance(value, str) else value
            for key, value in (filters or {}).items()
        }
        query_vector = embed(query)
        ranked = []
        for record in self._records:
            if record_digest(record) != self.hashes[record["id"]]:
                raise ValueError("TEST_ONLY fixture integrity mismatch")
            if filters and any(
                record["metadata"].get(k) != v for k, v in filters.items()
            ):
                continue
            vector = embed(record["metadata"]["keywords"])
            score = sum(a * b for a, b in zip(query_vector, vector, strict=True))
            if score > 0.1:  # Fixed toy cutoff, not a production relevance calibration.
                ranked.append(
                    {
                        **deepcopy(record),
                        "score": score,
                        "citation_handle": citation_handle(record),
                    }
                )
        return sorted(ranked, key=lambda r: (-r["score"], r["id"]))[:top_k]

    def retrieve(self, query, filters=None, top_k=None):
        self.last_query = query
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("TEST_ONLY simulated retrieval outage")
        candidates = self.search(query, filters, top_k or 3)
        admitted = [r for r in candidates if self.policy.approve(r)]
        assert not admitted
        return {
            "results": [],
            "context": "",
            "context_size": 0,
            "evidence_contract": 1,
            "top_k": top_k or 3,
            "filters": filters,
        }


class ForbiddenGenerator:
    def generate(self, **kwargs):
        raise AssertionError("Unapproved fixtures must never reach generation")

    stream = generate
