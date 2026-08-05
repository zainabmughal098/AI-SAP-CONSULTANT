"""Embedding generation module."""

from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

_model = None


def get_model():
    global _model
    if _model is None:
        try:
            _model = SentenceTransformer(MODEL_NAME, local_files_only=True)
        except Exception:
            _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_chunks(chunks):
    model = get_model()
    texts = [chunk.page_content for chunk in chunks]
    embeddings = model.encode(texts).tolist()
    return embeddings
