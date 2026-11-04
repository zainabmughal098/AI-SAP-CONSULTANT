# Stage 5 — DEMO / SIMULATED scenarios

Prepared November 3, 2026. **Every company, supplier, user, material, document, message, observation and outcome below is fictional.** No real FFC data or policy is used. No SAP system was accessed and no transaction was executed. Human safety approval is pending for all nine scenarios.

These are proposed facilitator scripts, not recorded application runs or validated SAP test data. Some deliberately use identifiers longer than real SAP fields allow: they are conversation fixtures, not executable payloads. Machine-readable originals, complete reply suggestions, limitations and forbidden claims are in [`demo_corpus/scenarios.json`](demo_corpus/scenarios.json).

## Fictional setting

| Entity | DEMO / SIMULATED value |
| --- | --- |
| Company | DEMO Lantern Components (fictional; unrelated to FFC) |
| Supplier | DEMO Paper Kite Supply (fictional) |
| User | DEMO_USER_A (fictional) |
| Materials | DEMO_MAT_BOLT_A, DEMO_MAT_KIT_B, DEMO_MAT_ASSEMBLY_C, DEMO_MAT_BATCH_D, DEMO_MAT_PALLET_E, DEMO_MAT_SERVICE_F |
| Storage bin / company code | DEMO_BIN_A / DEMO_CC (fictional conversation identifiers, not validated SAP field values) |
| Documents | DEMO_PO_001/002, DEMO_INV_003, DEMO_SO_004, DEMO_AUTH_CASE_005, DEMO_PROD_006, DEMO_LOT_007, DEMO_TO_008, DEMO_FI_009 |

No supplier prices, personal identities, tax values, real document numbers or approval thresholds are needed. No fictional rule should be described as an actual FFC or universal SAP rule.

## Scenario scripts

| ID / module | Opening question and simulated observation | Suggested follow-up / expected behavior | Candidate references and limits |
| --- | --- | --- | --- |
| DEMO-S01 / MM | “DEMO_PO_001 will not release in ME29N. This is a fictional scenario.” Message: **SIMULATED: release decision pending**. Group/code/approver deliberately unavailable. | Respond “I don't know” / “not sure”, then ask for preliminary guidance. Reuse supplied details; do not treat unknowns as evidence or invent a release cause. A later mock approval-state update is a facilitator report, not an executed release. | SAP-MM-001/003: narrow purpose/permission context only; no release-strategy runbook. |
| DEMO-S02 / MM | “DEMO goods receipt for DEMO_PO_002 fails in MIGO; material DEMO_MAT_BOLT_A.” Message: **SIMULATED: document input requires review**. | State that no real SAP error number exists. Preserve the reference, clarify activity/edition, and avoid guessing movement type, stock deficit or period closure. Mock status changing to “reviewed” is not posting. | SAP-MM-004/005: separate on-premise/Cloud app evidence; not a merged procedure. |
| DEMO-S03 / MM | “DEMO invoice DEMO_INV_003 has a problem in MIRO.” Message: **SIMULATED: invoice needs review**. | Correct the report: “Actually it posted in the fictional scenario, but payment is blocked.” Then say the configured tolerance is unknown. Honor the corrected symptom; do not invent a threshold or unblock/payment operation. | SAP-MM-006/007: direct-posting and payment-block concepts; exact release must be selected. |
| DEMO-S04 / SD | “DEMO sales order DEMO_SO_004 is not visible in VA03.” Message: **SIMULATED: document is not shown**. | Correct to “Actually transaction is VA02”, leave sales area unknown, then “Explain VA01 instead”. Preserve corrections and explicit topic change; do not infer deletion/authorization cause. | SAP-SD-001/002: app-purpose/reference concepts; no visibility diagnosis. |
| DEMO-S05 / BC | “In a DEMO scenario I am not authorized to change DEMO_PO_001 in ME22N.” Message: **SIMULATED: requested activity denied**. | Supply fictional DEMO_USER_A; state that no real authorization trace exists. Ask what SU53 shows. A diagnostic explanation must not become a role-grant recommendation. | SAP-BC-001/ SAP-MM-003: release applicability unresolved for the legacy authorization article. No real trace should be requested. |
| DEMO-S06 / PP | “DEMO_PROD_006 is not ready for processing. What status information would help?” Message: **SIMULATED: production status review pending**. | Report that only one fictional operation is released and the header status is unknown. Keep reported status separate from verified documentation. No shortage/capacity cause or production release is established. | SAP-PP-001: conceptual order/operation distinction only; current engine has no specialized PP decision tree. |
| DEMO-S07 / QM | “DEMO_LOT_007 has incomplete quality information. What should I clarify?” Message: **SIMULATED: inspection information incomplete**. | Leave lot origin unknown and state that no usage decision was supplied. Missing information is not rejection/acceptance evidence. Do not release stock or prescribe a quality threshold. | SAP-QM-001: information concept, not acceptance criteria or a stock-release procedure. |
| DEMO-S08 / WM | “What is the purpose of DEMO_TO_008 in this fictional classic-WM scenario?” Message: **SIMULATED: warehouse reference unclear**. | Leave source document unknown and clarify classic WM. A facilitator-supplied relationship is fictional evidence; no physical stock movement or confirmation is observed. | SAP-WM-001: classic ERP scope, no EWM task/confirmation equivalence. |
| DEMO-S09 / FI | “Which header information belongs in the fictional G/L discussion for DEMO_FI_009?” Message: **SIMULATED: header information not supplied**. | Supply only fictional DEMO_CC. No real balance or posting date is provided. Completing a demonstration worksheet is not an accounting posting or reconciliation. | SAP-FI-001/002: FPS01/FPS02 scopes must be reviewed separately. |

Transaction/app names appearing in a scenario are reference targets from pending public candidates. They do not make that scenario factual SAP documentation or establish the existence of a live system. Every `documented_error_codes` list is empty: **SIMULATED messages are invented dialogue, never SAP message class/number pairs**. In particular, these messages do not explain the benchmark's exact M7 021 question.

## Execution and evaluation rules

At the current approval state, the app can demonstrate relevant clarification, supplied-field extraction, unknown handling, corrections, explicit topic changes and safe evidence limitations. It must not produce a substantive procedure from these unapproved records. The scripted conversations have not been run against live services; suggested replies are not guaranteed to match each pending questionnaire field.

For offline validation, use the existing network-denied tests and synthetic provider fixtures. For a later approved interactive demonstration, choose one product/release, complete source and scenario review, use an explicitly authorized non-production evidence target, and obtain separate provider-call authorization. Do not start the ingestion CLI or submit a real chat to “test” these drafts.

A functional reviewer should score separately:

- Correct distinction between documented concepts, fictional assumptions and user reports.
- Relevant non-repeated clarification, unknown/correction handling and topic preservation.
- Honest source limitations and preliminary wording; no invented root cause, codes, tables or policy.
- Citation-to-record mapping after approval, without treating a citation as proof of entailment.
- No role bypass, quality acceptance, posting, stock movement, production release or live-system claim.

The expected simulated outcome is always a worksheet/facilitator state change, not an SAP-system result. Reject any answer that represents fictional companies or outcomes as FFC facts.
