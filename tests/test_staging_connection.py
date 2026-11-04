"""Fake senders/permits only. Actual sources remain pending and are never approved."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from email.message import Message
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from rag.evidence import record_digest
from staging.adapter import ROOT, ValidationError, admit_context, load_json
from staging.application import create_app
from staging.transport import (
    NoRedirect,
    OperationPermit,
    StagingCredentials,
    StagingTransport,
    binding_hash,
    https_json,
    request_hash,
)

PROBE = "DEMO / SIMULATED embedding probe: no SAP facts or business records."


@pytest.fixture
def build_transport():
    def build(response=None, operation="pinecone_describe", mutation=None):
        config = load_json(ROOT / "staging/offline_config.json")
        connection = load_json(ROOT / "staging/connection_config.json")
        records = [
            r
            for r in load_json(ROOT / "demo_corpus/stage6b/prepared_records.json")[
                "records"
            ]
            if r["id"] in connection["allowed_record_ids"]
        ]
        original = load_json(ROOT / "demo_corpus/stage6b/review_manifest.json")
        manifest = {
            "records": {
                record_digest(r): original["records"][record_digest(r)] for r in records
            }
        }
        target = {
            "project": "TEST_ONLY_STAGE",
            "index": "demo-staging-test-only",
            "host": "fixture-staging.svc.example.pinecone.io",
            "namespace": "demo-staging-test-only",
        }
        config.update(
            target=target,
            staging_allowlist=[deepcopy(target)],
            target_review_reference="TEST_ONLY target review",
            production_inventory={
                "reviewed": True,
                "reference": "TEST_ONLY inventory",
                "projects": ["TEST_ONLY_PROD"],
                "indexes": ["TEST_ONLY_PROD"],
                "hosts": ["fixture-prod.svc.example.pinecone.io"],
            },
        )
        credentials = StagingCredentials(
            target["project"], "TEST_ONLY_PINECONE", "TEST_ONLY_EMBED", "TEST_ONLY_GROQ"
        )
        connection.update(
            network_enabled=True,
            endpoint_review_reference="TEST_ONLY endpoint review",
            credential_review_reference="TEST_ONLY credential review",
            production_credential_sha256=["f" * 64],
            credential_sha256={
                key: hashlib.sha256(getattr(credentials, key).encode()).hexdigest()
                for key in ("pinecone", "embedding", "groq")
            },
            embedding_url="https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2",
            allowed_probe_hashes=[hashlib.sha256(PROBE.encode()).hexdigest()],
        )
        requests = {
            "pinecone_describe": (
                "GET",
                "https://api.pinecone.io/indexes/" + target["index"],
                None,
            ),
            "pinecone_stats": (
                "POST",
                f"https://{target['host']}/describe_index_stats",
                {},
            ),
            "pinecone_fetch": (
                "GET",
                f"https://{target['host']}/vectors/fetch?"
                + urlencode(
                    [
                        *(("ids", r["id"]) for r in records),
                        ("namespace", target["namespace"]),
                    ]
                ),
                None,
            ),
            "groq_models": ("GET", "https://api.groq.com/openai/v1/models", None),
            "embedding_probe": (
                "POST",
                connection["embedding_url"],
                {"inputs": PROBE, "options": {"wait_for_model": True}},
            ),
        }
        if mutation:
            mutation(config, connection)
        method, url, body = requests[operation]
        permit = OperationPermit(
            "TEST_ONLY fictional permission, NOT user authorization",
            binding_hash(records, manifest, config, connection),
            frozenset({request_hash(operation, method, url, body)}),
            1,
            "2099-01-01T00:00:00Z",
            1.0,
            "USD",
        )
        calls = []

        def sender(*args):
            calls.append(args)
            if isinstance(response, Exception):
                raise response
            return deepcopy(response)

        transport = StagingTransport(
            records, manifest, config, connection, credentials, permit, sender
        )
        return transport, calls, records, manifest

    return build


def description():
    return {
        "name": "demo-staging-test-only",
        "host": "fixture-staging.svc.example.pinecone.io",
        "dimension": 384,
        "metric": "cosine",
        "status": {"ready": True},
    }


def test_construction_and_default_application_are_inert():
    app = create_app(
        sender=lambda *_: pytest.fail("A readiness app must not call a provider")
    )
    with TestClient(app) as client:
        assert client.get("/health").json()["provider_health"] == "unverified"
        readiness = client.get("/readiness").json()
        assert readiness["record_count"] == 2 and readiness["admitted_records"] == 0
        assert readiness["network_enabled"] is False
        assert client.post("/chat", json={"query": "DEMO"}).status_code == 404
        assert app.state.transport.attempts == 0
        with pytest.raises(ValidationError, match="staging_network_disabled"):
            app.state.transport.describe_index()
    assert app.state.transport.active is False


def test_explicit_fake_read_only_permit_does_not_approve_sources(build_transport):
    transport, calls, records, manifest = build_transport(description())
    assert calls == []
    assert transport.describe_index()["dimension"] == 384
    assert len(calls) == transport.attempts == 1
    assert admit_context(records, manifest) == []
    with pytest.raises(ValidationError, match="exhausted"):
        transport.describe_index()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,collection",
    [("project", "projects"), ("index", "indexes"), ("host", "hosts")],
)
def test_production_collisions_stop_before_sender(build_transport, field, collection):
    def mutation(config, connection):
        config["production_inventory"][collection] = [config["target"][field]]

    transport, calls, _, _ = build_transport(description(), mutation=mutation)
    with pytest.raises(ValidationError):
        transport.describe_index()
    assert calls == []


@pytest.mark.parametrize(
    "change",
    ["missing", "wrong-project", "wrong-key", "production-key", "no-inventory"],
)
def test_credentials_never_fall_back_to_environment(
    build_transport, monkeypatch, change
):
    monkeypatch.setenv("PINECONE_API_KEY", "TEST_ONLY_PINECONE")
    monkeypatch.setenv("GROQ_API_KEY", "TEST_ONLY_GROQ")
    transport, calls, _, _ = build_transport(description())
    if change == "missing":
        transport._credentials = None
    elif change == "wrong-project":
        transport._credentials = replace(
            transport._credentials, project="TEST_ONLY_PROD"
        )
    elif change == "wrong-key":
        transport._credentials = replace(transport._credentials, pinecone="WRONG")
    else:
        connection = transport._connection
        connection["production_credential_sha256"] = (
            [connection["credential_sha256"]["pinecone"]]
            if change == "production-key"
            else []
        )
        transport._permit = replace(
            transport._permit,
            binding_hash=binding_hash(
                transport._records, transport._manifest, transport._config, connection
            ),
        )
    with pytest.raises(ValidationError):
        transport.describe_index()
    assert not calls
    assert "TEST_ONLY_PINECONE" not in repr(
        StagingCredentials("TEST", "TEST_ONLY_PINECONE")
    )


@pytest.mark.parametrize(
    "change",
    ["missing", "hash", "request", "expiry", "budget", "unreviewed", "disabled"],
)
def test_authorization_is_request_package_and_budget_bound(build_transport, change):
    transport, calls, _, _ = build_transport(description())
    if change == "missing":
        transport._permit = None
    elif change == "hash":
        transport._permit = replace(transport._permit, binding_hash="0" * 64)
    elif change == "request":
        transport._permit = replace(transport._permit, request_hashes=frozenset())
    elif change == "expiry":
        transport._permit = replace(
            transport._permit, expires_utc="2000-01-01T00:00:00Z"
        )
    elif change == "budget":
        transport._permit = replace(transport._permit, cost_ceiling=0)
    else:
        transport._connection[
            "endpoint_review_reference" if change == "unreviewed" else "network_enabled"
        ] = None if change == "unreviewed" else False
    with pytest.raises(ValidationError):
        transport.describe_index()
    assert not calls


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {**description(), "host": "fixture-prod.svc.example.pinecone.io"},
        {**description(), "dimension": True},
        {**description(), "metric": "dotproduct"},
        {**description(), "status": {"ready": False}},
    ],
)
def test_malformed_description_deactivates_without_raw_error(build_transport, response):
    transport, calls, _, _ = build_transport(response)
    with pytest.raises(
        ValidationError, match="provider_operation_failed_or_response_invalid"
    ):
        transport.describe_index()
    assert not transport.active and len(calls) == 1
    with pytest.raises(ValidationError, match="disabled"):
        transport.describe_index()
    assert len(calls) == 1


def test_provider_exception_is_sanitized_and_not_retried(build_transport):
    transport, calls, _, _ = build_transport(
        RuntimeError("TEST_ONLY_SECRET provider body")
    )
    with pytest.raises(ValidationError) as exc:
        transport.describe_index()
    assert "SECRET" not in str(exc.value) and len(calls) == 1 and not transport.active


@pytest.mark.parametrize("count", [0, 2, True, -1, "2"])
def test_stats_count_validation(build_transport, count):
    response = {
        "dimension": 384,
        "namespaces": {"demo-staging-test-only": {"vector_count": count}},
    }
    transport, _, _, _ = build_transport(response, "pinecone_stats")
    if type(count) is int and count >= 0:
        assert transport.describe_stats()["vector_count"] == count
    else:
        with pytest.raises(ValidationError):
            transport.describe_stats()


@pytest.mark.parametrize(
    "change", [None, "metadata", "missing-id", "namespace", "vector", "id"]
)
def test_fetch_metadata_round_trip_never_admits_pending_records(
    build_transport, change
):
    transport, calls, records, manifest = build_transport(None, "pinecone_fetch")
    response = {
        "namespace": "demo-staging-test-only",
        "vectors": {
            r["id"]: {
                "id": r["id"],
                "metadata": deepcopy(r["metadata"]),
                "values": [1.0] + [0.0] * 383,
            }
            for r in records
        },
    }
    first = records[0]["id"]
    if change == "metadata":
        response["vectors"][first]["metadata"]["page"] = 169
    elif change == "missing-id":
        response["vectors"].pop(first)
    elif change == "namespace":
        response["namespace"] = "default"
    elif change == "vector":
        response["vectors"][first]["values"] = [True] * 384
    elif change == "id":
        response["vectors"][first]["id"] = "wrong-id"
    transport._sender = lambda *args: calls.append(args) or deepcopy(response)
    if change:
        with pytest.raises(ValidationError):
            transport.fetch_exact()
        assert not transport.active
    else:
        assert transport.fetch_exact()["admitted"] == 0
        assert admit_context(records, manifest) == []


@pytest.mark.parametrize(
    "value",
    [
        [1.0] + [0.0] * 383,
        [],
        [[0.0] * 384],
        [True] * 384,
        [float("nan")] * 384,
        [float("inf")] * 384,
        [0.0] * 384,
        {"error": "TEST_ONLY failure"},
    ],
)
def test_embedding_response_cannot_be_pooled_or_assumed_equivalent(
    build_transport, value
):
    transport, _, _, _ = build_transport(value, "embedding_probe")
    if (
        isinstance(value, list)
        and len(value) == 384
        and type(value[0]) is float
        and value[0] == 1.0
    ):
        assert transport.embedding_probe(PROBE)["encoder_equivalence_verified"] is False
    else:
        with pytest.raises(ValidationError):
            transport.embedding_probe(PROBE)


@pytest.mark.parametrize(
    "value",
    [
        {"data": [{"id": "TEST_ONLY_MODEL"}]},
        {"data": []},
        {"data": [{"id": None}]},
        {"choices": []},
    ],
)
def test_groq_metadata_is_not_an_answer_generation_test(build_transport, value):
    transport, _, _, _ = build_transport(value, "groq_models")
    if value.get("data") and value["data"][0].get("id"):
        assert transport.list_groq_models()["generation_tested"] is False
    else:
        with pytest.raises(ValidationError):
            transport.list_groq_models()


def test_deactivation_is_a_local_stop_not_a_registry_or_index_rollback(build_transport):
    transport, calls, _, _ = build_transport(description())
    transport.deactivate()
    with pytest.raises(ValidationError, match="disabled"):
        transport.describe_index()
    assert calls == []


def test_redirect_is_rejected_instead_of_forwarding_credentials():
    with pytest.raises(ValidationError, match="redirect"):
        NoRedirect().redirect_request(
            None, None, 302, "redirect", {}, "https://example.com"
        )


@pytest.mark.parametrize(
    "namespace",
    [
        {"vectorCount": 2},
        {"vectorCount": 2, "vector_count": 2},
        {"vectorCount": 2, "vector_count": 3},
        {"vectorCount": True},
    ],
)
def test_documented_rest_count_and_conflicting_aliases(build_transport, namespace):
    transport, _, _, _ = build_transport(
        {"dimension": 384, "namespaces": {"demo-staging-test-only": namespace}},
        "pinecone_stats",
    )
    if namespace == {"vectorCount": 2} or namespace == {
        "vectorCount": 2,
        "vector_count": 2,
    }:
        assert transport.describe_stats()["vector_count"] == 2
    else:
        with pytest.raises(ValidationError):
            transport.describe_stats()


@pytest.mark.parametrize(
    "data,content_type,status,limit",
    [
        (b'{"ok":true}', "application/json", 200, 100),
        (b"not-json", "application/json", 200, 100),
        (b'{"x":1,"x":2}', "application/json", 200, 100),
        (b'{"x":NaN}', "application/json", 200, 100),
        (b"{}", "text/html", 200, 100),
        (b"{}", "application/json", 401, 100),
        (b"123456", "application/json", 200, 5),
    ],
)
def test_http_sender_limits_and_strict_json_without_network(
    monkeypatch, data, content_type, status, limit
):
    import staging.transport as module

    class Response:
        def __init__(self):
            self.status = status
            self.headers = Message()
            self.headers["Content-Type"] = content_type

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, count):
            return data[:count]

    class Opener:
        def open(self, request, timeout):
            assert timeout == 10
            return Response()

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: Opener())
    if data == b'{"ok":true}':
        assert https_json("GET", "https://api.pinecone.io/", {}, None, 10, limit) == {
            "ok": True
        }
    else:
        with pytest.raises((ValidationError, json.JSONDecodeError)):
            https_json("GET", "https://api.pinecone.io/", {}, None, 10, limit)


def test_focus_review_package_is_an_exact_pending_subset():
    package = load_json(ROOT / "staging/review/two_source_package.json")
    original = load_json(ROOT / "demo_corpus/stage6b/prepared_records.json")["records"]
    assert package["records"] == [
        r for r in original if r["id"] in {"SAP6B-MM-INV-001", "SAP6B-QM-LOT-001"}
    ]
    assert admit_context(package["records"], package["manifest"]) == []


@pytest.mark.parametrize("change", ["record-hash", "permit-binding"])
def test_changed_record_cannot_reuse_a_review_or_connection_permit(
    build_transport, change
):
    transport, calls, records, manifest = build_transport(description())
    if change == "record-hash":
        broken = deepcopy(records)
        broken[0]["metadata"]["page"] = "CHANGED"
        with pytest.raises(ValidationError):
            StagingTransport(
                broken,
                manifest,
                transport._config,
                transport._connection,
                sender=lambda *_: pytest.fail("No provider call allowed"),
            )
    else:
        transport._records[0]["metadata"]["page"] = "CHANGED"
        with pytest.raises(ValidationError):
            transport.describe_index()
    assert calls == []
