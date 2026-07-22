"""Entry point for the knowledge ingestion pipeline."""

import logging

from dotenv import load_dotenv

from ingestion.loader import load_directory
from ingestion.preprocessing import clean_documents
from ingestion.chunking import chunk_documents
from ingestion.embedding import embed_chunks
from ingestion.vector_store import store_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = "data"


def main():
    load_dotenv()

    logger.info("Loading documents from %s", DATA_DIR)
    documents = load_directory(DATA_DIR)
    logger.info("Loaded %d documents", len(documents))

    documents = clean_documents(documents)

    chunks = chunk_documents(documents)
    logger.info("Created %d chunks", len(chunks))

    embeddings = embed_chunks(chunks)
    logger.info("Generated %d embeddings", len(embeddings))

    count = store_chunks(chunks, embeddings)
    logger.info("Stored %d vectors in Pinecone", count)


if __name__ == "__main__":
    main()
