"""Pinecone storage module."""

import logging
import os

from pinecone import Pinecone, ServerlessSpec

from ingestion.metadata import build_vector_id

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 384
UPSERT_BATCH_SIZE = 100


def get_pinecone_client() -> Pinecone:
    return Pinecone(api_key=os.environ["PINECONE_API_KEY"])


def get_index_name() -> str:
    return os.environ["PINECONE_INDEX_NAME"]


def ensure_index(pc: Pinecone | None = None):
    client = pc or get_pinecone_client()
    index_name = get_index_name()

    if index_name not in [index["name"] for index in client.list_indexes()]:
        client.create_index(
            name=index_name,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    return client.Index(index_name)


def get_index():
    return ensure_index()


def clear_index():
    index = get_index()
    namespace = os.environ.get("PINECONE_NAMESPACE", "").strip() or None
    delete_kwargs = {"delete_all": True}
    if namespace:
        delete_kwargs["namespace"] = namespace
    index.delete(**delete_kwargs)
    logger.info("Cleared Pinecone index%s", f" namespace '{namespace}'" if namespace else "")


def _sanitize_metadata(metadata: dict) -> dict:
    sanitized: dict = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list):
            sanitized[key] = [str(item) for item in value]
        else:
            sanitized[key] = str(value)
    return sanitized


def store_chunks(chunks, embeddings):
    index = get_index()
    namespace = os.environ.get("PINECONE_NAMESPACE", "").strip() or None

    vectors = []
    for chunk, embedding in zip(chunks, embeddings):
        chunk_number = int(chunk.metadata.get("chunk_number", 0))
        metadata = _sanitize_metadata(dict(chunk.metadata))
        metadata["text"] = chunk.page_content
        vector = {
            "id": build_vector_id(chunk, chunk_number),
            "values": embedding,
            "metadata": metadata,
        }
        vectors.append(vector)

    upsert_kwargs: dict = {"vectors": []}
    if namespace:
        upsert_kwargs["namespace"] = namespace

    for start in range(0, len(vectors), UPSERT_BATCH_SIZE):
        batch = vectors[start : start + UPSERT_BATCH_SIZE]
        upsert_kwargs["vectors"] = batch
        index.upsert(**upsert_kwargs)

    return len(vectors)
