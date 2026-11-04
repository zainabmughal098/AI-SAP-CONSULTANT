"""Inert readiness application factory; does not import api.main or runtime settings."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from rag.evidence import record_digest
from staging.adapter import ROOT, admit_context, dry_run, load_json
from staging.transport import StagingTransport, binding_hash


def create_app(
    *,
    config_path: Path | None = None,
    connection_path: Path | None = None,
    credentials=None,
    permit=None,
    sender=None,
) -> FastAPI:
    config = load_json(config_path or ROOT / "staging/offline_config.json")
    connection = load_json(connection_path or ROOT / "staging/connection_config.json")
    all_records = load_json(ROOT / "demo_corpus/stage6b/prepared_records.json")[
        "records"
    ]
    all_manifest = load_json(ROOT / "demo_corpus/stage6b/review_manifest.json")
    records = [
        record
        for record in all_records
        if record["id"] in connection["allowed_record_ids"]
    ]
    if len(records) != 2 or {record["id"] for record in records} != set(
        connection["allowed_record_ids"]
    ):
        raise ValueError("Exactly the two selected source records are required")
    manifest = {
        "records": {
            record_digest(record): all_manifest["records"][record_digest(record)]
            for record in records
        }
    }
    transport = StagingTransport(
        records, manifest, config, connection, credentials, permit, sender
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        transport.deactivate()

    app = FastAPI(
        title="AI SAP Consultant — isolated staging readiness", lifespan=lifespan
    )
    app.state.transport = (
        transport  # Explicit Python calls only; no provider HTTP routes.
    )

    @app.get("/health")
    def health():
        return {
            "status": "offline_readiness_only",
            "provider_health": "unverified",
            "live_ready": False,
        }

    @app.get("/readiness")
    def readiness():
        report = dry_run(records, manifest, config)
        report["admitted_records"] = len(admit_context(records, manifest))
        report["network_enabled"] = connection["network_enabled"]
        report["connection_binding_hash"] = binding_hash(
            records, manifest, config, connection
        )
        return report

    return app
