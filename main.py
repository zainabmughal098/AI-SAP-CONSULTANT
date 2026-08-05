"""Entry point for the knowledge ingestion pipeline."""

import argparse
import logging

from dotenv import load_dotenv

from ingestion.loader import load_directory
from ingestion.preprocessing import clean_documents
from ingestion.metadata import enrich_documents
from ingestion.chunking import chunk_documents
from ingestion.embedding import embed_chunks
from ingestion.vector_store import clear_index, store_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = "data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SAP knowledge ingestion pipeline")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Clear the Pinecone index before storing new vectors",
    )
    return parser


def main():
    load_dotenv()
    args = build_parser().parse_args()

    if args.rebuild:
        logger.info("Clearing existing Pinecone vectors before re-ingestion")
        clear_index()

    logger.info("Loading documents from %s", DATA_DIR)
    documents = load_directory(DATA_DIR)
    logger.info("Loaded %d documents", len(documents))

    documents = clean_documents(documents)
    documents = enrich_documents(documents)

    chunks = chunk_documents(documents)
    logger.info("Created %d chunks", len(chunks))

    embeddings = embed_chunks(chunks)
    logger.info("Generated %d embeddings", len(embeddings))

    count = store_chunks(chunks, embeddings)
    logger.info("Stored %d vectors in Pinecone", count)


if __name__ == "__main__":
    main()
