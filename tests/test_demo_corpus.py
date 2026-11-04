"""Offline Stage 5 preparation QA. No actual candidate is approved or ingested."""

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from urllib.parse import urlsplit

import pytest

from demo_corpus.prepare_manifest import DIRECTORY, prepare
from rag.evidence import SourcePolicy, citation_handle, evidence_refusal, record_digest
from rag.retriever.retriever import SemanticRetriever

ROOT = DIRECTORY.parent
CANDIDATES = json.loads((DIRECTORY / "candidates.json").read_text(encoding="utf-8"))[
    "records"
]
SCENARIOS = json.loads((DIRECTORY / "scenarios.json").read_text(encoding="utf-8"))[
    "scenarios"
]
RECORDS, MANIFEST = prepare()


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda item: item["candidate_id"])
def test_public_candidates_provenance_scope_and_pending_review(candidate):
    assert urlsplit(candidate["source_url"]).hostname == "help.sap.com"
    assert urlsplit(candidate["source_url"]).scheme == "https"
    assert candidate["document_title"] and candidate["source_sections"]
    assert candidate["product"] and candidate["version"]
    assert (
        candidate["summary"] and candidate["prerequisites"] and candidate["limitations"]
    )
    assert candidate["human_approved"] is False
    assert (
        candidate["human_reviewer"] is None and candidate["human_review_date"] is None
    )
    assert candidate["usage_review"] == "pending"
    assert (
        "indexed_article_extract_only" in candidate["evidence_access"]
        or "direct_article_body_read" in candidate["evidence_access"]
    )
    prepared = next(item for item in RECORDS if item["id"] == candidate["candidate_id"])
    assert prepared["metadata"]["research_date"] == "2026-11-03"
    assert prepared["metadata"]["source_url"] == candidate["source_url"]
    assert candidate["version"] in prepared["content"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["scenario_id"])
def test_synthetic_scenarios_are_labeled_and_have_no_documented_error_codes(scenario):
    assert scenario["scenario_id"].startswith("DEMO-")
    for key in [
        "title",
        "company",
        "supplier",
        "material",
        "document_number",
        "fictional_observation",
        "simulated_outcome",
    ]:
        assert "DEMO" in scenario[key]
    assert scenario["simulated_error_message"].startswith("SIMULATED:")
    assert scenario["documented_error_codes"] == []
    assert scenario["human_approved"] is False
    assert scenario["expected_behavior"] and scenario["forbidden_claims"]
    assert set(scenario["candidate_references"]) <= {
        item["candidate_id"] for item in CANDIDATES
    }


def test_all_six_requested_modules_are_present_in_both_sets():
    required = {"MM", "SD", "FI", "PP", "QM", "WM"}
    assert required <= {item["module"] for item in CANDIDATES}
    assert required <= {item["module"] for item in SCENARIOS}


def test_manifest_is_deterministic_and_matches_saved_artifacts():
    assert prepare() == (RECORDS, MANIFEST)
    assert (
        json.loads((DIRECTORY / "prepared_records.json").read_text(encoding="utf-8"))[
            "records"
        ]
        == RECORDS
    )
    assert (
        json.loads((DIRECTORY / "review_manifest.json").read_text(encoding="utf-8"))
        == MANIFEST
    )
    assert len(RECORDS) == len(MANIFEST["records"]) == 26
    assert len({item["id"] for item in RECORDS}) == 26


@pytest.mark.parametrize("record", RECORDS, ids=lambda item: item["id"])
def test_prepared_record_identity_matches_real_normalizer_and_fails_approval(record):
    retriever = SemanticRetriever.__new__(SemanticRetriever)
    normalized = retriever._normalize_match(
        {"id": record["id"], "score": 0.9, "metadata": record["metadata"]}
    )
    digest = record_digest(record)
    assert record_digest(normalized) == digest
    entry = MANIFEST["records"][digest]
    assert entry["citation_handle"] == citation_handle(normalized)
    assert entry["reviewed"] is False and entry["usage_review"] == ""
    assert entry["human_reviewer"] is None
    assert SourcePolicy(MANIFEST["records"]).approve(normalized) is None
    assert SourcePolicy().approve(normalized) is None


def test_runtime_registry_remains_empty():
    assert (
        json.loads((ROOT / "rag/approved_sources.json").read_text(encoding="utf-8"))[
            "records"
        ]
        == {}
    )


def test_pending_candidates_and_approved_test_fixture_are_distinct():
    # An isolated fictional fixture exercises the positive contract; this is
    # neither a candidate approval nor a write to any review registry.
    fixture = {"id": "TEST_ONLY", "content": "DEMO / SIMULATED fixture", "metadata": {}}
    policy = SourcePolicy(
        {record_digest(fixture): {"reviewed": True, "kind": "synthetic"}}
    )
    assert policy.approve(fixture)["source_kind"] == "synthetic"
    assert policy.approve(RECORDS[0]) is None
    assert all(entry["reviewed"] is False for entry in MANIFEST["records"].values())


def test_content_and_applicability_tampering_changes_citation_identity():
    original = RECORDS[0]
    altered = deepcopy(original)
    altered["metadata"]["version"] = "UNVERIFIED_OTHER_RELEASE"
    assert record_digest(altered) not in MANIFEST["records"]
    assert citation_handle(altered) != citation_handle(original)
    altered = deepcopy(original)
    altered["content"] += " UNREVIEWED ADDITION"
    assert record_digest(altered) not in MANIFEST["records"]


def test_duplicate_screen_preserves_distinct_applicability():
    retriever = SemanticRetriever.__new__(SemanticRetriever)
    original = deepcopy(RECORDS[0])
    duplicate = deepcopy(original)
    duplicate["id"] = "DEMO_DUPLICATE"
    assert len(retriever._dedupe_results([original, duplicate])) == 1
    duplicate["metadata"]["version"] = "DIFFERENT_RELEASE"
    assert len(retriever._dedupe_results([original, duplicate])) == 2
    summaries = [" ".join(item["summary"].lower().split()) for item in CANDIDATES]
    assert len(set(summaries)) == len(summaries)


@pytest.mark.parametrize(
    "query",
    [
        "What is FFC's purchase order approval limit?",
        "Which FFC employee approves my order?",
        "What is our company supplier price?",
    ],
)
def test_company_questions_cannot_use_generic_public_evidence(query):
    # Deliberately unrelated attestation fixture, not an approved real source.
    result = evidence_refusal(
        query, {"evidence_contract": 1, "results": [{"source_kind": "public_sap"}]}
    )
    assert result and "FFC" in result


def test_legacy_csvs_match_preparation_checksums():
    inventory = json.loads(
        (DIRECTORY / "legacy_inventory.json").read_text(encoding="utf-8")
    )
    assert sum(item["rows"] for item in inventory["files"].values()) == 3079
    for filename, entry in inventory["files"].items():
        assert (
            hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
            == entry["sha256"]
        )


def test_all_existing_40_queries_have_explicit_content_mapping():
    mapping = json.loads(
        (DIRECTORY / "evaluation_mapping.json").read_text(encoding="utf-8")
    )
    baseline_ids = re.findall(
        r"(?m)^\| (R\d\d) \|", (ROOT / "RAG_EVALUATION.md").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in mapping["queries"]] == baseline_ids
    ids = {item["candidate_id"] for item in CANDIDATES}
    for item in mapping["queries"] + mapping["supplemental"]:
        assert set(item["candidates"]) <= ids
    counts = Counter(item["category"] for item in mapping["queries"])
    assert counts == {
        "narrow": 9,
        "partial": 11,
        "gap": 15,
        "ambiguous": 2,
        "unsupported_company_custom": 3,
    }
    assert all(
        not item["candidates"]
        for item in mapping["queries"]
        if item["category"] == "unsupported_company_custom"
    )


def test_unresolved_product_version_is_not_turned_into_a_verified_release():
    candidate = next(
        item for item in CANDIDATES if item["candidate_id"] == "SAP-BC-001"
    )
    assert "Not established" in candidate["version"]
    entry = MANIFEST["records"][
        record_digest(next(item for item in RECORDS if item["id"] == "SAP-BC-001"))
    ]
    assert "Not established" in entry["scope"] and entry["reviewed"] is False
