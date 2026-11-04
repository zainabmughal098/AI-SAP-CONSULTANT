"""Measured fixture-only retrieval/API benchmark. No SAP accuracy claims."""

from offline_demo.network import install

install()

import json  # noqa: E402
import math  # noqa: E402
import statistics  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from offline_demo.application import create_app  # noqa: E402
from offline_demo.fixtures import FixtureRetriever, records  # noqa: E402
from rag.evidence import citation_handle, record_digest  # noqa: E402

# Frozen, hand-defined fixture relevance labels. Not SAP expert judgments.
QUERIES = [
    ("invoice payment blocked", "invoice"),
    ("payment blocked", "invoice"),
    ("invoice payment", "invoice"),
    ("DEMO invoice", "invoice"),
    ("inspection lot results decision", "inspection"),
    ("inspection results", "inspection"),
    ("lot decision", "inspection"),
    ("DEMO inspection", "inspection"),
    ("goods receipt material", "receipt"),
    ("receipt material", "receipt"),
    ("goods receipt", "receipt"),
    ("DEMO receipt", "receipt"),
    ("purchase order release group code", "release"),
    ("release group", "release"),
    ("release code", "release"),
    ("DEMO release", "release"),
    ("authorization trace object", "authorization"),
    ("authorization user", "authorization"),
    ("trace object", "authorization"),
    ("DEMO authorization", "authorization"),
    ("sales order visibility", "sales"),
    ("sales area", "sales"),
    ("sales visibility", "sales"),
    ("DEMO sales", "sales"),
    ("FFC approval limit", None),
    ("supplier price", None),
    ("employee salary", None),
    ("planet astronomy", None),
    ("tax tolerance configuration", None),
    ("ZFFC_UNKNOWN_999", None),
]


def summary(values):
    ordered = sorted(values)
    return {
        "count": len(values),
        "p50_ms": statistics.median(values),
        "p95_ms_nearest_rank": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "max_ms": max(values),
    }


def evaluate():
    retriever = FixtureRetriever()
    rows, latencies, reciprocal, precision = [], [], [], []
    unsupported_correct = duplicate_count = 0
    for query, relevant in QUERIES:
        start = time.perf_counter()
        results = retriever.search(query, top_k=3)
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)
        ids = [r["id"] for r in results]
        target = f"TEST_ONLY-{relevant}" if relevant else None
        if target:
            reciprocal.append(1 / (ids.index(target) + 1) if target in ids else 0)
            precision.append(
                int(target in ids) / 3
            )  # Fixed denominator, missing ranks=0.
        else:
            unsupported_correct += not ids
        duplicate_count += len(ids) - len(set(ids))
        rows.append(
            {
                "query": query,
                "relevant_fixture_id": target,
                "actual_ids": ids,
                "scores": [r["score"] for r in results],
                "elapsed_ms": elapsed,
            }
        )
    api_rows = []
    with TestClient(create_app()) as client:
        for record in records():
            topic = record["id"].removeprefix("TEST_ONLY-")
            for endpoint in ["/chat", "/chat/stream"]:
                start = time.perf_counter()
                response = client.post(
                    endpoint, json={"query": f"DEMO fixture: {topic}"}
                )
                elapsed = (time.perf_counter() - start) * 1000
                if endpoint.endswith("stream"):
                    events = [
                        json.loads(line[6:])
                        for line in response.text.splitlines()
                        if line.startswith("data: ")
                    ]
                    payload = events[-1]
                else:
                    payload = response.json()
                passed = (
                    response.status_code == 200
                    and "not have enough reviewed" not in payload["answer"]
                    and record["content"] in payload["answer"]
                    and payload["sources"][0]["citation_handle"]
                    == citation_handle(record)
                    and payload.get("context_size", 0) == 0
                )
                api_rows.append(
                    {
                        "fixture_id": record["id"],
                        "endpoint": endpoint,
                        "passed": bool(passed),
                        "elapsed_ms": elapsed,
                    }
                )
    return {
        "label": "TEST_ONLY / DEMO / SIMULATED. Not provider or SAP performance.",
        "encoder": "sha256 bag-of-words, 384 dimensions, L2 unit norm, cosine dot product",
        "fixture_hashes": {r["id"]: record_digest(r) for r in records()},
        "retrieval": {
            "k": 3,
            "cutoff": 0.1,
            "supported_queries": len(reciprocal),
            "unsupported_queries": 6,
            "mrr_at_3": statistics.mean(reciprocal),
            "precision_at_3_fixed_denominator": statistics.mean(precision),
            "recall_at_3_one_relevant_fixture": sum(v > 0 for v in reciprocal)
            / len(reciprocal),
            "unsupported_empty_results": unsupported_correct,
            "duplicate_results": duplicate_count,
            "latency": summary(latencies),
            "cases": rows,
        },
        "api_fixture_correctness": {
            "passed": sum(r["passed"] for r in api_rows),
            "total": len(api_rows),
            "latency": summary([r["elapsed_ms"] for r in api_rows]),
            "cases": api_rows,
        },
    }


if __name__ == "__main__":
    result = evaluate()
    Path(__file__).with_name("evaluation_results.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "retrieval": {
                    k: v for k, v in result["retrieval"].items() if k != "cases"
                },
                "api_fixture_correctness": {
                    k: v
                    for k, v in result["api_fixture_correctness"].items()
                    if k != "cases"
                },
            },
            indent=2,
        )
    )
