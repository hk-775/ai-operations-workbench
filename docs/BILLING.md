# Bedrock billing reconciliation

This feature is in **0.5.0 source development**, requiring **schema 4**. The
existing AWS test workspaces have been
[upgraded and verified](VERIFICATION-HOSTED-BILLING.md). The published v0.4.0
archive uses schema 3 and does not include it; v0.5.0 has not been published.

An administrator imports a complete monthly Bedrock billing snapshot, links
comparable charge groups to captured application sources, and inspects the
difference from saved API estimates. Viewers and analysts can inspect and export
the result. No AWS API, Athena query, model invocation, or routing change runs
from this screen.

## Try the complete workflow

1. Open the authenticated pilot and choose **Billing reconciliation**.
2. Select **Load fictional billing example** as an administrator.
3. Inspect the two-call task comparison, unassigned charges, and separate credit.
4. Select **Export reconciliation** for the normalized records, content hashes,
   declared mappings, captured-call counts, limitations, and exact Decimal totals.
5. Select **Inspect … tasks** to see the source's calls in the billing month.
   This navigation includes every model in that source; the comparison itself
   filters the exact model, region, service tier, and performance mode.

The example is explicitly synthetic and idempotent. It adds a dedicated fixture
source and two fixture events, makes zero provider calls, and remains separate
from normal usage totals and ordinary imported bills. Its October 2026 period
is fixed. When usage retention has removed that period, use a local test
workspace to explore it.

| Fictional example evidence | USD |
|---|---:|
| Imported charges | 0.0121475 |
| Input/output groups linked to two captured calls | 0.0001475 |
| Those captured calls' saved estimate | 0.0001295 |
| Charges minus estimate | 0.000018 |
| Unassigned positive charges | 0.014 |
| Unassigned credit | -0.002 |
| Unassigned net charges | 0.012 |

These are authored example amounts, not measured AWS charges or realized savings.

## Supply a billing snapshot

Use **Import a complete Bedrock billing snapshot**. Select the usage account
(which can differ from the payer account), billing month in UTC, currency, and
all CSV parts from **one complete export generation**. Preview before importing.
CSV limits are 20 files, 8 MB of decoded UTF-8 text, 20,000 rows, 400 columns, and
500 distinct charge groups. The JSON request has an additional 16.5 MB wire limit.
Gzip/Parquet, mixed-account Bedrock exports, automatic AWS downloads, and
incremental append imports are not supported.

The importer checks each Bedrock row's account, currency, and exact monthly
billing boundaries. Rows explicitly belonging to another service are counted
separately and excluded. Missing service identity, required billing values,
conflicting rows, malformed CSV, or mismatched scope rejects the entire upload.
Records without user tags or model IDs are retained. Missing usage timestamps,
region, or supported charge type prevent linking; they do not discard the charge.

Select Legacy CUR or CUR 2.0 according to the CSV headers:

| Required field | Legacy CUR | CUR 2.0 |
|---|---|---|
| Line identity | `identity/LineItemId` | `identity_line_item_id` |
| Service | `lineItem/ProductCode` or `product/servicecode` | `line_item_product_code` |
| Usage account | `lineItem/UsageAccountId` | `line_item_usage_account_id` |
| Billing start | `bill/BillingPeriodStartDate` | `bill_billing_period_start_date` |
| Billing end | `bill/BillingPeriodEndDate` | `bill_billing_period_end_date` |
| Currency | `lineItem/CurrencyCode` | `line_item_currency_code` |
| Charge type | `lineItem/LineItemType` | `line_item_line_item_type` |
| Unblended cost | `lineItem/UnblendedCost` | `line_item_unblended_cost` |

Include these optional columns whenever available:

| Evidence | Legacy CUR | CUR 2.0 projection |
|---|---|---|
| Net unblended cost | `lineItem/NetUnblendedCost` | `line_item_net_unblended_cost` |
| Identity interval | `identity/TimeInterval` | `identity_time_interval` |
| Usage start/end | `lineItem/UsageStartDate`, `lineItem/UsageEndDate` | `line_item_usage_start_date`, `line_item_usage_end_date` |
| Usage type/operation | `lineItem/UsageType`, `lineItem/Operation` | `line_item_usage_type`, `line_item_operation` |
| Quantity/unit | `lineItem/UsageAmount`, `pricing/unit` | `line_item_usage_amount`, `pricing_unit` |
| Invoice ID | `bill/InvoiceId` | `bill_invoice_id` |
| Region code | `product/regionCode` | `product_region_code` |
| SKU | `product/sku` | `product_sku` |
| Model display hint | `product/modelId` | `product_model_id` |

CUR 2.0 product attributes vary. Project the verified attributes from your
export into the region/SKU/model columns above; these projection names are
Workbench's input contract, not a claim that every export has those native
columns. Alternatively, `product` can contain a JSON object with `region_code`
or `regionCode`, `sku`, and `model_id`/`modelId`/`model`. Athena's non-JSON map
display text is not accepted. Workbench never guesses a runtime model/profile
ID or region from a display name, SKU, usage type, or ARN.

Preserve account and identity fields as text; spreadsheet conversion can remove
leading zeroes. Billing timestamps without a suffix are interpreted as UTC.
Usage end is exclusive. Financial values remain finite Decimal text with up to
18 decimal places and absolute value below one trillion per row. Net unblended
cost is used when supplied, otherwise unblended cost; each row retains its
basis. Missing cost is rejected rather than replaced with zero. List prices,
amortized/effective rates, and foreign exchange are never substituted.
Reported quantity retains its original unit and fractional precision; no token
conversion is assumed.

## Refreshes, identity, and provenance

Account, month, currency, and synthetic/imported evidence define a report family.
Changed accepted contents create a new immutable revision and supersede the
current snapshot. Exact replay of the current contents does nothing. Replaying
superseded contents is rejected. A stale preview receives a conflict and must be
previewed again. Nothing is appended to a prior monthly total.

Within a submission, identical rows with the same line identity, identity
interval, and usage interval are deduplicated. Conflicting occurrences reject
the snapshot. AWS line IDs are not assumed stable across refreshes or globally
unique across partitions; supply one complete generation, not overlapping
generations. Hashes identify the normalized snapshot and submitted CSV text.
They do not authenticate the publisher, prove export completeness, or preserve
an externally signed original file. Keep your original export separately under
your company's evidence policy.

Missing invoice IDs are labeled provisional. Supplied IDs remain evidence from
the upload, not independent invoice validation. A header-only empty snapshot
records an empty import, not proof of a zero AWS invoice.

## Declare a comparison scope

Select eligible nonnegative `Usage` groups together, including input and output,
and declare their application sources, exact captured model ID, region, service
tier, and performance. The billing group dimensions retain charge type, usage
type, operation, region, unit, SKU, and model hint.

The administrator attests that each selected source belongs to the stated AWS
usage account and that the groups cover this captured scope. The binding is
persistent configuration. A source cannot span accounts; use a separate source
for each account. To correct an erroneous account binding, create a correctly
scoped source and map the appropriate data rather than rewriting its history.

A group can be selected once, and overlapping source/model/region/mode scopes
cannot reuse a captured estimate within a snapshot. Input/output groups for one
scope must be combined. Up to 100 comparisons are supported per report. Exact,
still-eligible selections carry forward to refreshed snapshots with a visible
revision reference. Removed or changed dimensions require a new selection.
Historical snapshots are read-only; unlinking current groups retains their
charges as unassigned.

Comparisons use the billing month and persisted captured estimates; events
are never repriced. SQL aggregation uses integer nanodollars and Decimal text.
No matching calls, unsupported prices, incomplete attempts/additional charges,
or a usage-retention gap makes the comparable total and variance unavailable.
The known subtotal and specific gap remain visible. Genuine zero estimates
from completely captured zero-usage calls can compare as zero.

Imported currency is preserved. Captured estimates are USD, so non-USD records
stay unassigned. Fees, tax, refunds, credits, missing-region lines, unsupported
charge types, and out-of-period usage stay visible. Positive and negative
unassigned values are reported separately even when the net is zero.

## Interpret the result

`Imported charges = linked charges + unassigned charges`.
Linked means a declared group selection has matching captured calls. It does
not prove that capture is complete or that the bill belongs to those exact tasks.
Incomplete captured scopes can be linked while their comparison stays unavailable.
Selected scopes without calls remain unassigned.

A signed difference is **imported group charges minus the matching captured
API estimate**. Investigate discounts, export timing, missing calls, retries,
unsupported charges, and mapping errors before drawing conclusions. This feature
does not allocate invoices to individual tasks, calculate answer quality, prove
realized savings, or change routing. Per-call `invoice_usd` stays unknown.
Historical billing snapshots are immutable; their operational comparison is
recalculated on refresh/export as captured usage and retention change. Exports
include calculation time, last received time, scope, and limitations.

## Access, retention, and upgrade

Billing reads and JSON exports require an authenticated team member. Imports,
previews, example loading, and mapping changes require an administrator and CSRF.
Every query is team scoped. Uploads are untrusted; UI values are escaped,
validation errors omit raw cells, and exports use JSON. Stored records contain
account IDs and billing metadata. Protect the deployment and backup storage
accordingly; do not commit customer billing files.

`WORKBENCH_EVIDENCE_RETENTION_DAYS` covers snapshot revisions and their comparison
mappings by import time, in batches of 20 per maintenance transaction. Expired
snapshot deletion is audited. Captured usage follows its separate usage policy.
Account bindings remain configuration until the source is removed; they do not
expire with financial records. Export needed reconciliation evidence before its
retention deadline.

**Schema 3 → 4 is additive**: four tables store families, immutable snapshots,
source account bindings, and comparison mappings. Existing payloads,
fingerprints, accounting facts, and collector health remain unchanged.

1. Stop the app, worker, and maintenance together.
2. Take and verify a restorable PostgreSQL backup. Preserve the previous images.
3. Build matching app/worker/maintenance images from this source.
4. Run `python -m workbench.pilot migrate` with the deployment's existing database
   settings (the same explicit migration entry point as earlier releases).
5. Start matching services and verify readiness, login, original usage totals,
   and the billing screen. Loading fictional records is an explicit choice.

Production startup checks schema 4 and does not migrate silently. For rollback,
stop all writers and restore the pre-upgrade backup with the previous images.
Do not manually decrement the schema marker or run old binaries against schema 4.
This feature changes neither company authentication requirements nor the
explicit password-only hosted-test exception.

## Components and reference sources

Workbench uses AxonLLM Ledger's pure `normalize_cost_row` aliases pinned to commit
`d773dafda758755100104123c58c3a658e5866e2`. It owns financial validation,
snapshot replacement, persistence, and reconciliation. Ledger's full ingestion,
user/model filtering, in-memory deduplication, and quantity conversion are not
used. AxonLLM and Ostiari's existing integration boundaries remain unchanged.

- [AWS CUR 2.0 table dictionary](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-cur2.html)
- [AWS line-item columns](https://docs.aws.amazon.com/cur/latest/userguide/Lineitem-columns.html)
- [AWS identity columns](https://docs.aws.amazon.com/cur/latest/userguide/identity-columns.html)
- [AWS product columns](https://docs.aws.amazon.com/cur/latest/userguide/product-columns.html)

Local validation uses authored CSV and synthetic usage. It does not establish
compatibility with every AWS export configuration or validate a customer's
invoice. Automated billing collection, subscription allocation, other provider
bills, and cost-based routing activation remain future work.
See the [dated implementation verification](VERIFICATION-BILLING.md).
