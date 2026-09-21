"""Application settings for retrieval and generation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class AppSettings:
    """Runtime settings loaded from environment variables."""

    pinecone_api_key: str
    pinecone_index_name: str
    pinecone_namespace: str | None = None
    top_k: int = 5
    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_api_url: str = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
    embedding_api_key: str = ""
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    max_history_turns: int = 10
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024

    @classmethod
    def from_env(cls) -> "AppSettings":
        api_key = os.environ.get("PINECONE_API_KEY", "").strip()
        index_name = os.environ.get("PINECONE_INDEX_NAME", "").strip()
        namespace = os.environ.get("PINECONE_NAMESPACE", "").strip() or None
        top_k_raw = os.environ.get("RETRIEVAL_TOP_K", "5").strip()
        groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        embedding_api_url = os.environ.get(
            "EMBEDDING_API_URL",
            "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2",
        ).strip()
        embedding_api_key = os.environ.get("EMBEDDING_API_KEY", "").strip()
        llm_model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile").strip()
        max_history_raw = os.environ.get("MAX_HISTORY_TURNS", "10").strip()
        temperature_raw = os.environ.get("LLM_TEMPERATURE", "0.2").strip()
        max_tokens_raw = os.environ.get("LLM_MAX_TOKENS", "1024").strip()

        if not api_key:
            raise ValueError("Missing required environment variable: PINECONE_API_KEY")
        if not index_name:
            raise ValueError("Missing required environment variable: PINECONE_INDEX_NAME")
        if not groq_api_key:
            raise ValueError("Missing required environment variable: GROQ_API_KEY")

        try:
            top_k = max(1, int(top_k_raw))
            max_history_turns = max(2, int(max_history_raw))
            llm_max_tokens = max(256, int(max_tokens_raw))
            llm_temperature = float(temperature_raw)
        except ValueError as exc:
            raise ValueError("Invalid numeric environment variable for app settings") from exc

        return cls(
            pinecone_api_key=api_key,
            pinecone_index_name=index_name,
            pinecone_namespace=namespace,
            top_k=top_k,
            embedding_api_url=embedding_api_url,
            embedding_api_key=embedding_api_key,
            groq_api_key=groq_api_key,
            llm_model=llm_model,
            max_history_turns=max_history_turns,
            llm_temperature=llm_temperature,
            llm_max_tokens=llm_max_tokens,
        )


RetrievalSettings = AppSettings
