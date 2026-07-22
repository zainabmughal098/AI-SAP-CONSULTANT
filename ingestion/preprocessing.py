"""Text preprocessing module.

Cleans extracted text before chunking, without touching SAP-specific
keywords (transaction codes, table names) that matter for retrieval.
"""

import re


def clean_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def clean_documents(documents):
    for doc in documents:
        doc.page_content = clean_text(doc.page_content)
    return documents
