# AI SAP Consultant Retrieval Engine

This repository implements a grounded SAP consultant using a RAG pipeline:

- Task 1: ingestion and Pinecone indexing
- Task 2: semantic retrieval
- Task 3: grounded LLM generation with multi-turn conversational memory
- Task 4: human-in-the-loop interactive diagnosis for SAP issues

## What it does

- Accepts natural language SAP questions
- Classifies intent before retrieval
- For **Issue Diagnosis**, asks clarifying questions one at a time (like a functional consultant)
- Retrieves relevant records from Pinecone using an enriched diagnostic query
- Generates grounded answers using Groq (structured diagnosis when diagnosing)
- Maintains conversation history across multiple prompts in the same session

## Interactive diagnosis workflow

```text
User message
  → Intent classification
  → Issue Diagnosis? ──No──→ Retrieve → Answer
                     │
                     Yes
                     ▼
              Ask clarifying questions (one at a time)
                     ▼
              Enough information?
                     │
                    Yes
                     ▼
              Enriched retrieval query → Retrieve → Structured diagnosis
```

Only **Issue Diagnosis** enters clarification. Lookups such as “Explain ME21N” or “What is VBAK?” go straight to retrieval.

Diagnosis flows are config-driven in [`consultant/diagnosis_trees.json`](consultant/diagnosis_trees.json). Add a new SAP issue flow by editing that JSON—no Python changes required.

Each tree defines:

- `id` / `intent`
- `match_keywords` (used to select the flow)
- `required_fields` and `questions`
- `retrieval_terms` (seed terms for the enriched Pinecone query)

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

- `reset` clears conversation memory and any in-progress diagnosis state
- `exit` or `quit` ends the session

## Run the web UI

Start the server and open the Gemini-style chat interface in your browser:

```bash
uvicorn api.main:app --reload --port 8000
```

Then visit [http://127.0.0.1:8000](http://127.0.0.1:8000)

Features:
- Dark animated background
- Streaming grounded responses
- Clarifying questions appear as normal assistant messages
- Multi-turn conversation memory via session id
- Recent chats stored locally in the browser

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

Issue diagnosis example (clarification then final answer in the same session):

```bash
curl -X POST http://127.0.0.1:8000/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"My Purchase Order is not releasing.\"}"
```

Responses may include optional `intent` and `phase` fields (`clarifying`, `diagnosing`, `answering`).

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
consultant/
├── intent_classifier.py
├── clarification_engine.py
├── diagnosis_manager.py
├── diagnosis_tree_loader.py
├── session_state.py
├── response_builder.py
└── diagnosis_trees.json
api/
web/
tests/
```

## Notes

- Ingestion uses deterministic vector IDs to prevent duplicate records on re-index.
- CSV rows are enriched with semantic metadata such as `module`, `title`, and `document_type`.
- Generation is grounded: the model is instructed to answer only from retrieved context.
- The retrieval engine is unchanged; diagnosis only builds a richer query before calling it.
- Final diagnoses use a structured format: Diagnosis, Possible Root Cause, Reasoning, Recommended Resolution, Related T-Codes, Related Tables, Confidence Score.
