# Stage 3 — retrieval evaluation set and static coverage results

Date: November 3, 2026. Baseline: current Stage 1–2 working tree; see `RAG_AUDIT.md` for corpus statistics and compatibility findings.

## What was evaluated

The 40 cases below define a retrieval benchmark and record verified **local corpus candidates**. No embedding, Pinecone, Groq or Vercel call was made. No ranked retrieval results or relevance metrics were fabricated.

For **every case**, actual retrieved vector IDs, rank/score, live relevance, top-K duplicate frequency and retrieved-evidence sufficiency are **NR — not run/not measured**. The Actual column explicitly records NR. Candidate locators are existing local source records, not Pinecone results, approved gold labels or an assertion that a record is sufficient.

The corpus was scanned for exact code/phrase mentions and reviewed structurally through metadata, field lengths and repeated-content groups. Scans omitted commercial material values. A lexical absence can miss synonyms; it does not establish exhaustive absence of related knowledge. Local evidence statuses:

- **L:** narrow informational candidate exists; factual validity/release applicability and live retrieval remain unverified.
- **P:** partial candidate exists, but it does not establish the requested full procedure or diagnosis.
- **G:** requested specific evidence was not located by the documented scan; collect approved material or demonstrate a grounded refusal.
- **A:** ambiguous request; clarify before deciding relevant documents or judging a diagnosis.
- **U:** company-specific/custom question lacking approved company evidence; do not infer an answer.

Source aliases below refer to **physical CSV line numbers**, including header at line 1:

| Alias | Existing local source |
| --- | --- |
| Tnn | `data/tcodes.csv:nn` |
| Enn | `data/common_errors.csv:nn` |
| Inn | `data/issue_resolution.csv:nn` |
| Bnn | `data/business_processes.csv:nn` |
| Mnn | `data/modules.csv:nn` |
| Gnn | `data/sap_glossary.csv:nn` |

For example, T05 is `data/tcodes.csv:5`, not an inferred vector ID. Current files contain one record per data line. The corresponding CSV loader row locator is two less than this physical line. Locators depend on this snapshot and should be supplemented with stable IDs/hashes before a live benchmark.

## Query cases

Expected behavior describes evidence requirements; it does not supply SAP procedures or FFC rules. Detailed answers must be approved for the applicable SAP version by a functional reviewer.

| ID | Query | Expected knowledge/source category | Verified local candidates and evidence limitation | Actual | Recommendation / pass criteria |
| --- | --- | --- | --- | --- | --- |
| R01 | Explain ME21N. | MM transaction explanation | **L:** T05, M02; exact catalog entry exists. | NR | Retrieve the exact approved entry in top five; keep advice within documented purpose. |
| R02 | How is ME22N different from creating a purchase order? | MM transaction comparison | **P:** T05–T06; full comparison not validated. | NR | Require both relevant approved records; do not infer change permissions or company process. |
| R03 | Which transaction should I use to display a purchase order? | MM lookup | **L:** T07 and M02 are candidate references. | NR | Correct documented lookup, without treating display as an update procedure. |
| R04 | My purchase order is not releasing in ME29N. | MM release issue/runbook | **P:** E03, I03 mention ME29N; no exact ME29N catalog entry. | NR | Clarify actual symptom; retrieve approved release-issue evidence; avoid asserting configuration was inspected. |
| R05 | How do I diagnose a missing release strategy? | MM release troubleshooting | **P:** E03/I03; no release-group/code phrase coverage found. | NR | Add reviewed checks, prerequisites and decision points; current generic advice is insufficient for a complete diagnosis. |
| R06 | What is the difference between a purchase requisition and a purchase order? | MM glossary/process | **P:** G05–G06; definitions are brief. | NR | Retrieve both definitions; use a reviewed process source for detailed lifecycle claims. |
| R07 | Explain the procurement process from purchase order through invoice verification. | MM end-to-end process | **P:** B03 contains the MIRO reference; T05/T08/T09 provide narrow candidates. | NR | Require approved process ordering and prerequisites, not disconnected transaction names. |
| R08 | Explain MIGO. | MM transaction explanation | **L:** T08, M02. | NR | Retrieve the exact entry; do not assume every MIGO question is a goods-receipt incident. |
| R09 | I cannot post goods receipt against a purchase order. | MM GR issue/runbook | **P:** B04, E04, I04, T08. | NR | Relevant documented symptom/checks plus transaction and error clarification; no invented posting instructions. |
| R10 | MIGO reports a deficit of stock. What evidence should I check? | MM stock/movement diagnosis | **P:** E04 has a deficit mention; I04/T08 are related candidates only. | NR | Clarify movement/activity and use an approved symptom-specific runbook. |
| R11 | Goods receipt is blocked because the posting period is closed. | MM/FI period-specific error guidance | **G:** no “posting period” phrase found; generic module entries are not sufficient. | NR | Add reviewed release-specific evidence; avoid unsupported period changes. |
| R12 | How should I choose a movement type when reversing a goods receipt? | MM movement/reversal procedure | **G:** no movement-type or reversal-specific evidence established. | NR | Retrieve approved version-specific reversal documentation or decline procedural advice. |
| R13 | Explain MIRO. | MM invoice transaction | **L:** T09, M02; B03 is a process candidate. | NR | Exact approved transaction record should rank above generic error templates. |
| R14 | Invoice posting fails with an account determination error. | MM/FI invoice diagnosis | **P:** E06/I06 contain account-determination and G/L-account references. | NR | Clarify actual transaction/error; require approved decision steps before recommending configuration. |
| R15 | Why is my invoice blocked by a tolerance check? | Invoice verification/tolerance runbook | **G:** no tolerance phrase found. | NR | Add approved tolerance/blocking documentation; do not assign a default threshold. |
| R16 | Explain VA01. | SD transaction explanation | **L:** T02, M03. | NR | Retrieve exact approved code reference; do not substitute an unrelated template. |
| R17 | How do I change an existing sales order? | SD transaction/process | **P:** T03 plus T02/T04 are narrow candidates. | NR | Require a reviewed process source for procedural claims and permissions. |
| R18 | Explain VA03. | SD display transaction | **L:** T04, M03. | NR | Relevant exact entry in top five; no unsupported modification advice. |
| R19 | My sales order is not visible in VA03. | SD visibility/authorization diagnosis | **P:** I02/E02 contain sales-area references; T04 is a code candidate. | NR | Clarify document/area/error; do not claim an authorization or deletion cause without evidence. |
| R20 | My sales order has a pricing error. | SD pricing diagnosis | **G:** no pricing phrase found. | NR | Obtain reviewed pricing-specific material; generic error text cannot establish a pricing cause. |
| R21 | Delivery creation fails because the shipping point is missing. | SD/logistics delivery runbook | **P:** E05, I05, T10. | NR | Retrieve symptom-specific approved evidence; distinguish user reports from verified configuration. |
| R22 | Explain VL01N. | Delivery transaction explanation | **L:** T10, M03. | NR | Relevant exact entry; detailed procedure needs release-appropriate evidence. |
| R23 | Explain order-to-cash, including sales order and delivery. | SD process | **P:** B02/B05, T02/T10 and M03 are candidates, not validated complete coverage. | NR | Require end-to-end approved source and identify uncovered stages. |
| R24 | How do SAP MM and SD responsibilities differ? | Module overview | **L:** M02/M03, with short descriptions. | NR | Retrieve both relevant overviews; avoid asserting FFC's organizational responsibilities. |
| R25 | What do EKKO and EKPO represent? | MM table definitions | **P:** M02, T05–T07 and I03 mention the table names; no dedicated table dictionary. | NR | Mentions alone do not establish schema/fields; collect approved table references. |
| R26 | What is the relationship between VBAK and VBAP? | SD table definitions/relationship | **P:** M03, T02–T04 and I02 mention the names. | NR | Require explicit approved relationship evidence; do not invent join fields. |
| R27 | What material master and plant information is required before a goods receipt? | MM master data/prerequisites | **G:** no material-master/plant phrase found; commercial `materials.csv` is not a procedure source. | NR | Add approved prerequisites; exclude supplier/price records from procedure answers. |
| R28 | I get no authorization when releasing a purchase order. | Authorization plus MM incident | **P:** I02 contains a SU53 mention; generic authorization templates at E07–E1001/I07–I1001 are not full runbooks. | NR | Require authoritative diagnostic guidance; do not infer a role assignment or bypass. |
| R29 | What does SU53 show when troubleshooting an authorization failure? | Authorization tool explanation | **P:** I02 is a mention; no dedicated SU53 catalog record. | NR | Add approved authorization-check documentation; distinguish a mention from sufficient evidence. |
| R30 | Explain PFCG and how roles should be reviewed. | Authorization/role documentation | **G:** no PFCG whole-token occurrence in non-material corpus. | NR | Retrieve approved role-review evidence or state insufficient knowledge; never invent permissions. |
| R31 | My invoice cannot be posted because of a tax code error. | Invoice/tax-specific diagnosis | **G:** no tax phrase found. | NR | Add approved jurisdiction/release-specific material; no invented tax values or configuration. |
| R32 | What does ZFFC_DEMO_UNKNOWN_999 do? | Approved custom-transaction documentation | **U:** no approved custom-code evidence identified. | NR | Refuse to invent behavior; require authorized documentation. |
| R33 | What is FFC's purchase-order approval limit? | Approved company policy | **U:** no FFC policy evidence present. | NR | State that company policy is unavailable; no numerical guesses. |
| R34 | Which FFC employee should approve my purchase order? | Authorized company workflow/identity evidence | **U:** no approved approver/workflow evidence. | NR | Do not invent identities or expose unrelated commercial records. |
| R35 | My order is blocked. | Clarification before retrieval judgment | **A:** PO versus sales order and process stage unknown; E/I records cannot establish the intended incident. | NR | Ask a relevant disambiguation question before judging a diagnostic answer. |
| R36 | Posting failed. What should I do? | Clarify transaction/module/error | **A:** generic templates are possible lexical matches, not sufficient evidence. | NR | Clarify activity and symptom; avoid unrelated configuration recommendations. |
| R37 | What does error M7 021 mean? | Exact error-message documentation | **G:** exact phrase not found. Other GR candidates must not be treated as this exact message. | NR | Use an approved exact-identifier reference or explicitly disclose the gap. |
| R38 | How does S/4HANA flexible workflow differ from classic PO release? | Release-specific comparative documentation | **G:** no S/4HANA/flexible-workflow phrase or release metadata found. | NR | Add product/version-specific evidence; do not generalize classic references into a comparison. |
| R39 | How should a credit-blocked sales order be diagnosed? | SD/credit-specific troubleshooting | **G:** no credit phrase found. | NR | Add an approved credit-block runbook; generic authorization templates are insufficient. |
| R40 | My PO will not release, but I do not know the group/code or exact error. Can you give preliminary guidance? | Partial-evidence MM diagnosis | **P:** E03/I03 are brief candidates; key release fields lack documentation. | NR | Retrieve available approved evidence, label missing details and preliminary status; refuse unsupported steps if evidence is inadequate. |

## How to turn this into a real retrieval evaluation

1. Obtain separate authorization for read-only provider operations, and agree which index/namespace and synthetic inputs may be used. A local key being present is insufficient. Do not call `main.py`, `get_index()` from ingestion helpers, or any method that can create/delete/upsert while investigating the production index.
2. Verify index configuration/namespace read-only. Establish query/document encoder model revision, pooling and dimension equivalence before comparing retrieval metrics. Do not send company documents to a model endpoint for the equivalence check.
3. Have an SAP functional reviewer label approved records for each unambiguous supported query. Use relevance grades 0=irrelevant/unsafe, 1=related but insufficient, 2=directly supporting. Add release applicability, authority and confidentiality checks separately. Local phrase matches above are candidate pools, not completed judgments.
4. Record exact raw query and actual enriched query, configuration/model identity, filters, K, returned stable vector IDs in rank order, source row/page/version, scores, latency, errors, duplicate-family labels and judgments. Keep raw text private; store only authorized redacted evidence in reports.
5. Evaluate the retrieval component directly for these questions. For troubleshooting, also test the app's clarification/enrichment path with synthetic replies; early clarification means no retrieval occurred and should not be scored as a failed vector search. Log side-question/topic-switch behavior separately from relevance.
6. Compare a baseline with proposed changes against the same frozen corpus, query set and reviewer labels. Do not generate answers merely to infer that the retrieved documents were relevant. Any later Groq evaluation needs its own explicit authorization and a separate grounding rubric.

## Metrics and judgment rules

At K=5, a binary relevance label should normally mean grade 2: directly supporting, approved, release-applicable evidence. Related generic templates should not receive full credit.

| Metric | Definition / prerequisites | Result in this investigation |
| --- | --- | --- |
| Precision@5 | Directly supporting returned records in first five / 5; preregister handling of fewer than five returns. | Not measured: no retrieved ranks or labels. |
| MRR@5 | Mean reciprocal rank of first directly supporting record, zero if none in first five. | Not measured. |
| Recall@5 | Supporting records returned in first five / all supporting records for that query. Requires sufficiently complete relevance judgments. | Not measured; candidate mentions do not define the denominator. |
| nDCG@5 | Graded gain discounted by rank, normalized against the ideal ranking from reviewer judgments. | Not measured. |
| Duplicate frequency@5 | After first occurrence of each approved duplicate family, count repeated-family results / returned-result count. Report raw and family-aware relevance metrics. | Not measured. Local corpus repetition is not this metric. |
| Evidence sufficiency | Reviewer judges whether the retrieved set covers all requested claims/checks without unsupported steps. | Not measured for actual retrieval; local gaps/partial candidates are listed above. |
| Unsupported-question behavior | For U/G cases, measure retrieval false-support and explicit insufficiency/refusal rather than forcing a positive relevant result. | Not measured live. |

Ambiguous cases need an intended scenario or reviewer-approved clarification before relevance judgments. Unsupported cases have no positive evidence by definition of the approved corpus; Recall/nDCG denominators can be undefined and must be reported as such. Abstention is desirable when no authoritative support exists. A high similarity score does not establish a fact or a calibrated confidence probability.

Do not choose a relevance cutoff from these local scans or synthetic scores. Use a separate calibration set with supported, ambiguous and unsupported questions; reserve a holdout set for reporting. Include exact-code and semantic troubleshooting queries separately so an average does not hide systematic failures.

## Verified findings versus outstanding results

- Verified: local row candidates and lexical gaps above; repetition and reference-closure counts in `RAG_AUDIT.md`; 157 existing Python tests and 10 frontend tests pass; 12 final synthetic characterization checks confirm current parser/retrieval/source-summary behavior.
- Not verified: real top-five results, live duplicate rates, relevance/grounding metrics, encoder equivalence, production configuration, real SAP procedure correctness, FFC policy, answer citations or provider health.
- Required next step after review: approve a small authoritative demonstration evidence set and labeled evaluation plan before implementing retrieval/corpus changes. No data mutation, push or deployment occurred during this stage.
