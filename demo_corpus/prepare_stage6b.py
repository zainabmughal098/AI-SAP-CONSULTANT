"""Build separate, pending Stage 6B review envelopes offline. Never ingest/approve."""

from __future__ import annotations

import json
from pathlib import Path

from rag.evidence import citation_handle, record_digest

DIRECTORY = Path(__file__).resolve().parent / "stage6b"


def prepare() -> tuple[list[dict], dict]:
    candidates = json.loads((DIRECTORY / "candidates.json").read_text(encoding="utf-8"))
    scenarios = json.loads((DIRECTORY / "scenarios.json").read_text(encoding="utf-8"))
    original = json.loads(
        (DIRECTORY.parent / "prepared_records.json").read_text(encoding="utf-8")
    )["records"]
    old_hashes = {record["id"]: record_digest(record) for record in original}
    records, entries = [], {}
    for item in candidates["records"]:
        scope = f"{item['product']} | {item['version']}"
        body = "\n".join(
            [
                f"Topic: {item['topic']}",
                f"Scope (pending human review): {scope}",
                f"Summary: {item['summary']}",
                "Review boundaries: " + " | ".join(item["prerequisites"]),
                "Limitations: " + " | ".join(item["limitations"]),
            ]
        )
        metadata = {
            "source_file": "demo_corpus/stage6b/candidates.json",
            "document_type": "public_sap_summary",
            "module": item["module"],
            "identifier": item["candidate_id"],
            "document_number": item["candidate_id"],
            "title": item["topic"],
            "product": item["product"],
            "version": item["version"],
            "source_url": item["source_url"],
            "source_title": item["document_title"],
            "source_sections": item["source_sections"],
            "transaction_codes": item["transaction_codes"],
            "app_ids": item["app_ids"],
            "research_date": candidates["research_date"],
            "evidence_access": item["evidence_access"],
            "text": body,
        }
        if "page" in item:
            metadata["page"] = item[
                "page"
            ]  # real printed page, string avoids numeric drift
        if len(item["transaction_codes"]) == 1:
            metadata["tcode"] = item["transaction_codes"][0]
        record = {"id": item["candidate_id"], "content": body, "metadata": metadata}
        records.append(record)
        entries[record_digest(record)] = {
            "reviewed": False,
            "kind": "public_sap",
            "source_url": item["source_url"],
            "original_summary": True,
            "usage_review": "",
            "scope": scope,
            "human_reviewer": None,
            "human_review_date": None,
            "review_status": "pending human factual/applicability/usage approval; machine verification is not approval",
            "candidate_id": record["id"],
            "citation_handle": citation_handle(record),
            "parent_draft_hashes": [
                old_hashes[key] for key in item["supersedes_candidates"]
            ],
        }
    for item in scenarios["scenarios"]:
        body = (
            "DEMO / SIMULATED: fictional facilitator script; no live SAP operation.\n"
            + "\n".join(
                [
                    item["title"],
                    item["product_context"],
                    item["fictional_observation"],
                    "Simulated outcome: " + item["simulated_outcome"],
                    "Limits: " + item["expected_behavior"],
                ]
            )
        )
        metadata = {
            "source_file": "demo_corpus/stage6b/scenarios.json",
            "document_type": "synthetic_scenario",
            "identifier": item["scenario_id"],
            "module": item["module"],
            "title": item["title"],
            "document_number": item["document_number"],
            "data_classification": "DEMO / SIMULATED",
            "candidate_references": item["candidate_references"],
            "text": body,
        }
        record = {"id": item["scenario_id"], "content": body, "metadata": metadata}
        records.append(record)
        entries[record_digest(record)] = {
            "reviewed": False,
            "kind": "synthetic",
            "source_url": None,
            "original_summary": True,
            "usage_review": "",
            "scope": "DEMO / SIMULATED only",
            "human_reviewer": None,
            "human_review_date": None,
            "review_status": "pending human safety review",
            "candidate_id": record["id"],
            "citation_handle": citation_handle(record),
            "parent_draft_hashes": [old_hashes[item["parent_scenario_id"]]],
        }
    return records, {
        "description": "PENDING Stage 6B review only; never a runtime registry",
        "records": entries,
    }


if __name__ == "__main__":
    records, manifest = prepare()
    for name, value in [
        (
            "prepared_records.json",
            {"status": "PENDING HUMAN REVIEW; NOT FOR INGESTION", "records": records},
        ),
        ("review_manifest.json", manifest),
    ]:
        (DIRECTORY / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(
        f"Prepared {len(records)} local pending records. Zero approvals or provider operations."
    )
