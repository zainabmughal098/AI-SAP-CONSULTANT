"""Offline revision identities and pending-review boundaries, not SAP certification."""

import hashlib
import json
from copy import deepcopy
from urllib.parse import urlsplit

import pytest

from demo_corpus.prepare_stage6b import DIRECTORY, prepare
from rag.evidence import SourcePolicy, citation_handle, record_digest
from rag.retriever.retriever import SemanticRetriever

ROOT = DIRECTORY.parents[1]
RECORDS, MANIFEST = prepare()
CANDIDATES = json.loads((DIRECTORY / "candidates.json").read_text(encoding="utf-8"))[
    "records"
]
SCENARIOS = json.loads((DIRECTORY / "scenarios.json").read_text(encoding="utf-8"))[
    "scenarios"
]


def test_original_inputs_and_empty_runtime_registry_preserved():
    inventory = json.loads(
        (DIRECTORY / "preserved_inputs.json").read_text(encoding="utf-8")
    )["sha256"]
    assert len(inventory) == 18
    for filename, digest in inventory.items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest, (
            filename
        )
    assert (
        json.loads((ROOT / "rag/approved_sources.json").read_text(encoding="utf-8"))[
            "records"
        ]
        == {}
    )


def test_reproducible_revision_package_matches_saved_files():
    assert len(RECORDS) == len(MANIFEST["records"]) == 13
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
    assert len({record["id"] for record in RECORDS}) == 13
    assert len({citation_handle(record) for record in RECORDS}) == 13


@pytest.mark.parametrize("record", RECORDS, ids=lambda item: item["id"])
def test_real_normalizer_preserves_identity_and_pending_admission(record):
    retriever = SemanticRetriever.__new__(SemanticRetriever)
    normalized = retriever._normalize_match(
        {"id": record["id"], "score": 0.87, "metadata": deepcopy(record["metadata"])}
    )
    assert normalized["content"] == record["metadata"]["text"] == record["content"]
    assert record_digest(normalized) == record_digest(record)
    assert citation_handle(normalized) == citation_handle(record)
    assert SourcePolicy(MANIFEST["records"]).approve(normalized) is None
    assert SourcePolicy().approve(normalized) is None
    entry = MANIFEST["records"][record_digest(record)]
    assert entry["reviewed"] is False and entry["usage_review"] == ""
    assert entry["human_reviewer"] is None and entry["human_review_date"] is None
    assert entry["citation_handle"] == citation_handle(record)


@pytest.mark.parametrize("record", RECORDS, ids=lambda item: item["id"])
def test_flat_metadata_and_draft_lineage_for_future_adapter(record):
    assert len(json.dumps(record["metadata"]).encode("utf-8")) < 40000
    assert all(
        isinstance(value, str)
        or (isinstance(value, list) and all(isinstance(part, str) for part in value))
        for value in record["metadata"].values()
    )
    entry = MANIFEST["records"][record_digest(record)]
    old = json.loads(
        (DIRECTORY.parent / "review_manifest.json").read_text(encoding="utf-8")
    )["records"]
    assert (
        entry["parent_draft_hashes"] and set(entry["parent_draft_hashes"]) <= old.keys()
    )
    assert record_digest(record) not in entry["parent_draft_hashes"]
    changed = deepcopy(record)
    changed["metadata"]["version"] = "changed scope"
    assert record_digest(changed) != record_digest(record)


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda item: item["candidate_id"])
def test_source_and_scope_are_explicit_without_catalog_inference(candidate):
    assert urlsplit(candidate["source_url"]).hostname == "help.sap.com"
    assert candidate["human_approved"] is False
    assert candidate["usage_review"] == "pending"
    assert candidate["claims"] and all(
        claim["status"] == "supported" and claim["locator"]
        for claim in candidate["claims"]
    )
    assert candidate["troubleshooting_steps"] == []
    if candidate["module"] == "SD":
        assert "ERP" in candidate["product"] and "EHP7 SPS06" in candidate["version"]
        assert candidate["transaction_codes"] == ["VA03"]
    else:
        assert candidate["product"] == "SAP S/4HANA on-premise"
        assert "FPS02" in candidate["version"] and "FPS01" not in candidate["version"]
        assert candidate["transaction_codes"] == candidate["app_ids"] == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["scenario_id"])
def test_revised_scenarios_are_fictional_scoped_and_unapproved(scenario):
    assert scenario["human_approved"] is False
    assert scenario["human_reviewer"] is None
    assert scenario["scenario_id"].endswith("-6B")
    assert scenario["simulated_error_message"].startswith("SIMULATED:")
    assert scenario["documented_error_codes"] == []
    for field in [
        "company",
        "supplier",
        "material",
        "document_number",
        "product_context",
        "expected_behavior",
    ]:
        assert "DEMO" in scenario[field]
    assert set(scenario["candidate_references"]) <= {
        candidate["candidate_id"] for candidate in CANDIDATES
    }
    assert scenario["review_disposition"]


def test_no_exact_repeated_public_summaries():
    summaries = [
        " ".join(candidate["summary"].lower().split()) for candidate in CANDIDATES
    ]
    assert len(set(summaries)) == len(summaries)
