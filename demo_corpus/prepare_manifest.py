"""Prepare LOCAL pending-review artifacts. No providers, ingestion or approval.

Run from the repository root: python -m demo_corpus.prepare_manifest
Only demo_corpus/prepared_records.json and review_manifest.json are written.
Never writes rag/approved_sources.json or changes any reviewed flag to true.
"""

from __future__ import annotations

import json
from pathlib import Path

from rag.evidence import citation_handle, record_digest

DIRECTORY = Path(__file__).resolve().parent


def prepare() -> tuple[list[dict], dict]:
    research = json.loads((DIRECTORY / "candidates.json").read_text(encoding="utf-8"))
    scenarios = json.loads((DIRECTORY / "scenarios.json").read_text(encoding="utf-8"))
    records, entries = [], {}
    for candidate in research["records"]:
        scope = f"{candidate['product']} | {candidate['version']}"
        body = "\n".join(
            [
                f"Topic: {candidate['topic']}",
                f"Module: {candidate['module']}",
                f"Product applicability (pending human review): {scope}",
                f"Transaction codes: {', '.join(candidate['transaction_codes']) or 'none established'}",
                f"Summary: {candidate['summary']}",
                "Supported diagnostic observations: "
                + " | ".join(
                    candidate["troubleshooting_steps"]
                    or ["No procedural runbook established"]
                ),
                "Prerequisites: " + " | ".join(candidate["prerequisites"]),
                "Limitations: " + " | ".join(candidate["limitations"]),
            ]
        )
        metadata = {
            "source_file": "demo_corpus/candidates.json",
            "document_type": "public_sap_summary",
            "identifier": candidate["candidate_id"],
            "module": candidate["module"],
            "title": candidate["topic"],
            "document_number": candidate["candidate_id"],
            "product": candidate["product"],
            "version": candidate["version"],
            "source_url": candidate["source_url"],
            "source_title": candidate["document_title"],
            "source_sections": candidate["source_sections"],
            "research_date": research["research_date"],
            "evidence_access": candidate["evidence_access"],
            "transaction_codes": candidate["transaction_codes"],
            "app_ids": candidate.get("app_ids", []),
        }
        if len(candidate["transaction_codes"]) == 1:
            metadata["tcode"] = candidate["transaction_codes"][0]
        metadata["text"] = body
        record = {
            "id": candidate["candidate_id"],
            "content": body,
            "metadata": metadata,
        }
        entry = {
            "reviewed": False,
            "kind": "public_sap",
            "source_url": candidate["source_url"],
            "original_summary": True,
            "usage_review": "",
            "scope": scope,
            "human_reviewer": None,
            "human_review_date": None,
            "review_status": "pending factual, applicability, provenance and usage review",
            "candidate_id": candidate["candidate_id"],
            "citation_handle": citation_handle(record),
        }
        records.append(record)
        entries[record_digest(record)] = entry

    for scenario in scenarios["scenarios"]:
        body = (
            "DEMO / SIMULATED — entirely fictional; no live SAP operation.\n"
            + "\n".join(
                f"{key}: {scenario[key]}"
                for key in [
                    "title",
                    "company",
                    "supplier",
                    "material",
                    "document_number",
                    "product_context",
                    "simulated_error_message",
                    "fictional_observation",
                    "simulated_outcome",
                    "expected_behavior",
                ]
            )
        )
        metadata = {
            "source_file": "demo_corpus/scenarios.json",
            "document_type": "synthetic_scenario",
            "identifier": scenario["scenario_id"],
            "module": scenario["module"],
            "title": scenario["title"],
            "document_number": scenario["document_number"],
            "data_classification": "DEMO / SIMULATED",
            "candidate_references": scenario["candidate_references"],
            "research_date": research["research_date"],
        }
        record = {"id": scenario["scenario_id"], "content": body, "metadata": metadata}
        metadata["text"] = body
        records.append(record)
        entries[record_digest(record)] = {
            "reviewed": False,
            "kind": "synthetic",
            "source_url": None,
            "original_summary": True,
            "usage_review": "",
            "scope": "DEMO / SIMULATED only; not SAP documentation",
            "human_reviewer": None,
            "human_review_date": None,
            "review_status": "pending synthetic-data safety review",
            "candidate_id": scenario["scenario_id"],
            "citation_handle": citation_handle(record),
        }
    return records, {
        "description": "DRAFT ONLY. Stage 4-compatible pending entries, not a runtime registry. No approvals authorized.",
        "records": entries,
    }


if __name__ == "__main__":
    prepared, manifest = prepare()
    for filename, value in [
        (
            "prepared_records.json",
            {"status": "PENDING REVIEW — NOT FOR INGESTION", "records": prepared},
        ),
        ("review_manifest.json", manifest),
    ]:
        (DIRECTORY / filename).write_text(
            json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(
        f"Prepared {len(prepared)} local candidates; zero approved. No registry/provider/index changes."
    )
