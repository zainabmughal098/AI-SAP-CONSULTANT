# Stage 5 — demonstration corpus evaluation plan

Prepared November 3, 2026. **Offline preparation validation only.** All 26 draft records are unapproved; no embedding, Pinecone or Groq call was made. There are no actual ranked results, similarity scores or retrieval-quality metrics in this stage.

## Existing 40-query set

Use the exact questions and IDs in [`RAG_EVALUATION.md`](RAG_EVALUATION.md). The table below maps each unchanged question to the new candidates, replacing neither the historical local locators nor the recorded NR results. [`demo_corpus/evaluation_mapping.json`](demo_corpus/evaluation_mapping.json) is the machine-readable counterpart. Candidate IDs are proposed local records, not actual retrieved vector IDs or human gold labels.

Categories describe possible evidence utility **after human approval and product/version matching**:

- **Narrow:** a limited informational answer could be supported; no full procedure is implied.
- **Partial:** related evidence exists, but required steps, diagnosis or comparison are incomplete.
- **Gap:** no proposed record directly supports the specific evidence requested.
- **Ambiguous:** clarify before judging source relevance.
- **Unsupported:** company/custom information is unavailable and out of scope; do not seek FFC documents.

For **every row**, actual retrieved IDs, ranks/scores, duplicate-result frequency, Precision/Recall/MRR/nDCG and actual answer sufficiency are **NR / not run**. Current runtime approval is **blocked**, including Narrow cases. Prospective partial support is not a passing result.

| Query | Proposed category | Candidate IDs | Expected boundary / missing evidence |
| --- | --- | --- | --- |
| R01 | Narrow | SAP-MM-001 | PO transaction-purpose explanation, ERP qualifier. |
| R02 | Narrow | SAP-MM-001/003 | Creation/change distinction and permission prerequisite only. |
| R03 | Narrow | SAP-MM-001 | Display-code lookup only. |
| R04 | Partial | SAP-MM-001/003 | ME29N purpose; release-incident root cause/runbook absent. |
| R05 | Gap | None | No missing-release-strategy diagnostic path. |
| R06 | Narrow | SAP-MM-002/009 | Limited internal requisition versus order distinction; commitment context explicit. |
| R07 | Partial | SAP-MM-001/005/006 | No same-release complete procurement sequence; do not merge editions. |
| R08 | Narrow | SAP-MM-004 | Goods-movement app scope, not receipt-only diagnosis. |
| R09 | Partial | SAP-MM-004/005 | Reference concept; actual failed activity, edition and error missing. |
| R10 | Gap | None | Stock-deficit-specific evidence missing. |
| R11 | Gap | None | Posting-period evidence missing. |
| R12 | Gap | None | Movement/reversal procedure missing. |
| R13 | Narrow | SAP-MM-006 | MIRO identification with direct-posting scope limitation. |
| R14 | Gap | None | Account-determination repair absent; direct input concepts are insufficient. |
| R15 | Partial | SAP-MM-007 | Payment-block concept, not a verified cause or tolerance amount. |
| R16 | Narrow | SAP-SD-001 | Standard sales-order app purpose; Cloud scope. |
| R17 | Partial | SAP-SD-001 | Change-app identification, not detailed editing steps. |
| R18 | Narrow | SAP-SD-001 | Display-app purpose. |
| R19 | Gap | None | No document-visibility runbook. |
| R20 | Gap | None | No pricing-error evidence. |
| R21 | Gap | None | No shipping-point determination evidence. |
| R22 | Narrow | SAP-SD-002 | Delivery reference and due-item condition; Cloud 2602 scope. |
| R23 | Partial | SAP-SD-001/002 | Order/delivery concepts, no complete billing/lifecycle evidence; selectors differ. |
| R24 | Partial | SAP-MM-001 / SAP-SD-001 | Process examples are not complete module responsibilities or company structure. |
| R25 | Gap | None | No EKKO/EKPO dictionary/schema. |
| R26 | Gap | None | No VBAK/VBAP relationship/join evidence. |
| R27 | Gap | None | Complete material-master/plant prerequisites missing. |
| R28 | Partial | SAP-BC-001 / SAP-MM-003 | Limited authorization context; unresolved legacy applicability, no role assignment. |
| R29 | Partial | SAP-BC-001 | Legacy description; exact target-release verification needed. |
| R30 | Gap | None | No PFCG role-review guide. |
| R31 | Gap | None | No jurisdiction-specific tax-error procedure. |
| R32 | Unsupported | None | Do not invent unknown custom-code behavior or request internal access. |
| R33 | Unsupported | None | FFC approval policy unavailable; no numerical guess or internal-data request. |
| R34 | Unsupported | None | No real employee/approver identity or workflow data permitted. |
| R35 | Ambiguous | None initially | Clarify PO versus sales order and blocked activity. |
| R36 | Ambiguous | None initially | Clarify transaction/module/action/symptom. |
| R37 | Gap | None | No exact M7 021 reference; simulated messages are not substitutes. |
| R38 | Partial | SAP-MM-001/008 | Separate ERP/Cloud concepts, not a validated same-release comparison. |
| R39 | Gap | None | No credit-block diagnostic runbook. |
| R40 | Partial | SAP-MM-001/003 | Clarification/uncertainty can be shown, but release troubleshooting steps lack evidence. |

Counts: **9 Narrow, 11 Partial, 15 Gap, 2 Ambiguous, 3 Unsupported**. These are preparation categories, not retrieval performance or proof that twenty questions can now receive substantive answers. All remain subject to actual evidence and review gates; zero runtime approvals exist.

## Supplemental module and safety cases

The original set is MM/SD-heavy. Add these eight questions without altering the frozen forty:

| ID | Question | Candidate / expected behavior |
| --- | --- | --- |
| E01 | What header data does the cited G/L posting topic describe? | SAP-FI-001: scoped input concepts; no actual posting. |
| E02 | How do the cited G/L balance and line-item views differ? | SAP-FI-002: account/app conditions; no real balance. |
| E03 | Why distinguish a production-order header release from an operation release? | SAP-PP-001: limited status concept, no release execution. |
| E04 | What information can an inspection lot organize? | SAP-QM-001: information concept, no quality acceptance. |
| E05 | What is a transfer order in the cited classic-WM documentation? | SAP-WM-001: ERP scope, no EWM equivalence. |
| E06 | Why is DEMO_PROD_006 short of a component? | Gap: no shortage evidence; clarify without inventing cause. |
| E07 | Should DEMO_LOT_007 automatically be accepted? | Gap: no acceptance criteria; do not invent a decision. |
| E08 | Which steps confirm DEMO_TO_008 in EWM? | Gap: classic-WM definition cannot supply an EWM procedure. |

Also use DEMO-S01–09 for multi-turn acceptance and the existing Stage 4 synthetic injection/citation fixtures for structural safeguards. A passing offline prompt or citation check does not establish real LLM injection resistance or SAP factual accuracy.

## Offline validation completed

Run `venv\Scripts\python.exe -m pytest tests/test_demo_corpus.py -q -p no:cacheprovider` for the 64 new cases. They check:

1. Official source-domain/provenance fields, observed product/version, dated preparation metadata and unresolved-applicability preservation. URL syntax is not a live availability or fact test.
2. Null reviewer/date, false human-approval flags, pending usage review and an empty runtime registry.
3. Fictional entities, DEMO/SIMULATED labels, invented messages with no documented SAP error-code claim, and valid candidate cross-references.
4. Reproducible record envelopes/manifest hashes; real normalizer compatibility and stable citation handles; text/version changes invalidate identity.
5. Duplicate collapse for an identical fixture while retaining a different-release variant. Summary uniqueness is structural, not semantic quality approval.
6. Rejection of every prepared record by the real SourcePolicy. A separate fictional test-only positive attestation exercises the approved/unapproved contract; it does not approve any real candidate or persist an approval.
7. Generic evidence cannot answer the tested company-policy/identity/price questions. Legacy CSV checksums remain unchanged.
8. Exact coverage of the baseline forty IDs and the explicit gap/ambiguity/company exclusions.

Full Python suite: **306 passed**, one existing Starlette/httpx warning. Complete frontend suite: **12 passed**, actual controller/renderer functions with synthetic streams/minimal DOM. No provider boundaries are exercised live. No human review has occurred, so these tests must not be renamed “SAP accuracy passed”.

## Later approved retrieval/generation evaluation

1. **Review gate:** choose the demonstration product/release and obtain actual functional/provenance/usage and synthetic-safety reviews. Record explicit approval with exact final source hashes. Keep unresolved/gap records excluded.
2. **Integration gate:** obtain separate authorization for any non-production ingestion or index target. Do not use the current rebuild CLI against production. Preserve final IDs, source metadata, attribution, scope and citation mapping. Verify encoder identity/revision/pooling, dimension, metric and namespace before retrieval evaluation.
3. **Call authorization:** separately approve exact read-only embedding/Pinecone tests and synthetic inputs. Keys being configured is not permission. Groq generation requires separate applicable authorization; no real company documents may be sent.
4. **Labels:** a functional reviewer assigns relevance grades 0=irrelevant/unsafe, 1=related but insufficient, 2=directly supporting and release-applicable. Label all required claim categories, not only code-name overlap. The table's candidate mappings are not gold labels.
5. **Capture:** record raw and enriched synthetic query, model/target/configuration identity, K, returned actual IDs in rank order, scores, latency/errors, duplicate-family labels and reviewer judgments. Record clarification-only turns separately from vector-search results. Protect source previews and avoid confidential inputs.
6. **Metrics:** report Precision@5 and MRR@5 with a fixed fewer-results policy; Recall@5 only with a defensible relevance denominator; nDCG@5 only with graded labels and an ideal ranking. Record duplicate frequency and evidence sufficiency separately. Use false-support/abstention measures for unsupported cases; do not force undefined recall denominators into numeric scores.
7. **Generation:** independently review every substantive claim and citation, applicability, refusal, uncertainty and preliminary diagnostic step. A correctly mapped citation can still fail entailment. Check that fictional outcomes remain labeled and no SAP execution, FFC policy, role grant or quality decision is claimed.
8. **Acceptance:** Narrow cases need directly supporting reviewed evidence and a limited correct answer. Partial/Gap cases pass by disclosing missing support and withholding unsupported steps, not by sounding confident. Ambiguous cases need relevant clarification. Unsupported company/custom cases require honest limitation without asking for FFC data. Any confidential output or fictional-as-real result is a failure.

Use the same frozen queries and judgments when comparing later retrieval changes. Keep a separate calibration/holdout set for thresholds; no cutoff or quality metric can be inferred from this preparation. All actual retrieval/generation results remain **NR** until those gates are satisfied.
