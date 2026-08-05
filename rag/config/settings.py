"""Configuration for the semantic retrieval engine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class RetrievalSettings:
    """Runtime settings loaded from environment variables."""

    pinecone_api_key: str
    pinecone_index_name: str
    pinecone_namespace: str | None = None
    top_k: int = 5
    embedding_model_name: str = "all-MiniLM-L6-v2"

    @classmethod
    def from_env(cls) -> "RetrievalSettings":
        api_key = os.environ.get("PINECONE_API_KEY", "").strip()
        index_name = os.environ.get("PINECONE_INDEX_NAME", "").strip()
        namespace = os.environ.get("PINECONE_NAMESPACE", "").strip() or None
        top_k_raw = os.environ.get("RETRIEVAL_TOP_K", "5").strip()

        if not api_key:
            raise ValueError("Missing required environment variable: PINECONE_API_KEY")
        if not index_name:
            raise ValueError("Missing required environment variable: PINECONE_INDEX_NAME")

        try:
            top_k = max(1, int(top_k_raw))
        except ValueError as exc:
            raise ValueError("RETRIEVAL_TOP_K must be an integer") from exc

        return cls(
            pinecone_api_key=api_key,
            pinecone_index_name=index_name,
            pinecone_namespace=namespace,
            top_k=top_k,
        )
