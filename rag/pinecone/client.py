"""Thin Pinecone access layer for semantic retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pinecone import Pinecone

from rag.config.settings import RetrievalSettings


@dataclass
class PineconeRetrievalClient:
    """Query helper around the Pinecone index."""

    settings: RetrievalSettings

    def _client(self) -> Pinecone:
        return Pinecone(api_key=self.settings.pinecone_api_key)

    def get_index(self):
        client = self._client()
        return client.Index(self.settings.pinecone_index_name)

    def query(
        self,
        embedding: list[float],
        top_k: int,
        metadata_filter: dict[str, Any] | None = None,
    ):
        index = self.get_index()
        query_kwargs: dict[str, Any] = {
            "vector": embedding,
            "top_k": top_k,
            "include_metadata": True,
        }
        if metadata_filter:
            query_kwargs["filter"] = metadata_filter
        if self.settings.pinecone_namespace:
            query_kwargs["namespace"] = self.settings.pinecone_namespace

        return index.query(**query_kwargs)
