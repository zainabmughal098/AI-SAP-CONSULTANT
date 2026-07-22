"""Generic document loading module.

Loads every supported file from a directory using LangChain loaders picked
by file extension, so adding a new file of a supported type requires no
code changes.
"""

import os

from langchain_community.document_loaders import (
    CSVLoader,
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
)

LOADER_MAPPING = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".csv": CSVLoader,
    ".docx": Docx2txtLoader,
}


def load_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    loader_cls = LOADER_MAPPING.get(ext)
    if loader_cls is None:
        return []

    loader = loader_cls(file_path)
    documents = loader.load()

    for doc in documents:
        doc.metadata["filename"] = os.path.basename(file_path)
        doc.metadata["source"] = file_path
        doc.metadata["document_type"] = ext.lstrip(".")

    return documents


def load_directory(directory_path):
    all_documents = []
    for entry in sorted(os.listdir(directory_path)):
        file_path = os.path.join(directory_path, entry)
        if os.path.isfile(file_path):
            all_documents.extend(load_file(file_path))
    return all_documents
