"""Document chunking module."""

from langchain.text_splitter import RecursiveCharacterTextSplitter

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


def chunk_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)

    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_number"] = i

    return chunks
