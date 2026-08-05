# AI SAP Consultant Retrieval Engine

This repository implements a grounded SAP consultant using a RAG pipeline:

- Task 1: ingestion and Pinecone indexing
- Task 2: semantic retrieval
- Task 3: grounded LLM generation with multi-turn conversational memory

## What it does

- Accepts natural language SAP questions
- Retrieves relevant records from Pinecone
- Generates grounded answers using Groq
- Maintains conversation history across multiple prompts in the same session

## Required environment variables

Set these in your `.env` file:

```bash
PINECONE_API_KEY=your_api_key
PINECONE_INDEX_NAME=your_index_name
GROQ_API_KEY=your_groq_api_key

# Optional
PINECONE_NAMESPACE=optional_namespace
RETRIEVAL_TOP_K=5
LLM_MODEL=llama-3.3-70b-versatile
MAX_HISTORY_TURNS=10
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=1024
```

## Install dependencies

```bash
pip install -r requirements.txt
```

## Rebuild the knowledge base

Clear old vectors and re-ingest with enriched metadata:

```bash
python main.py --rebuild
```

## Run retrieval only

```bash
python -m rag.main "How do I create a Purchase Order?"
python -m rag.main "Purchase Order release failed" --filter Module=MM
```

## Run the grounded consultant chat

Interactive multi-turn chat:

```bash
python -m rag.chat
```

Single query:

```bash
python -m rag.chat --query "Explain ME21N"
```

Chat commands:

- `reset` clears conversation memory
- `exit` or `quit` ends the session

## Run the API server

```bash
uvicorn api.main:app --reload --port 8000
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"How do I create a Purchase Order?\"}"
```

Use the returned `session_id` in the next request to continue the conversation:

```bash
curl -X POST http://127.0.0.1:8000/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"What transaction code did you mention?\",\"session_id\":\"YOUR_SESSION_ID\"}"
```

## Run tests

```bash
python -m pytest tests/ -q
```

## Project structure

```text
ingestion/
rag/
├── retriever/
├── generation/
├── memory/
├── consultant.py
├── chat.py
└── main.py
api/
tests/
```

## Notes

- Ingestion uses deterministic vector IDs to prevent duplicate records on re-index.
- CSV rows are enriched with semantic metadata such as `module`, `title`, and `document_type`.
- Generation is grounded: the model is instructed to answer only from retrieved context.
