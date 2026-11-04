# Stage 5 — public SAP knowledge and synthetic demonstration corpus

Prepared November 3, 2026. Status: **candidate preparation complete; zero human approvals; no ingestion or runtime activation**.

The six baseline reports were read before preparation. Their historical audit findings remain baseline evidence. This stage adds public-source candidates, fictional scenarios and offline QA without changing application code, architecture, frontend, ingestion configuration or provider settings.

## Scope and current readiness

The proposed set contains **17 public-source summary candidates and nine entirely fictional scenarios**. MM, SD, FI, PP, QM and classic WM are represented, plus a cross-module authorization topic. Product editions are recorded separately. This is a small conceptual demonstration set, not complete SAP functional coverage or a collection of verified repair runbooks.

All records await factual/applicability, provenance, confidentiality and usage review. Sixteen public candidates rely on indexed SAP Help article extracts because direct opens returned no readable body. One legacy authorization article had a readable body but did not establish exact target product/release. Neither condition justifies human approval. The original summaries are drafts, not certified SAP documentation.

`rag/approved_sources.json` remains empty. The existing application does not load these preparation artifacts, and substantive answers remain blocked by Stage 4 until separately reviewed sources are authorized and made available through an approved ingestion/integration step. An empty registry does not prevent the existing app from making embedding/Pinecone queries if someone submits a live chat; do not use live chat as an offline validation method.

No real FFC business data, supplier/employee information, internal policies or documents are needed or permitted. The internship affiliation is not source authority or an assertion of SAP-system integration. The prototype does not access or execute SAP transactions.

## Existing knowledge disposition

The seven original CSV files are preserved. `demo_corpus/legacy_inventory.json` records only file hashes, row counts and aggregate repetition; it contains no supplier/price values or row bodies. The checksum tests confirm that preparation did not change them.

| Legacy area | Evidence from local checks | Demonstration disposition |
| --- | --- | --- |
| 1,000 transaction rows | Only 40 distinct payloads after excluding transaction-code column; recognized codes do not validate surrounding tables, modules or procedures. | Exclude all from automatic approval. Use independently researched narrow summaries instead. |
| 1,000 common errors | A 995-record group repeats its action tuple. | Exclude template expansions; collect symptom-specific sources before procedural use. |
| 1,000 issue resolutions | A 995-record group repeats root-cause/diagnostic/resolution/verification fields. | Do not treat repeated advice as independent corroboration. |
| 60 material records | Commercial-field provenance/synthetic status is unestablished. | Exclude from demonstration output and approval; never relabel as fictional by assumption. |
| Six module rows, eight glossary rows, five process rows | Brief text lacks authoritative lineage/version and does not establish full runbooks. | Preserve as historical data; do not approve by filename or plausible terminology. |

Unsupported, incomplete or suspicious content is not proof that a particular code is fictitious. No newly verified list of inaccurate SAP codes is claimed. The appropriate present classification is **unverified / unsuitable for automatic demonstration use**. Detailed Stage 3 reference-closure and consistency findings remain in `RAG_AUDIT.md`.

## Prepared artifacts

All preparation data lives outside `data/`, which remains the existing ingestion directory.

| Artifact | Role |
| --- | --- |
| `SAP_SOURCE_REVIEW.md` | Human review register, source links, edition/release scope and access limitations. |
| `SYNTHETIC_SCENARIOS.md` | Nine fictional demonstration scripts and safe expected behavior. |
| `DEMO_EVALUATION_PLAN.md` | Mapping of all existing 40 questions, eight supplemental cases, criteria and execution boundaries. |
| `demo_corpus/candidates.json` | Authoritative research ledger: topic/module, codes/apps, observed product/version, URL/title/sections, original summary, supported observations, prerequisites, limits and false/null human-approval fields. |
| `demo_corpus/scenarios.json` | Original fictional scenario entities, simulated messages/outcomes and forbidden claims. |
| `demo_corpus/prepared_records.json` | 26 proposed record envelopes with frozen local IDs, original content and metadata. Not existing vector IDs or an ingestion payload approved for use. |
| `demo_corpus/review_manifest.json` | Stage 4-compatible hash-keyed draft entries, all `reviewed: false`; usage-review gates remain empty. |
| `demo_corpus/evaluation_mapping.json` | Machine-readable prospective query-to-candidate mapping, not gold relevance judgments. |
| `demo_corpus/legacy_inventory.json` | Original CSV checksums and safe aggregate review. |
| `demo_corpus/prepare_manifest.py` | Offline generator for prepared records and pending manifest only; no provider, ingestion, approval or runtime-registry writes. |
| `tests/test_demo_corpus.py` | 64 offline preparation/approval-boundary checks. |

The research date is November 3, 2026 for every candidate and appears in each prepared record's metadata. It is **not** a human approval date; human reviewer/date remain null. Titles and versions describe observed documentation, not FFC's installation. Unknown applicability stays unknown.

## Source and content design

Use concise original summaries and source links, not copies of manuals. Public accessibility and an official hostname do not by themselves establish redistribution or ingestion permission. Usage review is pending for every public candidate. No protected manual was copied wholesale, SAP account/paywall bypass attempted, or external source text downloaded into the project.

Retain one narrow topic per reviewed record, with prerequisites and exclusions beside the summary. Keep ERP, S/4HANA on-premise and Cloud Public Edition variants separate; do not infer cross-edition screen or authorization equivalence. Mutable `Latest` selectors must be checked/frozen to the intended demonstration version before approval. The legacy SU53 source additionally needs target-product verification or replacement with a fully scoped authoritative source.

Only three candidates include limited diagnostic observations; they are not complete procedures. The remaining candidates deliberately have empty troubleshooting-step lists. Missing stock-deficit, period, reversal, tax, pricing, credit, table-dictionary and release-strategy evidence remains a gap. Do not manufacture a procedure to make every evaluation question answerable.

The candidate summaries have zero exact duplicates after whitespace/lowercase normalization. A standard-library character-overlap screen at ratio 0.5 found no candidate pairs. This is not learned semantic deduplication or proof of conceptual uniqueness. The two PO-related topics overlap intentionally but retain distinct source/release scope; a functional reviewer should decide whether to consolidate within one chosen product release. Existing Stage 4 tests retain meaningful code, operator, diagnostic and applicability differences.

## Stage 4 compatibility and approval gates

The generator builds the same `{id, content, metadata}` identity used by `record_digest()`. Prepared metadata already contains the text value expected in normalized Pinecone responses. Offline tests simulate the actual normalizer and confirm identical hashes and citation handles. Manifest keys are SHA-256 digests; its entry schema includes `reviewed`, `kind`, source URL, original-summary flag, usage-review field and scope. Every entry fails `SourcePolicy.approve()` as shipped.

Candidate IDs and metadata document numbers are local preparation locators, not SAP publication numbers or observed Pinecone IDs. No CSV row/PDF page is invented for web sources; URL, title and source section supply provenance. Synthetic business document numbers are explicitly fictional. Multi-code topics use `transaction_codes` arrays; the existing exact-code prototype queries scalar `identifier`/`tcode`, so family records may rely on semantic retrieval. That integration limitation is recorded rather than fixed in this preparation stage.

Before any activation, a qualified human must check each summary against readable official text, approve product/release applicability and usage, and record reviewer identity/date and the user's explicit authorization separately. Human review evidence must not be stored only in generated files: regeneration always produces pending entries. Any content, metadata, ID, chunking or loader change alters the hash and requires the final record manifest to be rebuilt and checked against the reviewed content. Never copy this draft into the runtime registry or simply flip a flag to obtain answers.

An approved integration task would still need an adapter preserving IDs and complete metadata, a chosen atomic/section-aware chunk strategy, verified model compatibility and a separate staging target. The current generic ingestion pipeline would change chunk IDs/metadata and may split these records. This manifest is compatible with the Stage 4 **record/hash contract**, not a claim that the current ingestion CLI can load it unchanged. No ingestion or index change is authorized by these files.

## Verification and remaining work

- Full Python suite: **306 passed** (242 unchanged prior cases plus 64 Stage 5 cases), one existing Starlette/httpx deprecation warning.
- Full frontend suite: **12 passed**, unchanged source-renderer/controller tests using a minimal DOM; no browser or provider test.
- Scoped lint/format, syntax and whitespace checks are recorded in `IMPROVEMENT_REPORT.md` after final verification.
- No existing CSV, application/runtime source, frontend, ingestion code or approval registry was modified in this stage.

Tests establish local schema, provenance-field completeness, consistency, hash/citation traceability, fictional labeling and approval gates. They do not establish SAP factual correctness, licensing clearance, embedding compatibility or live retrieval/answer quality. The 40-query mapping is prospective: nine narrow informational candidates, eleven partial cases, fifteen evidence gaps, two ambiguous requests and three unsupported company/custom questions. All real retrieval results remain NR; zero sources are approved now.

Stop for review of these candidates and evaluation boundaries. Source approval, ingestion, live embedding/Pinecone/Groq testing and deployment each remain subject to the user's applicable explicit authorization. Do not seek FFC evidence to fill gaps.
