"""Interactive multi-turn SAP consultant chat CLI."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from rag.consultant import SAPConsultant
from rag.main import parse_filters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive SAP consultant chat")
    parser.add_argument(
        "--session-id",
        help="Optional existing session id to continue a conversation",
    )
    parser.add_argument(
        "--filter",
        action="append",
        dest="filters",
        help="Optional metadata filter in key=value format. Can be used multiple times.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieval results")
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    parser.add_argument(
        "--query",
        help="Single-query mode. If omitted, starts an interactive chat session.",
    )
    return parser


def print_response(payload: dict) -> None:
    print("\nAssistant:")
    print(payload["answer"])
    if payload.get("sources"):
        print("\nSources:")
        for index, source in enumerate(payload["sources"], start=1):
            title = source.get("title") or "Unknown"
            module = source.get("module") or "?"
            doc_type = source.get("document_type") or "?"
            score = source.get("score")
            score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "n/a"
            print(f"  {index}. [{doc_type}/{module}] {title} (score: {score_text})")
    print(f"\nSession: {payload.get('session_id')}")


def run_interactive(consultant: SAPConsultant, filters, top_k: int) -> int:
    print("SAP Consultant Chat")
    print("Type your SAP question, or 'exit' / 'quit' to end, 'reset' to clear memory.")
    print(f"Session: {consultant.memory.session_id}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            return 0
        if user_input.lower() == "reset":
            consultant.reset_conversation()
            print("Conversation memory and diagnosis state cleared.\n")
            continue

        payload = consultant.ask(user_input, filters=filters, top_k=top_k)
        print_response(payload)
        print()

    return 0


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

    consultant = SAPConsultant()
    if args.session_id:
        consultant.memory = consultant.session_store.get_or_create(
            session_id=args.session_id,
            max_turns=consultant.settings.max_history_turns,
        )

    filters = parse_filters(args.filters)

    if args.query:
        payload = consultant.ask(args.query, filters=filters, top_k=args.top_k)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    return run_interactive(consultant, filters, args.top_k)


if __name__ == "__main__":
    raise SystemExit(main())
