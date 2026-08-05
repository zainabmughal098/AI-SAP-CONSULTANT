"""Enrich document metadata for structured Pinecone filtering."""

from __future__ import annotations

import re

DOCUMENT_TYPE_BY_SOURCE = {
    "business_processes.csv": "business_process",
    "common_errors.csv": "common_error",
    "issue_resolution.csv": "issue_resolution",
    "materials.csv": "material",
    "modules.csv": "module",
    "sap_glossary.csv": "glossary",
    "tcodes.csv": "tcode",
}

TITLE_FIELDS = ("title", "process_name", "term", "material_name", "name", "error_message")
MODULE_FIELDS = ("module",)
IDENTIFIER_FIELDS = ("tcode", "error_id", "issue_id", "process_id", "material_id", "term")


def parse_key_value_content(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _first_field(fields: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        value = fields.get(name)
        if value:
            return value
    return None


def enrich_document_metadata(document) -> None:
    filename = document.metadata.get("filename", "")
    document.metadata["source_file"] = filename
    document.metadata["document_type"] = DOCUMENT_TYPE_BY_SOURCE.get(
        filename,
        document.metadata.get("document_type", "unknown"),
    )

    fields = parse_key_value_content(document.page_content)
    module = _first_field(fields, MODULE_FIELDS)
    title = _first_field(fields, TITLE_FIELDS)
    identifier = _first_field(fields, IDENTIFIER_FIELDS)

    if module:
        document.metadata["module"] = module
    if title:
        document.metadata["title"] = title
    if identifier:
        document.metadata["identifier"] = identifier


def enrich_documents(documents):
    for document in documents:
        enrich_document_metadata(document)
    return documents


def build_vector_id(document, chunk_number: int) -> str:
    filename = document.metadata.get("filename", "unknown")
    stem = re.sub(r"[^a-zA-Z0-9_-]", "-", filename.rsplit(".", 1)[0])
    row = document.metadata.get("row")
    row_part = f"row{int(row)}" if row is not None else "row0"
    chunk_part = f"chunk{chunk_number}"
    return f"{stem}-{row_part}-{chunk_part}"
