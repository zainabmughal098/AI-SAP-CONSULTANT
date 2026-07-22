"""Pinecone storage module."""

import os
import uuid

from pinecone import Pinecone, ServerlessSpec

EMBEDDING_DIMENSION = 384
UPSERT_BATCH_SIZE = 100


def get_index():
    api_key = os.environ["PINECONE_API_KEY"]
    index_name = os.environ["PINECONE_INDEX_NAME"]

    pc = Pinecone(api_key=api_key)

    if index_name not in [i["name"] for i in pc.list_indexes()]:
        pc.create_index(
            name=index_name,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )

    return pc.Index(index_name)


def store_chunks(chunks, embeddings):
    index = get_index()

    vectors = []
    for chunk, embedding in zip(chunks, embeddings):
        metadata = dict(chunk.metadata)
        metadata["text"] = chunk.page_content
        vectors.append(
            {
                "id": str(uuid.uuid4()),
                "values": embedding,
                "metadata": metadata,
            }
        )

    for i in range(0, len(vectors), UPSERT_BATCH_SIZE):
        index.upsert(vectors=vectors[i : i + UPSERT_BATCH_SIZE])

    return len(vectors)
