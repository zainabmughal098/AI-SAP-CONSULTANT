"""Offline contracts. Positive approvals/configs are TEST_ONLY fixtures, not candidates."""

import hashlib
import json
from copy import deepcopy

import pytest

from rag.evidence import citation_handle, record_digest
from staging.__main__ import main
from staging.adapter import (
    ROOT,
    ValidationError,
    admit_context,
    canonical_hash,
    dry_run,
    embedding_blockers,
    load_json,
    prepare_payload,
    prepare_rollback,
    target_blockers,
    validate_records,
    verify_round_trip,
)


def pending_package():
    return (
        load_json(ROOT / "demo_corpus/stage6b/prepared_records.json")["records"],
        load_json(ROOT / "demo_corpus/stage6b/review_manifest.json"),
        load_json(ROOT / "staging/offline_config.json"),
    )


@pytest.fixture
def fixture_package():
    # This record is deliberately NOT any actual source candidate or SAP claim.
    body = "TEST_ONLY schema fixture. No SAP factual claim."
    metadata = {
        "text": body,
        "source_file": "tests/test_staging_adapter.py",
        "identifier": "TEST_ONLY_PUBLIC",
        "document_number": "TEST_ONLY_PUBLIC",
        "title": "TEST_ONLY schema fixture",
        "module": "TEST_ONLY",
        "document_type": "public_sap_summary",
        "product": "SAP S/4HANA on-premise",
        "version": "2025 FPS02",
        "source_title": "TEST_ONLY fixture; not a source summary",
        "source_sections": ["TEST_ONLY schema locator"],
        "source_url": "https://help.sap.com/doc/e2048712f0ab45e791e6d15ba5e20c68",
    }
    record = {"id": "TEST_ONLY_PUBLIC", "content": body, "metadata": metadata}
    entry = {
        "reviewed": True,
        "kind": "public_sap",
        "original_summary": True,
        "source_url": metadata["source_url"],
        "scope": f"{metadata['product']} | {metadata['version']}",
        "candidate_id": record["id"],
        "citation_handle": citation_handle(record),
        "human_reviewer": "TEST_ONLY fictitious reviewer",
        "human_review_date": "2000-01-01",
        "review_reference": "TEST_ONLY fake review reference",
        **{
            key: "approved"
            for key in (
                "factual_review",
                "applicability_review",
                "safety_review",
                "usage_review",
            )
        },
    }
    config = pending_package()[2]
    target = {
        "project": "TEST_ONLY_staging_project",
        "index": "demo-staging-test-only",
        "host": "fixture-staging.svc.example.pinecone.io",
        "namespace": "demo-staging-test-only",
    }
    config.update(
        target=target,
        staging_allowlist=[deepcopy(target)],
        target_review_reference="TEST_ONLY fake target review",
    )
    config["production_inventory"] = {
        "reviewed": True,
        "reference": "TEST_ONLY fictitious inventory",
        "projects": ["TEST_ONLY_prod_project"],
        "indexes": ["TEST_ONLY_prod_index"],
        "hosts": ["fixture-production.svc.example.pinecone.io"],
    }
    encoder = {
        "model": "all-MiniLM-L6-v2",
        "dimension": 384,
        "revision": "TEST_ONLY_revision",
        "pooling": "TEST_ONLY_pooling",
        "normalize": True,
        "tokenizer_revision": "TEST_ONLY_tokenizer",
        "max_tokens": 16,
        "preprocessing": "TEST_ONLY_preprocessing",
    }
    config["embedding"].update(
        query=deepcopy(encoder),
        document=deepcopy(encoder),
        verification_reference="TEST_ONLY fake equivalence",
        index_observation={
            "dimension": 384,
            "metric": "cosine",
            "reference": "TEST_ONLY fake observation",
            "target": deepcopy(target),
        },
        token_counts={record_digest(record): 3},
    )
    return [record], {"records": {record_digest(record): entry}}, config


def rebind(records, manifest):
    """For schema-negative fixtures only; this never changes a saved manifest."""
    entry = deepcopy(next(iter(manifest["records"].values())))
    entry["citation_handle"] = citation_handle(records[0])
    return {"records": {record_digest(records[0]): entry}}


def test_actual_pending_package_is_valid_but_blocked_and_not_admitted():
    records, manifest, config = pending_package()
    before = deepcopy((records, manifest, config))
    report = dry_run(records, manifest, config)
    assert report["structurally_valid"] and report["record_count"] == 13
    assert not report["eligible_for_payload"]
    assert all("pending_human_review" in item["blockers"] for item in report["records"])
    assert report["provider_calls"] == report["writes"] == 0
    assert report["embedding_blockers"] and report["target_blockers"]
    assert admit_context(records, manifest) == []
    with pytest.raises(ValidationError, match="release_blocked"):
        prepare_payload(records, manifest, config, {})
    assert (records, manifest, config) == before


def vector_fixture(records, config, values):
    return {
        records[0]["id"]: {
            "record_hash": record_digest(records[0]),
            "encoder_spec_hash": canonical_hash(config["embedding"]["document"]),
            "values": values,
        }
    }


def test_positive_contract_is_only_an_in_memory_fixture(fixture_package):
    records, manifest, config = fixture_package
    before = deepcopy(fixture_package)
    payload = prepare_payload(
        records, manifest, config, vector_fixture(records, config, [1.0] + [0.0] * 383)
    )
    assert payload["vectors"][0]["metadata"] == records[0]["metadata"]
    assert payload["vectors"][0]["metadata"] is not records[0]["metadata"]
    assert payload["identities"][0]["hash"] == record_digest(records[0])
    assert payload["identities"][0]["citation_handle"] == citation_handle(records[0])
    assert payload["namespace"] == config["target"]["namespace"]
    assert admit_context(records, manifest)[0]["id"] == records[0]["id"]
    verify_round_trip(
        records,
        [
            {
                "id": records[0]["id"],
                "metadata": payload["vectors"][0]["metadata"],
                "score": 0.12,
            }
        ],
    )
    assert fixture_package == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewed", False),
        ("reviewed", "true"),
        ("usage_review", "pending"),
        ("factual_review", "approved-ish"),
        ("applicability_review", None),
        ("safety_review", ""),
        ("human_reviewer", None),
        ("human_review_date", "2999-01-01"),
        ("human_review_date", "bad-date"),
        ("review_reference", "pending"),
        ("original_summary", False),
    ],
)
def test_partial_or_fake_review_shape_is_blocked(fixture_package, field, value):
    records, manifest, config = fixture_package
    next(iter(manifest["records"].values()))[field] = value
    assert not dry_run(records, manifest, config)["eligible_for_payload"]
    assert admit_context(records, manifest) == []
    with pytest.raises(ValidationError, match="release_blocked"):
        prepare_payload(records, manifest, config, {})


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "changed"),
        ("extra", {"nested": "value"}),
        ("extra", True),
        ("extra", float("nan")),
        ("reviewed", "true"),
        ("title", ""),
        ("identifier", "different-id"),
    ],
)
def test_metadata_integrity_rejects_unsafe_shape(fixture_package, field, value):
    records, manifest, _ = fixture_package
    records[0]["metadata"][field] = value
    with pytest.raises(ValidationError):
        validate_records(records, manifest)


@pytest.mark.parametrize(
    "change",
    ["body", "version", "page", "id", "handle", "extra-manifest", "duplicate-id"],
)
def test_hash_and_record_set_mismatches_fail(fixture_package, change):
    records, manifest, _ = fixture_package
    if change == "body":
        records[0]["content"] += " changed"
        records[0]["metadata"]["text"] = records[0]["content"]
    elif change in {"version", "page"}:
        records[0]["metadata"][change] = "changed"
    elif change == "id":
        records[0]["id"] = "CHANGED"
    elif change == "handle":
        next(iter(manifest["records"].values()))["citation_handle"] = "SRC-unknown"
    elif change == "extra-manifest":
        manifest["records"]["a" * 64] = {}
    else:
        records.append(deepcopy(records[0]))
    with pytest.raises(ValidationError):
        validate_records(records, manifest)


@pytest.mark.parametrize(
    "product,version",
    [
        ("SAP S/4HANA on-premise", "Latest"),
        ("SAP S/4HANA Cloud Public Edition", "2025 FPS02"),
        ("SAP S/4HANA on-premise", "2608 Cloud"),
        ("SAP ERP 6.0 with SAP Fiori for SAP ERP", "2025 FPS02"),
        ("Any SAP", "2025 FPS02"),
    ],
)
def test_product_editions_cannot_be_silently_mixed(fixture_package, product, version):
    records, manifest, _ = fixture_package
    records[0]["metadata"].update(product=product, version=version)
    manifest = rebind(records, manifest)
    next(iter(manifest["records"].values()))["scope"] = f"{product} | {version}"
    with pytest.raises(ValidationError):
        validate_records(records, manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_classification", "public"),
        ("document_type", "public_sap_summary"),
        ("document_number", "REAL_NUMBER"),
    ],
)
def test_synthetic_label_cannot_be_removed_even_with_recomputed_hash(field, value):
    records, manifest, _ = pending_package()
    record = deepcopy(records[4])
    entry = manifest["records"][record_digest(record)]
    record["metadata"][field] = value
    entry = deepcopy(entry)
    entry["citation_handle"] = citation_handle(record)
    with pytest.raises(ValidationError):
        validate_records([record], {"records": {record_digest(record): entry}})


@pytest.mark.parametrize(
    "field,collection",
    [("project", "projects"), ("index", "indexes"), ("host", "hosts")],
)
def test_same_production_target_is_rejected_even_with_different_namespace(
    fixture_package, field, collection
):
    _, _, config = fixture_package
    config["production_inventory"][collection] = [config["target"][field].upper()]
    assert "production_target_forbidden" in target_blockers(config)


@pytest.mark.parametrize(
    "change",
    [
        "empty-namespace",
        "unlisted",
        "no-inventory",
        "no-reference",
        "live-mode",
        "bad-host",
        "default-name",
    ],
)
def test_target_protection_fails_closed(fixture_package, change):
    _, _, config = fixture_package
    if change == "empty-namespace":
        config["target"]["namespace"] = ""
    elif change == "unlisted":
        config["staging_allowlist"] = []
    elif change == "no-inventory":
        config["production_inventory"]["reviewed"] = False
    elif change == "no-reference":
        config["target_review_reference"] = None
    elif change == "live-mode":
        config["mode"] = "live"
    elif change == "bad-host":
        config["target"]["host"] = "https://user:secret@example.com/path"
    else:
        config["target"]["index"] = "default"
    assert target_blockers(config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dimension", 768),
        ("dimension", True),
        ("model", "different-model"),
        ("revision", "other-revision"),
        ("normalize", None),
        ("normalize", "false"),
        ("pooling", None),
        ("tokenizer_revision", None),
        ("preprocessing", "different"),
        ("max_tokens", 1),
    ],
)
def test_embedding_mismatch_and_unverified_properties_block(
    fixture_package, field, value
):
    records, _, config = fixture_package
    config["embedding"]["document"][field] = value
    assert embedding_blockers(config, records)


@pytest.mark.parametrize(
    "vector",
    [
        [],
        [True] * 384,
        [float("nan")] * 384,
        [float("inf")] * 384,
        [[0.1] * 384],
        [0.0] * 384,
        [2.0] + [0.0] * 383,
    ],
)
def test_vector_validation_does_not_pool_normalize_or_repair(fixture_package, vector):
    records, manifest, config = fixture_package
    with pytest.raises(ValidationError):
        prepare_payload(
            records, manifest, config, vector_fixture(records, config, vector)
        )


def test_missing_vector_ids_cannot_silently_zip_truncate(fixture_package):
    records, manifest, config = fixture_package
    with pytest.raises(ValidationError, match="vector_record_set_mismatch"):
        prepare_payload(records, manifest, config, {})


def test_explicit_non_normalized_contract_is_not_silently_normalized(fixture_package):
    records, manifest, config = fixture_package
    config["embedding"]["query"]["normalize"] = False
    config["embedding"]["document"]["normalize"] = False
    vector = [2.0] + [0.0] * 383
    payload = prepare_payload(
        records, manifest, config, vector_fixture(records, config, vector)
    )
    assert payload["vectors"][0]["values"] == vector


@pytest.mark.parametrize(
    "dimension,metric",
    [(768, "cosine"), (True, "cosine"), (384, "dotproduct"), (None, None)],
)
def test_observed_index_contract_must_match(fixture_package, dimension, metric):
    records, _, config = fixture_package
    config["embedding"]["index_observation"].update(dimension=dimension, metric=metric)
    assert embedding_blockers(config, records)


def test_previous_release_hash_must_cover_complete_package(fixture_package):
    records, manifest, config = fixture_package
    report = dry_run(records, manifest, config)
    previous = {
        "records": records,
        "manifest": manifest,
        "config": config,
        "package_hash": "a" * 64,
        "review_reference": "TEST_ONLY previous release",
    }
    with pytest.raises(ValidationError, match="previous_staging_release_unverified"):
        prepare_rollback(report, previous)


def test_index_observation_cannot_be_reused_for_another_target(fixture_package):
    records, _, config = fixture_package
    config["embedding"]["index_observation"]["target"]["index"] = (
        "demo-staging-another-target"
    )
    assert embedding_blockers(config, records)


@pytest.mark.parametrize("field", ["record_hash", "encoder_spec_hash"])
def test_stale_embedding_cache_cannot_attach_to_another_record_or_encoder(
    fixture_package, field
):
    records, manifest, config = fixture_package
    vectors = vector_fixture(records, config, [1.0] + [0.0] * 383)
    vectors[records[0]["id"]][field] = "0" * 64
    with pytest.raises(ValidationError, match="vector_input_or_encoder_hash_mismatch"):
        prepare_payload(records, manifest, config, vectors)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "metadata-loss", "text-change", "numeric-page"]
)
def test_round_trip_rejects_changed_or_missing_metadata(change):
    records, _, _ = pending_package()
    records = [records[0]]
    matches = [{"id": records[0]["id"], "metadata": deepcopy(records[0]["metadata"])}]
    if change == "missing":
        matches = []
    elif change == "duplicate":
        matches *= 2
    elif change == "metadata-loss":
        matches[0]["metadata"].pop("source_sections")
    elif change == "numeric-page":
        matches[0]["metadata"]["page"] = 174
    else:
        matches[0]["metadata"]["text"] += " changed"
    with pytest.raises(ValidationError):
        verify_round_trip(records, matches)


def test_rollback_preparation_does_not_execute_or_authorize_cleanup(fixture_package):
    records, manifest, config = fixture_package
    report = dry_run(records, manifest, config)
    empty = prepare_rollback(report)
    assert empty["action"] == "stop_staging_and_return_to_empty_registry"
    assert empty["executed"] is empty["cleanup_authorized"] is False
    previous = {
        "package_hash": report["package_hash"],
        "review_reference": "TEST_ONLY previous release",
        "records": records,
        "manifest": manifest,
        "config": config,
    }
    rollback = prepare_rollback(report, previous)
    assert rollback["previous_release"]["package_hash"] == report["package_hash"]
    assert (
        rollback["previous_release"]["restore_matching_registry_encoder_corpus"] is True
    )
    previous["config"]["production_inventory"]["projects"] = [
        config["target"]["project"]
    ]
    with pytest.raises(ValidationError):
        prepare_rollback(report, previous)


def test_cli_pending_is_distinct_from_invalid_and_cannot_execute(capsys, tmp_path):
    assert main(["--dry-run"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["structurally_valid"] and not result["eligible_for_payload"]
    broken = tmp_path / "broken.json"
    broken.write_text('{"records": [], "records": []}', encoding="utf-8")
    assert main(["--dry-run", "--records", str(broken)]) == 1
    assert "invalid_staging_package" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--dry-run", "--execute"])


def test_hostile_runtime_environment_is_not_used(monkeypatch):
    for name in ("PINECONE_INDEX_NAME", "PINECONE_NAMESPACE", "PINECONE_API_KEY"):
        monkeypatch.setenv(name, "TEST_ONLY_PRODUCTION_DEFAULT")
    records, manifest, config = pending_package()
    assert (
        "staging_target_unconfigured"
        in dry_run(records, manifest, config)["target_blockers"]
    )


def test_nonfinite_and_duplicate_json_input_rejected(tmp_path):
    path = tmp_path / "bad.json"
    for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": 1, "a": 2}'):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValidationError):
            load_json(path)


def test_current_inputs_registry_and_saved_dry_run_remain_consistent():
    snapshot = load_json(ROOT / "staging/input_checksums.json")["sha256"]
    assert len(snapshot) == 7
    for filename, digest in snapshot.items():
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest
    assert load_json(ROOT / "rag/approved_sources.json")["records"] == {}
    records, manifest, config = pending_package()
    report = dry_run(records, manifest, config)
    report["rollback_preparation"] = prepare_rollback(report)
    assert load_json(ROOT / "staging/dry_run_report.json") == report
