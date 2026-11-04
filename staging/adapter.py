"""Pure offline adapter for immutable, reviewed staging envelopes.

No network, provider imports, .env loading, source approval or registry writes.
Approval evidence is externally supplied, not authenticated by these checks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from rag.evidence import SourcePolicy, citation_handle, record_digest

ROOT = Path(__file__).resolve().parents[1]
HASH = re.compile(r"[0-9a-f]{64}")
UNRESOLVED = re.compile(
    r"\b(?:unknown|unverified|pending|unspecified|unresolved|latest|tbd)\b", re.I
)


class ValidationError(ValueError):
    """Only safe machine codes are exposed, never record bodies or credentials."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    ).hexdigest()


def load_json(path: Path) -> Any:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError("duplicate_json_key")
            result[key] = value
        return result

    def bad_constant(_):
        raise ValidationError("nonfinite_json_number")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_pairs,
        parse_constant=bad_constant,
    )


def _present(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value.strip()) and not UNRESOLVED.search(value)
    )


def validate_records(records: list[dict], manifest: dict) -> None:
    """Identity/metadata validation, separate from permission to use the records."""
    if not isinstance(records, list) or not records:
        raise ValidationError("empty_or_invalid_records")
    entries = manifest.get("records") if isinstance(manifest, dict) else None
    if not isinstance(entries, dict):
        raise ValidationError("invalid_manifest")
    ids, digests, handles = set(), set(), set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"id", "content", "metadata"}:
            raise ValidationError("invalid_record_envelope")
        identifier, content, metadata = (
            record["id"],
            record["content"],
            record["metadata"],
        )
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}", identifier
        ):
            raise ValidationError("invalid_record_id")
        if identifier in ids:
            raise ValidationError("duplicate_record_id")
        ids.add(identifier)
        if (
            not isinstance(content, str)
            or not content.strip()
            or not isinstance(metadata, dict)
        ):
            raise ValidationError("invalid_content_or_metadata")
        if not all(
            isinstance(key, str)
            and key
            and (
                isinstance(value, str)
                or (
                    isinstance(value, list)
                    and all(isinstance(part, str) for part in value)
                )
            )
            for key, value in metadata.items()
        ):
            raise ValidationError("metadata_not_flat_strings")
        if {
            "reviewed",
            "human_approved",
            "authority",
            "source_kind",
            "citation_handle",
        } & metadata.keys():
            raise ValidationError("self_attested_metadata")
        if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 40000:
            raise ValidationError("metadata_too_large")
        if metadata.get("text") != content:
            raise ValidationError("metadata_text_mismatch")
        for field in (
            "source_file",
            "identifier",
            "document_number",
            "title",
            "module",
        ):
            if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                raise ValidationError("missing_source_identity")
        if metadata["identifier"] != identifier:
            raise ValidationError("identifier_mismatch")
        digest, handle = record_digest(record), citation_handle(record)
        entry = entries.get(digest)
        if not isinstance(entry, dict):
            raise ValidationError("record_hash_not_in_manifest")
        if (
            entry.get("candidate_id") != identifier
            or entry.get("citation_handle") != handle
        ):
            raise ValidationError("manifest_identity_mismatch")
        if digest in digests or handle in handles:
            raise ValidationError("duplicate_identity")
        digests.add(digest)
        handles.add(handle)
        kind = entry.get("kind")
        if kind == "public_sap":
            if metadata.get("document_type") != "public_sap_summary":
                raise ValidationError("source_kind_mismatch")
            for field in ("product", "version", "source_title"):
                if not _present(metadata.get(field)):
                    raise ValidationError("unresolved_public_applicability")
            product, version = metadata["product"], metadata["version"]
            if product == "SAP S/4HANA on-premise":
                scoped = re.search(
                    r"\b20\d{2}\s+FPS\d{2}\b", version
                ) and not re.search(r"Cloud|EHP", version, re.I)
            elif product == "SAP ERP 6.0 with SAP Fiori for SAP ERP":
                scoped = re.search(r"\bEHP\d+\s+SPS\d+\b", version) and not re.search(
                    r"Cloud|FPS", version, re.I
                )
            elif product == "SAP S/4HANA Cloud Public Edition":
                scoped = re.search(r"\b\d{4}\b", version) and not re.search(
                    r"EHP|FPS|on-premise", version, re.I
                )
            else:
                scoped = False
            if not scoped:
                raise ValidationError("unsupported_or_mixed_product_scope")
            sections = metadata.get("source_sections")
            if (
                not isinstance(sections, list)
                or not sections
                or not all(_present(part) for part in sections)
            ):
                raise ValidationError("missing_source_locator")
            url = metadata.get("source_url")
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                valid_url = (
                    parsed
                    and parsed.scheme == "https"
                    and parsed.hostname == "help.sap.com"
                    and not parsed.username
                    and not parsed.password
                    and parsed.port in (None, 443)
                )
            except ValueError:
                valid_url = False
            if not valid_url or entry.get("source_url") != url:
                raise ValidationError("source_url_mismatch_or_disallowed")
            if entry.get("scope") != f"{metadata['product']} | {metadata['version']}":
                raise ValidationError("scope_mismatch")
        elif kind == "synthetic":
            if (
                metadata.get("document_type") != "synthetic_scenario"
                or entry.get("source_url") is not None
            ):
                raise ValidationError("source_kind_mismatch")
            if (
                metadata.get("data_classification") != "DEMO / SIMULATED"
                or not identifier.startswith("DEMO-")
                or not metadata["document_number"].startswith("DEMO_")
            ):
                raise ValidationError("missing_synthetic_label")
            if (
                not content.startswith("DEMO / SIMULATED:")
                or "fictional" not in content.lower()
                or "no live SAP operation" not in content
            ):
                raise ValidationError("missing_synthetic_boundary")
            if entry.get("scope") != "DEMO / SIMULATED only":
                raise ValidationError("synthetic_scope_mismatch")
        else:
            raise ValidationError("unsupported_source_kind")
    if set(entries) != digests:
        raise ValidationError("manifest_record_set_mismatch")


def approval_blockers(record: dict, entry: dict) -> list[str]:
    blockers = []
    if entry.get("reviewed") is not True:
        blockers.append("pending_human_review")
    for field in (
        "factual_review",
        "applicability_review",
        "safety_review",
        "usage_review",
    ):
        if entry.get(field) != "approved":
            blockers.append(field + "_not_approved")
    for field in ("human_reviewer", "review_reference"):
        if not _present(entry.get(field)):
            blockers.append(field + "_missing")
    try:
        reviewed_on = date.fromisoformat(entry.get("human_review_date", ""))
        if reviewed_on > date.today():
            blockers.append("review_date_in_future")
    except (TypeError, ValueError):
        blockers.append("review_date_missing_or_invalid")
    if entry.get("original_summary") is not True:
        blockers.append("original_summary_not_confirmed")
    if (
        not blockers
        and SourcePolicy({record_digest(record): entry}).approve(record) is None
    ):
        blockers.append("runtime_source_policy_rejected")
    return blockers


def target_blockers(config: dict) -> list[str]:
    """Explicit inventory + exact allowlist; no environment/default target fallback."""
    blockers = []
    if config.get("mode") != "offline-only":
        blockers.append("unsupported_operation_mode")
    target, inventory = config.get("target", {}), config.get("production_inventory", {})
    keys = ("project", "index", "host", "namespace")
    if not all(_present(target.get(key)) for key in keys):
        return blockers + ["staging_target_unconfigured"]
    if not target["index"].startswith("demo-staging-") or not target[
        "namespace"
    ].startswith("demo-staging-"):
        blockers.append("staging_name_required")
    if not re.fullmatch(r"[a-z0-9.-]+\.pinecone\.io", target["host"]):
        blockers.append("invalid_target_host")
    if target not in config.get("staging_allowlist", []) or not _present(
        config.get("target_review_reference")
    ):
        blockers.append("target_not_explicitly_reviewed")
    if (
        inventory.get("reviewed") is not True
        or not _present(inventory.get("reference"))
        or not all(
            isinstance(inventory.get(key), list)
            and inventory[key]
            and all(_present(item) for item in inventory[key])
            for key in ("projects", "indexes", "hosts")
        )
    ):
        blockers.append("production_inventory_unverified")
    for key, collection in (
        ("project", "projects"),
        ("index", "indexes"),
        ("host", "hosts"),
    ):
        if target[key].casefold() in {
            value.casefold()
            for value in inventory.get(collection, [])
            if isinstance(value, str)
        }:
            blockers.append("production_target_forbidden")
    return sorted(set(blockers))


def embedding_blockers(config: dict, records: list[dict]) -> list[str]:
    spec = config.get("embedding", {})
    query, document = spec.get("query", {}), spec.get("document", {})
    blockers = []
    if (
        spec.get("expected_model") != "all-MiniLM-L6-v2"
        or type(spec.get("expected_dimension")) is not int
        or spec["expected_dimension"] != 384
    ):
        blockers.append("configured_encoder_contract_changed")
    fields = (
        "model",
        "revision",
        "dimension",
        "pooling",
        "normalize",
        "tokenizer_revision",
        "max_tokens",
        "preprocessing",
    )
    for encoder in (query, document):
        if (
            not all(
                _present(encoder.get(key))
                for key in (
                    "model",
                    "revision",
                    "pooling",
                    "tokenizer_revision",
                    "preprocessing",
                )
            )
            or type(encoder.get("normalize")) is not bool
            or type(encoder.get("max_tokens")) is not int
            or encoder["max_tokens"] <= 0
        ):
            blockers.append("encoder_details_unverified")
        if (
            encoder.get("model") != spec.get("expected_model")
            or type(encoder.get("dimension")) is not int
            or encoder["dimension"] != 384
        ):
            blockers.append("encoder_identity_or_dimension_mismatch")
    if any(query.get(key) != document.get(key) for key in fields):
        blockers.append("query_document_encoder_mismatch")
    if not _present(spec.get("verification_reference")):
        blockers.append("encoder_equivalence_unverified")
    observed = spec.get("index_observation", {})
    if (
        spec.get("proposed_metric") != "cosine"
        or observed.get("metric") != "cosine"
        or type(observed.get("dimension")) is not int
        or observed["dimension"] != 384
        or not _present(observed.get("reference"))
        or observed.get("target") != config.get("target")
    ):
        blockers.append("index_dimension_metric_unverified_or_mismatched")
    counts = spec.get("token_counts", {})
    for record in records:
        count = counts.get(record_digest(record))
        if type(count) is not int or count <= 0:
            blockers.append("record_token_count_unverified")
        elif type(document.get("max_tokens")) is int and count > document["max_tokens"]:
            blockers.append("record_would_be_truncated")
    return sorted(set(blockers))


def dry_run(records: list[dict], manifest: dict, config: dict) -> dict:
    validate_records(records, manifest)
    items = [
        {
            "id": record["id"],
            "hash": record_digest(record),
            "citation_handle": citation_handle(record),
            "blockers": approval_blockers(
                record, manifest["records"][record_digest(record)]
            ),
        }
        for record in records
    ]
    targets, embeddings = target_blockers(config), embedding_blockers(config, records)
    return {
        "mode": "offline-only",
        "structurally_valid": True,
        "record_count": len(records),
        "records": items,
        "target_blockers": targets,
        "embedding_blockers": embeddings,
        "eligible_for_payload": not targets
        and not embeddings
        and not any(item["blockers"] for item in items),
        "package_hash": canonical_hash(
            {"records": records, "manifest": manifest, "config": config}
        ),
        "provider_calls": 0,
        "writes": 0,
    }


def admit_context(records: list[dict], manifest: dict) -> list[dict]:
    """Separate staging admission, never edits or relaxes the runtime registry."""
    validate_records(records, manifest)
    policy = SourcePolicy(manifest["records"])
    return [
        policy.approve(record)
        for record in records
        if not approval_blockers(record, manifest["records"][record_digest(record)])
    ]


def prepare_payload(
    records: list[dict], manifest: dict, config: dict, vectors: dict[str, dict]
) -> dict:
    """Compile an in-memory payload only. There is deliberately no send method."""
    report = dry_run(records, manifest, config)
    if not report["eligible_for_payload"]:
        raise ValidationError("release_blocked")
    if not isinstance(vectors, dict) or set(vectors) != {
        record["id"] for record in records
    }:
        raise ValidationError("vector_record_set_mismatch")
    payload = []
    for record in records:
        artifact = vectors[record["id"]]
        if (
            not isinstance(artifact, dict)
            or artifact.get("record_hash") != record_digest(record)
            or artifact.get("encoder_spec_hash")
            != canonical_hash(config["embedding"]["document"])
        ):
            raise ValidationError("vector_input_or_encoder_hash_mismatch")
        vector = artifact.get("values")
        if (
            not isinstance(vector, list)
            or len(vector) != 384
            or any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in vector
            )
        ):
            raise ValidationError("invalid_sentence_vector")
        norm = math.hypot(*vector)
        if (
            not math.isfinite(norm)
            or norm == 0
            or (config["embedding"]["document"]["normalize"] and abs(norm - 1) > 1e-5)
        ):
            raise ValidationError("vector_norm_mismatch")
        payload.append(
            {
                "id": record["id"],
                "values": deepcopy(vector),
                "metadata": deepcopy(record["metadata"]),
            }
        )
    return {
        "target": deepcopy(config["target"]),
        "namespace": config["target"]["namespace"],
        "vectors": payload,
        "package_hash": report["package_hash"],
        "identities": deepcopy(report["records"]),
        "vector_payload_sha256": canonical_hash(payload),
    }


def verify_round_trip(records: list[dict], matches: list[dict]) -> None:
    """Check fetch-shaped fixtures; rank/similarity/vector rounding is not identity."""
    expected = {record["id"]: record for record in records}
    if (
        len(expected) != len(records)
        or not isinstance(matches, list)
        or len(matches) != len(records)
    ):
        raise ValidationError("round_trip_record_set_mismatch")
    seen = set()
    for match in matches:
        identifier, metadata = match.get("id"), match.get("metadata")
        if (
            identifier not in expected
            or identifier in seen
            or not isinstance(metadata, dict)
        ):
            raise ValidationError("round_trip_record_set_mismatch")
        seen.add(identifier)
        restored = {
            "id": identifier,
            "content": metadata.get("text"),
            "metadata": metadata,
        }
        if record_digest(restored) != record_digest(
            expected[identifier]
        ) or citation_handle(restored) != citation_handle(expected[identifier]):
            raise ValidationError("round_trip_identity_mismatch")


def prepare_rollback(report: dict, previous_release: dict | None = None) -> dict:
    if not isinstance(report.get("package_hash"), str) or not HASH.fullmatch(
        report["package_hash"]
    ):
        raise ValidationError("invalid_candidate_package_hash")
    previous = None
    if previous_release is not None:
        try:
            checked = dry_run(
                previous_release["records"],
                previous_release["manifest"],
                previous_release["config"],
            )
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValidationError("previous_staging_release_unverified") from exc
        if (
            not checked["eligible_for_payload"]
            or checked["package_hash"] != previous_release.get("package_hash")
            or not _present(previous_release.get("review_reference"))
        ):
            raise ValidationError("previous_staging_release_unverified")
        previous = {
            "package_hash": checked["package_hash"],
            "review_reference": previous_release["review_reference"],
            "target": deepcopy(previous_release["config"]["target"]),
            "restore_matching_registry_encoder_corpus": True,
        }
    return {
        "failed_candidate_package_hash": report["package_hash"],
        "action": "stop_staging_and_restore_previous_package"
        if previous_release
        else "stop_staging_and_return_to_empty_registry",
        "previous_release": previous,
        "runtime_registry_sha256": hashlib.sha256(
            (ROOT / "rag/approved_sources.json").read_bytes()
        ).hexdigest(),
        "cleanup_authorized": False,
        "executed": False,
    }
