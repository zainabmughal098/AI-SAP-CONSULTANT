# AI SAP Consultant Retrieval Engine

This repository now includes the Task 2 semantic retrieval engine for SAP knowledge search.

## What it does

- Accepts a natural language SAP question
- Generates a query embedding using the same model used during indexing
- Searches Pinecone with configurable top-k retrieval
- Supports optional metadata filtering
- Ranks results by similarity score
- Builds a combined retrieval context for downstream LLM usage

## Project structure

```text
rag/
├── retriever/
│   ├── query_processor.py
│   ├── retriever.py
│   └── context_builder.py
├── pinecone/
├── config/
└── main.py
```

## Required environment variables

Set these in your `.env` file:

```bash
PINECONE_API_KEY=your_api_key
PINECONE_INDEX_NAME=your_index_name
PINECONE_NAMESPACE=optional_namespace
RETRIEVAL_TOP_K=5
```

## Install dependencies

```bash
pip install -r requirements.txt
```

## Run the retrieval engine

Use the natural language query directly:

```bash
python -m rag.main "How do I create a Purchase Order?"
```

Use metadata filters when needed:

```bash
python -m rag.main "Purchase Order release failed" --filter Module=MM --filter document_type=issue
```

## Output format

The engine returns structured JSON similar to:

```json
{
  "query": "How do I create a Purchase Order?",
  "results": [
    {
      "score": 0.95,
      "source_file": "tcodes.csv",
      "document_type": "tcode",
      "module": "MM",
      "title": "ME21N",
      "content": "Create Purchase Order..."
    }
  ]
}
```

## Error handling

The engine handles the following cases gracefully:

- Empty query
- No matching documents
- Pinecone connection failure
- Invalid embedding generation
- Missing metadata

## Notes

- The retrieval engine uses the same embedding model as Task 1: `all-MiniLM-L6-v2`.
- The context builder combines retrieved records into a single block that can be passed to an LLM later.
