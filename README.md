# AI SAP Consultant Retrieval Engine

## Offline academic demonstration

This is an internship prototype, not an FFC-approved or implemented SAP system.
The isolated offline demo uses TEST_ONLY fictional scenarios and a finite set of
public SAP transaction-purpose summaries with explicit product/release scopes.
It does not access SAP or external AI providers and needs no API keys.
The production source-approval registry remains empty; prepared source candidates
are pending review, not automatically approved knowledge.

From the project root, using Python 3.12 and an activated project virtual environment:

```bash
python -m pip install -r requirements-dev.txt
python -m offline_demo
```

Dependency installation requires package access; running the installed offline
demo does not. Open http://127.0.0.1:8765. Try `What is ME21N used for?` or
`What should I do if a goods receipt fails?`. Use New Chat for a fresh case;
sidebar history and page refresh retain the selected conversation within the
running process. Server restarts clear backend diagnostic memory.

Offline verification:

```bash
python -m pytest tests/ -q -p no:cacheprovider
node --test tests/frontend_reliability.test.cjs tests/frontend_sources.test.cjs tests/frontend_offline_presentation.test.cjs
python -m offline_demo.evaluate
python -m staging --dry-run
```

Node 24 was used for frontend checks. The staging dry run is intentionally blocked
(exit 2) while reviews, encoder compatibility and isolated target details are
missing; it performs no ingestion. Keep the source/manifest/checksum JSON files
and five Markdown test baselines included by `.gitignore`. Browser/evaluation
run-result JSON files are disposable and regenerated locally.

The legacy CSV corpus is unverified and is not the offline demo's approved SAP
knowledge. In particular, publication of the existing material/supplier/price
file requires provenance and confidentiality clearance. Do not ingest it or
treat it as fictional by assumption.

The remaining sections describe the provider-backed pipeline; starting that
pipeline or ingestion is separate from the offline commands above.

## Explicit Vercel demo mode

For the academic demo deployment, configure this environment variable in the
Vercel project for the intended environment (Production, and Preview if used):

```text
SAP_APP_MODE=demo
```

The root `app.py` exports the existing offline FastAPI factory before importing
`api.main` or loading provider settings. No Pinecone, Groq or embedding credentials
are required or used in demo mode. Keep the persistent simulation indicator;
code descriptions retain their explicit SAP release scopes and citations.
This selects a finite deterministic demonstration, not live RAG or SAP access.

Leaving the variable unset/blank, or setting `SAP_APP_MODE=rag`, retains the
existing provider-backed bootstrap and its required settings/approval checks.
Other values fail startup clearly. The variable is read at process startup;
changing it requires a fresh deployment/restart, not a hot mode switch. A local
`.env` entry alone does not select this mode: set it in the process environment.

Local check of the exact deployment entrypoint (PowerShell):

```powershell
$env:SAP_APP_MODE = 'demo'
python -m uvicorn app:app --host 127.0.0.1 --port 8767
```

Deployment checklist, **only after separately approving a push/deployment**:

1. Include root `app.py`, `offline_demo/` source files and `presentation.js`,
   `api/routes.py`, the imported `consultant/` and `rag/` modules,
   `consultant/diagnosis_trees.json`, `web/` assets and `requirements.txt`.
   Fictional fixtures and scoped references live in Python source. No legacy
   CSVs, preparation packages, saved test results or provider keys are needed
   by this demo runtime. This does not remove already tracked data or history.
2. Confirm the Vercel project uses the repository root and the root FastAPI
   `app.py` entrypoint. Retain runtime access to frontend files and the custom
   `/static/js/app.js` route; do not override it with a static-only rewrite.
3. Set `SAP_APP_MODE` to `demo` for the intended deployment environment and
   verify the new deployment's commit. Do not change provider credentials.
4. Check the persistent simulation label and `X-SAP-Mode: TEST_ONLY-OFFLINE`
   on function responses. `/health` remains liveness, not provider readiness.
5. Test both ME21N lookup/comparison, an unknown code, receipt/invoice
   clarification, corrections, source titles, New Chat/history/reset/delete,
   and `/chat/stream` completion. Confirm no outgoing provider requests in logs.

Local ASGI and package tests cannot certify the live Vercel build/router.
Conversation memory, diagnosis and deletion tombstones remain process-local:
warm requests in one instance retain context; cold starts or another instance
can lose it even though browser history remains. Start a new case when context
is lost. Durable multi-instance sessions were not added. The process-level
offline network guard is not an OS firewall. No paid inference is used; hosting
usage remains subject to the existing Vercel plan.

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
# Optional: Hugging Face token for remote query embeddings on Vercel
EMBEDDING_API_KEY=your_huggingface_token
```

## Install dependencies

```bash
pip install -r requirements.txt
```

For local knowledge-base ingestion, install the additional document and ML dependencies:

```bash
pip install langchain langchain-community langchain-text-splitters pypdf docx2txt sentence-transformers
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
