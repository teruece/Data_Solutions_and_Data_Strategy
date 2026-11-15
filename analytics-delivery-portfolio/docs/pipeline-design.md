# Daily retail sales pipeline

The pipeline loads synthetic retail sell-through into a daily sales fact that analysts can aggregate by date, market, and SKU. The demo uses Python's standard library and SQLite to address duplicate keys, partial loads, and accidental replay. The [README](../README.md) contains the commands to run it.

## Data contract

| Field | Meaning | Rule |
| --- | --- | --- |
| `sale_date` | Reporting date supplied by the source | ISO calendar date (`YYYY-MM-DD`) |
| `market_code` | Market identifier | Exactly three uppercase ASCII letters |
| `sku` | Product identifier | 1–24 uppercase ASCII letters, digits, or hyphens, starting with a letter or digit |
| `units` | Daily units for the key | Unsigned whole number of up to nine digits |
| `net_sales_gbp` | Daily net sales for the key | Unsigned GBP amount with up to 12 digits before the decimal point and exactly two after it |

The CSV uses UTF-8, optionally with a byte order mark, and the header fields appear in the order shown. The business key is (`sale_date`, `market_code`, `sku`). One input row carries the complete authoritative daily value for that key. The source handles any currency conversion before delivery. File omissions leave existing keys in place. Support for deletions would require an explicit source instruction and a contract change.

SQLite stores `sale_date` as ISO text and the monetary amount as an integer in `net_sales_pence`. Storing currency as pence keeps additions and reconciliations exact. The report presents those totals as `net_sales_gbp`.

## Load and replay

| Step | What happens | Integrity check |
| --- | --- | --- |
| Identify the batch | Read the batch ID and compute a SHA-256 digest from the input file bytes. | A previously accepted ID with the same digest returns a no-op. An accepted ID with different bytes raises a conflict. |
| Validate the source | Parse the rows and check field values and key uniqueness within the file. | An invalid value or duplicate business key rejects the whole batch. |
| Apply the batch | Load accepted rows into `fact_sales_daily` using `INSERT … ON CONFLICT … DO UPDATE` on the business key. | An incoming row replaces the existing measures for its key. New keys are inserted. |
| Record success | Write the accepted batch ID and digest to `batch_ledger` in the same transaction as the fact changes. | After a rollback, a retry can apply the batch. After a successful commit, an exact replay returns a no-op. |

In the sample, the first file delivers 135 units and £202.50 for `2026-02-14 / LON / SPARK-330`. The correction arrives under a new batch ID with 140 units and £210.00 for that key. It also adds a new SKU row. Replaying either accepted batch under its original ID leaves the corrected fact in place.

The demo applies new batches in load order. A late batch can correct an old sales date, and an older file submitted under a fresh ID can overwrite a later correction. In an operated feed, retain the original ID and file bytes for retries, use a single writer per target, and confirm source precedence before applying a backfill to a date already loaded. Add an upstream revision or effective timestamp and a stale-update rule if automated precedence becomes a requirement.

## Operator runbook

| Signal | Response | Evidence to capture |
| --- | --- | --- |
| Invalid row or duplicate key | Hold the entire source file in quarantine outside the reporting inputs. Ask the source owner to correct it before resubmission. | Batch ID, original filename and digest, rejection reason, and offending rows or keys where available. |
| Batch ID conflict | Locate the accepted file by its ledger digest. Confirm whether the incoming file is an authorised correction and issue a new ID if it is. | Both digests, original acceptance record, and correction approval. |
| Load interrupted | Retry the original bytes with the original ID and check the ledger result before releasing the dataset. | Retry outcome and target totals for the affected date and market. |
| Dashboard totals drift | Reconcile affected keys and totals against the authoritative extract. Verify market/date filters and check which correction is current. | Expected and actual row counts, units, and GBP totals at the affected grain. |

The demo reports rejected batches in its command output. A shared feed should retain the original rejected file in a managed quarantine location with an alert and a record of the resolution. For a schema change, version the source contract, validate a representative fixture against both the current and new paths, and update downstream models that consume the affected fields. A change to the business grain, currency meaning, or measure semantics needs a new reconciliation baseline before cutover.

## Microsoft Fabric migration design

| Layer | Proposed role | Cutover check |
| --- | --- | --- |
| Bronze | Land each original extract with batch identity and digest for inspection and replay. | Recover the exact source bytes for an accepted batch. |
| Silver | Parse the contract, validate values and keys, and route rejected batches to quarantine. | Duplicate and invalid files stay outside the accepted set. |
| Gold | Publish the daily fact for the [Power BI semantic model](power-bi-semantic-model.md). | SQLite and Fabric produce the same keys, units, and monetary totals to the penny from the same retained fixtures. |

Treat fact promotion and ledger updates as a recovery design requirement. If they run as separate operations, define a resumable batch state and test interruption between those operations before releasing the feed. Run both pipelines against the same inputs through a correction and replay cycle, then apply the [delivery gates](delivery-playbook.md) before switching the reporting connection.
