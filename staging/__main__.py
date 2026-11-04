"""Dry-run CLI. No credentials, write switch or provider transport exists."""

import argparse
import json
from pathlib import Path

from staging.adapter import ROOT, ValidationError, dry_run, load_json, prepare_rollback


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument(
        "--records",
        type=Path,
        default=ROOT / "demo_corpus/stage6b/prepared_records.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "demo_corpus/stage6b/review_manifest.json",
    )
    parser.add_argument(
        "--config", type=Path, default=ROOT / "staging/offline_config.json"
    )
    args = parser.parse_args(argv)
    try:
        report = dry_run(
            load_json(args.records)["records"],
            load_json(args.manifest),
            load_json(args.config),
        )
        report["rollback_preparation"] = prepare_rollback(report)
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError, OSError):
        print(
            json.dumps(
                {
                    "mode": "offline-only",
                    "structurally_valid": False,
                    "error": "invalid_staging_package",
                    "writes": 0,
                    "provider_calls": 0,
                }
            )
        )
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if report["eligible_for_payload"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
