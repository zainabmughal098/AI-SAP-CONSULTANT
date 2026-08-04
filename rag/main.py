"""Command-line entry point for the semantic retrieval engine."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from rag.retriever.retriever import SemanticRetriever


def parse_filters(filter_items: list[str] | None) -> dict[str, str]:
    filters: dict[str, str] = {}
    if not filter_items:
        return filters

    for item in filter_items:
        if "=" not in item:
            raise ValueError(f"Invalid filter '{item}'. Use key=value format.")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"Invalid filter '{item}'. Use key=value format.")
        filters[key] = value
    return filters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SAP semantic retrieval engine")
    parser.add_argument("query", help="Natural language SAP query")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to retrieve")
    parser.add_argument(
        "--filter",
        action="append",
        dest="filters",
        help="Optional metadata filter in key=value format. Can be used multiple times.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

    retriever = SemanticRetriever()
    result = retriever.retrieve(
        query=args.query,
        filters=parse_filters(args.filters),
        top_k=args.top_k,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
