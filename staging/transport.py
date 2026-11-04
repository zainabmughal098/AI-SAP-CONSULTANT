"""Explicitly gated staging verification transport. No ingestion or generation.

Construction never opens a connection. All credentials/targets/permits are explicit.
Read-only Pinecone and Groq metadata, plus separately authorized synthetic encodings.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone

from staging.adapter import (
    HASH,
    ValidationError,
    canonical_hash,
    target_blockers,
    validate_records,
    verify_round_trip,
)

OPERATIONS = {
    "pinecone_describe",
    "pinecone_stats",
    "pinecone_fetch",
    "groq_models",
    "embedding_probe",
}


@dataclass(frozen=True, repr=False)
class StagingCredentials:
    project: str
    pinecone: str = field(default="", repr=False)
    embedding: str = field(default="", repr=False)
    groq: str = field(default="", repr=False)


@dataclass(frozen=True)
class OperationPermit:
    reference: str
    binding_hash: str
    request_hashes: frozenset[str]
    max_requests: int
    expires_utc: str
    cost_ceiling: float
    currency: str


def binding_hash(records, manifest, config, connection) -> str:
    return canonical_hash(
        {
            "records": records,
            "manifest": manifest,
            "config": config,
            "connection": connection,
        }
    )


def request_hash(operation: str, method: str, url: str, body) -> str:
    return canonical_hash(
        {"operation": operation, "method": method, "url": url, "body": body}
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValidationError("provider_redirect_forbidden")


def https_json(method, url, headers, body, timeout, limit):
    """Single bounded HTTPS attempt, no redirect/retry or environment proxy lookup."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValidationError("duplicate_provider_json_key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValidationError("nonfinite_provider_json")

    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body, allow_nan=False).encode(),
        headers=headers,
        method=method,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if (
            response.status != 200
            or response.headers.get_content_type() != "application/json"
        ):
            raise ValidationError("invalid_provider_http_response")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValidationError("provider_response_too_large")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)


class StagingTransport:
    """A permit is operator evidence, not cryptographic proof of authorization."""

    def __init__(
        self,
        records,
        manifest,
        config,
        connection,
        credentials=None,
        permit=None,
        sender=None,
    ):
        validate_records(records, manifest)
        self._records, self._manifest, self._config, self._connection = deepcopy(
            (records, manifest, config, connection)
        )
        self._credentials, self._permit = credentials, permit
        self._sender = sender if sender is not None else https_json
        self._active = True
        self._attempts = 0
        self._lock = threading.Lock()

    @property
    def attempts(self):
        return self._attempts

    @property
    def active(self):
        return self._active

    def deactivate(self):
        """Stop subsequent operations; never changes any index or registry."""
        self._active = False

    def _target(self):
        if not self._active or self._connection.get("network_enabled") is not True:
            raise ValidationError("staging_network_disabled")
        if target_blockers(self._config):
            raise ValidationError("staging_target_or_operation_blocked")
        return self._config["target"]

    def _guard(self, operation, method, url, body):
        connection, config, permit = self._connection, self._config, self._permit
        if not self._active or connection.get("network_enabled") is not True:
            raise ValidationError("staging_network_disabled")
        if operation not in OPERATIONS or target_blockers(config):
            raise ValidationError("staging_target_or_operation_blocked")
        if not connection.get("endpoint_review_reference") or not connection.get(
            "credential_review_reference"
        ):
            raise ValidationError("connection_review_missing")
        if (
            permit is None
            or not permit.reference.strip()
            or permit.binding_hash
            != binding_hash(self._records, self._manifest, config, connection)
        ):
            raise ValidationError("operation_authorization_missing_or_mismatched")
        try:
            expiry = datetime.fromisoformat(permit.expires_utc.replace("Z", "+00:00"))
            valid_expiry = expiry.utcoffset() is not None and expiry > datetime.now(
                timezone.utc
            )
        except (ValueError, TypeError, AttributeError):
            valid_expiry = False
        if (
            not valid_expiry
            or type(permit.max_requests) is not int
            or not 1 <= permit.max_requests <= 10
            or self._attempts >= permit.max_requests
        ):
            raise ValidationError("operation_permit_expired_or_exhausted")
        if (
            type(permit.cost_ceiling) not in (int, float)
            or not math.isfinite(permit.cost_ceiling)
            or permit.cost_ceiling <= 0
            or not isinstance(permit.currency, str)
            or len(permit.currency) != 3
            or not permit.currency.isupper()
        ):
            raise ValidationError("operation_budget_missing")
        if request_hash(operation, method, url, body) not in permit.request_hashes:
            raise ValidationError("request_not_explicitly_authorized")
        if (
            type(connection.get("timeout_seconds")) is not int
            or not 1 <= connection["timeout_seconds"] <= 30
            or type(connection.get("max_response_bytes")) is not int
            or not 1 <= connection["max_response_bytes"] <= 1048576
        ):
            raise ValidationError("invalid_connection_bounds")
        credentials = self._credentials
        if credentials is None or credentials.project != config["target"]["project"]:
            raise ValidationError("staging_credentials_missing_or_wrong_project")
        service = (
            "pinecone"
            if operation.startswith("pinecone_")
            else "groq"
            if operation == "groq_models"
            else "embedding"
        )
        key = getattr(credentials, service)
        expected = connection.get("credential_sha256", {}).get(service)
        production = connection.get("production_credential_sha256")
        if (
            not isinstance(production, list)
            or not production
            or not all(
                isinstance(item, str) and HASH.fullmatch(item) for item in production
            )
        ):
            raise ValidationError("production_credential_inventory_missing")
        if (
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(expected, str)
            or hashlib.sha256(key.encode()).hexdigest() != expected
            or expected in production
        ):
            raise ValidationError("credential_fingerprint_mismatch_or_production_key")
        return service, key

    def _perform(self, operation, method, url, body, validator):
        with self._lock:
            service, key = self._guard(operation, method, url, body)
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            if service == "pinecone":
                version = self._connection.get("pinecone_api_version")
                if version != "2025-10":
                    raise ValidationError("pinecone_version_missing")
                headers.update({"Api-Key": key, "X-Pinecone-API-Version": version})
            else:
                headers["Authorization"] = f"Bearer {key}"
            self._attempts += 1  # Count failed attempts too; no automatic retry.
            try:
                response = self._sender(
                    method,
                    url,
                    headers,
                    deepcopy(body),
                    self._connection["timeout_seconds"],
                    self._connection["max_response_bytes"],
                )
                return validator(response)
            except Exception:
                self.deactivate()
                raise ValidationError(
                    "provider_operation_failed_or_response_invalid"
                ) from None

    def describe_index(self):
        target = self._target()
        url = "https://api.pinecone.io/indexes/" + urllib.parse.quote(
            target["index"], safe=""
        )

        def validate(value):
            if (
                not isinstance(value, dict)
                or value.get("name") != target["index"]
                or value.get("host") != target["host"]
                or type(value.get("dimension")) is not int
                or value["dimension"] != 384
                or value.get("metric") != "cosine"
                or not isinstance(value.get("status"), dict)
                or value["status"].get("ready") is not True
            ):
                raise ValidationError("index_description_mismatch")
            return {
                "target": deepcopy(target),
                "dimension": 384,
                "metric": "cosine",
                "ready": True,
            }

        return self._perform("pinecone_describe", "GET", url, None, validate)

    def describe_stats(self):
        target = self._target()
        url = f"https://{target['host']}/describe_index_stats"

        def validate(value):
            if (
                not isinstance(value, dict)
                or type(value.get("dimension")) is not int
                or value["dimension"] != 384
                or not isinstance(value.get("namespaces"), dict)
            ):
                raise ValidationError("invalid_index_stats")
            namespace = value["namespaces"].get(target["namespace"], {"vectorCount": 0})
            counts = [
                namespace[key]
                for key in ("vectorCount", "vector_count")
                if isinstance(namespace, dict) and key in namespace
            ]
            if (
                not counts
                or any(type(item) is not int or item < 0 for item in counts)
                or len(set(counts)) != 1
            ):
                raise ValidationError("invalid_namespace_count")
            count = counts[0]
            return {
                "namespace": target["namespace"],
                "vector_count": count,
                "dimension": 384,
            }

        return self._perform("pinecone_stats", "POST", url, {}, validate)

    def fetch_exact(self):
        self._target()
        ids = [record["id"] for record in self._records]
        if (
            set(ids) != set(self._connection.get("allowed_record_ids", []))
            or len(ids) > 2
        ):
            raise ValidationError("fetch_record_set_not_authorized")
        namespace = self._config["target"]["namespace"]
        url = (
            f"https://{self._config['target']['host']}/vectors/fetch?"
            + urllib.parse.urlencode(
                [*(("ids", item) for item in ids), ("namespace", namespace)]
            )
        )

        def validate(value):
            if (
                not isinstance(value, dict)
                or value.get("namespace") != namespace
                or not isinstance(value.get("vectors"), dict)
                or set(value["vectors"]) != set(ids)
            ):
                raise ValidationError("fetch_response_mismatch")
            matches = list(value["vectors"].values())
            verify_round_trip(self._records, matches)
            for identifier, match in value["vectors"].items():
                if match.get("id") != identifier:
                    raise ValidationError("fetch_id_mismatch")
                vector = match.get("values")
                if (
                    not isinstance(vector, list)
                    or len(vector) != 384
                    or not all(
                        type(item) in (int, float) and math.isfinite(item)
                        for item in vector
                    )
                ):
                    raise ValidationError("fetch_vector_malformed")
            # No raw source preview or context admission; approvals remain separate.
            return {"round_trip_verified": True, "record_ids": ids, "admitted": 0}

        return self._perform("pinecone_fetch", "GET", url, None, validate)

    def list_groq_models(self):
        def validate(value):
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("data"), list)
                or not value["data"]
                or not all(
                    isinstance(item, dict)
                    and isinstance(item.get("id"), str)
                    and item["id"].strip()
                    for item in value["data"]
                )
            ):
                raise ValidationError("invalid_groq_model_response")
            return {
                "model_ids": [item["id"] for item in value["data"]],
                "generation_tested": False,
            }

        return self._perform(
            "groq_models",
            "GET",
            "https://api.groq.com/openai/v1/models",
            None,
            validate,
        )

    def embedding_probe(self, text):
        if (
            not isinstance(text, str)
            or not text.startswith("DEMO / SIMULATED")
            or len(text) > 500
            or hashlib.sha256(text.encode()).hexdigest()
            not in self._connection.get("allowed_probe_hashes", [])
        ):
            raise ValidationError("probe_input_not_authorized")
        url = self._connection.get("embedding_url")
        parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
        if (
            not parsed
            or parsed.scheme != "https"
            or parsed.hostname
            not in {"api-inference.huggingface.co", "router.huggingface.co"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValidationError("embedding_endpoint_not_reviewed")

        def validate(value):
            if (
                not isinstance(value, list)
                or len(value) != 384
                or not all(
                    type(item) in (int, float) and math.isfinite(item) for item in value
                )
            ):
                raise ValidationError("invalid_sentence_embedding")
            norm = math.hypot(*value)
            if not math.isfinite(norm) or norm == 0:
                raise ValidationError("invalid_embedding_norm")
            return {
                "dimension": 384,
                "norm": norm,
                "vector": deepcopy(value),
                "encoder_equivalence_verified": False,
            }

        return self._perform(
            "embedding_probe",
            "POST",
            url,
            {"inputs": text, "options": {"wait_for_model": True}},
            validate,
        )
