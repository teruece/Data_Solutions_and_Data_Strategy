# Delivering a retail sales reporting data product

This case study uses synthetic retail sales to show how a delivery lead can take a reporting request from scope through release and support. The [repository demo](../README.md) runs the Python and SQLite load locally. The [Power BI semantic model](power-bi-semantic-model.md), UAT and production release steps below are a reference for a rollout.

## Scope and priorities

A commercial analyst needs to compare daily sales units and net sales in GBP by market and SKU. A corrected source delivery should replace the previous value for the same business key. The analyst should be able to reconcile a reported number with the source file and know when a delivery failed.

| Priority | Deliverable | Reason |
| --- | --- | --- |
| P0 | Load daily sales to `fact_sales_daily` at one row per `(sale_date, market_code, sku)` | Establish a stable grain before aggregating sales or joining dimensions. |
| P0 | Reconcile units and GBP, prove replay is safe, and reject an invalid batch in full | Protect totals when a file is resent, corrected, or malformed. |
| P0 for report rollout | Agree KPI definitions and prove market access with representative users | Business users need a shared definition and appropriate access before release. |
| P1 | Automate scheduling, operational alerts and freshness reporting | Make unattended operation supportable once the load contract is proven. |
| Separate scope | Source onboarding, currency conversion and deletions | Each would change the contract and require its own reconciliation and acceptance criteria. |

The source supplies complete values per business key and normalises `net_sales_gbp` to GBP. The load stores this measure as integer `net_sales_pence` in the fact table. Reporting presents it as `net_sales_gbp`. Corrections use a new batch ID. The delivery team needs an agreed source sequencing process before automating arrival-based upserts, since a stale extract under a new batch ID could overwrite a newer value.

## Decision and risk log

| ID | Type | Decision or action | Owner |
| --- | --- | --- | --- |
| DEC-01 | Decision | Publish daily sales at date, market and SKU grain. Store GBP as integer pence and present GBP in reporting. Record the KPI definition and source ownership. | Business owner |
| DEC-02 | Decision | Treat each batch ID and file digest pair as an immutable delivery. An identical re-send is a no-op. A reused ID with changed bytes requires a corrected delivery under a new ID. | Data engineering lead |
| RISK-01 | Risk | A stale delivery arrives after a correction. Agree the authoritative batch sequence with the source owner and escalate an uncertain sequence before loading. | Data engineering lead |
| RISK-02 | Risk | Market access maps drift when staff move. Require a named entitlement owner and rerun allow and deny tests after mapping changes. | Platform owner |
| DEP-01 | Dependency | Obtain representative market and viewer accounts, a source reconciliation extract, and a release window before report UAT. | Delivery lead |

## Ownership

| Activity | Accountable | Responsible | Consulted | Informed |
| --- | --- | --- | --- | --- |
| Define KPIs and sign off reconciled totals | Business owner | Commercial analyst | Source owner, BI lead | Delivery lead |
| Agree source contract and route corrections | Source owner | Source support | Data engineering lead | Commercial analyst |
| Validate the load and maintain recovery steps | Data engineering lead | Data engineer | Source owner, platform owner | Delivery lead |
| Verify market entitlements and service access | Platform owner | BI lead | Business owner, commercial analyst | Delivery lead |
| Record the go/no-go decision and coordinate deployment | Delivery lead | Release coordinator | Business owner, platform owner, data engineering lead | Support team, report users |
| Triage incidents after handover | Platform owner | Support team | Data engineering lead, BI lead, source owner | Business owner |

## Acceptance and evidence

Create a release evidence record that links each criterion to a run result, the exact fixture or source snapshot, the version tested, and the named owner for sign-off. Record expected and actual values with the same date, market and SKU filters. Mark tests that require a deployed model as pending until they have run in the target environment.

| ID | Test and expected result | Evidence and sign-off |
| --- | --- | --- |
| QA-01 | Load an approved fixture. The fact contains one row per business key. Units and GBP reconcile by date and market and at the grand total. | Source and SQLite query results, plus the batch ID. Data engineering lead. |
| QA-02 | Re-send the identical file under the same batch ID. Fact rows and totals stay the same. Then change the file under that ID. The load fails and the prior state is preserved. | First load, replay and conflict logs, plus before and after fact and ledger comparisons. Data engineering lead. |
| QA-03 | Submit one batch with a duplicate business key and one with an invalid row. Each batch fails as a whole. | Rejection evidence and before and after fact and ledger comparisons. Data engineering lead. |
| QA-04 | Submit a corrected value under a new batch ID. The target key takes the corrected value, the row count for that key remains one, and unrelated rows are unchanged. | Key-level diff, totals delta and accepted batch ID. Data engineering lead. |
| UAT-01 | The analyst selects an agreed period and market in the report. Units and GBP reconcile with the approved fact query, including totals when the analyst clears the SKU filter. | Filters, source query result, visual result and sign-off. Business owner. |
| UAT-02 | A test viewer assigned one market can see its rows and totals. A viewer with two markets sees both. An unmapped viewer sees no market data. Exercise direct report access with representative viewer accounts. | Test identities, entitlement mapping and observed results. Platform owner. |
| OPS-01 | Recover a test release from a known-good state. Confirm the first accepted batch after recovery reconciles and the reporting layer reflects the recovered data. | Recovery record, before and after totals, report refresh record and handover acknowledgement. Platform owner. |

## Release and rollback

1. **Prepare.** Record the release commit, source or fixture version, last accepted batch and expected reporting totals. Preserve a recoverable copy of the data state and the prior semantic model version before changing either layer.
2. **Decide.** The delivery lead records go or no-go after reviewing P0 evidence with the business and technical owners. A failed reconciliation, unverified market access, or untested recovery blocks a production rollout. Keep the failed criterion and its owner in the decision record.
3. **Deploy and verify.** Run the load before refreshing the model. Reconcile one market to the approved result and verify allow and deny access with representative viewers. Capture the accepted batch and semantic model version in the release record.
4. **Recover if needed.** Pause scheduled loads and model refreshes. For a report-only defect, deploy the previous compatible model version. For corrupted data, restore the fact and batch ledger from the same verified recovery point, then replay approved source files in their authoritative order. Rerun reconciliation and access checks before resuming service.

## Day-two support

The support team compares the expected source cadence, the most recent accepted batch and the last successful semantic model refresh. A current load and stale report point to a refresh issue. A stale load prompts a source or ingestion check. A successful refresh only confirms that the model refreshed.

| Symptom | First check and next action |
| --- | --- |
| Source file missing or late | Confirm the delivery with the source owner. Tell report users the last verified data date if their reporting is affected. |
| Invalid or duplicate row | Record the batch ID and rejection details. Ask the source owner for a corrected delivery and rerun the affected reconciliation after loading it. |
| Changed file under an accepted ID | Compare fingerprints and establish which delivery is authoritative. Have the source owner issue a new ID if the business values need correction. |
| Incorrect market access | Have the platform owner contain the access issue, correct and verify the mapping with viewer accounts, and record the affected market scope. |

See the [pipeline design](pipeline-design.md) for the source contract and recovery model and the [Power BI semantic model](power-bi-semantic-model.md) for KPI and access design.
