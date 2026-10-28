# Scheduled billing collection from S3

The operator runs one collector per account/month/currency on the application
host. It downloads a complete versioned Legacy CUR assembly, validates every part,
and imports a replacement snapshot using the same accounting path as manual CSV.
It does not create AWS exports or invoke models.

Supported: Legacy CUR **CSV or gzip CSV**, configured to **create new report
versions**, with the current monthly manifest and matching assembly manifest.
The existing limits apply: 20 parts, 8 MB compressed total, 8 MB decoded CSV,
20,000 rows, one Bedrock usage account/month/currency. Other AWS service rows
are excluded by the existing importer. Mixed Bedrock accounts reject atomically.
CUR 2.0 manifests, overwrite delivery, ZIP, Parquet, and large organization-wide
exports need separate validated adapters and are rejected. Manual projected
CUR 2.0 CSV import remains supported.

AWS describes the current monthly pointer and immutable assembly manifests in
[report versions](https://docs.aws.amazon.com/cur/latest/userguide/understanding-report-versions.html).
Workbench follows only the manifest's complete part list. It checks the assembly
copy, expected bucket owner, object ETags, byte bounds, and the unchanged current
manifest before importing. A conflicting database revision rejects stale work.
Exact replay leaves the snapshot unchanged; refreshed contents preserve revisions.
Collection does not create model/source mappings.

## Configure on the customer host

Install the optional AWS SDK:

```sh
uv sync --locked --extra bedrock
```

Create `.pilot/billing-collector.json` privately:

```json
{
  "name": "Monthly Bedrock billing",
  "team_id": "00000000-0000-0000-0000-000000000000",
  "bucket": "company-billing-example",
  "bucket_owner": "123456789012",
  "manifest_key": "exports/report/20261001-20261101/report-Manifest.json",
  "account_id": "123456789012",
  "month": "2026-10",
  "currency": "USD",
  "region": "us-east-1",
  "interval_seconds": 3600
}
```

Replace placeholders with the actual team and report scope. `bucket_owner` is
the bucket-owning account; `account_id` is the usage account. Obtain the team UUID
from the authenticated `/api/auth/session` response. Use the same private database
configuration as the application. Schema 4 is required; the collector never
migrates or initializes a workspace. Production configuration checks remain active.
The optional `profile` selects an AWS SDK profile for local operation; on a host
prefer its workload role and the SDK credential chain.

Grant `s3:GetObject` only for this report's monthly manifest and assembly prefix.
If required by the customer's bucket encryption, grant `kms:Decrypt` for that
key with the appropriate S3 encryption-context/service restrictions. No bucket
listing or write permissions are needed. Keep credentials out of configuration
and Git. S3 requests have normal AWS request charges; no new model calls occur.

```sh
uv run --locked python -m workbench.billing_collection \
  --config .pilot/billing-collector.json --dry-run
uv run --locked python -m workbench.billing_collection \
  --config .pilot/billing-collector.json --watch
```

First run the preview and inspect the scope, then run the watcher under your
existing service manager with restart-on-failure. `SIGTERM` stops the watcher.
The interval is 5 minutes–24 hours; default one hour. Each configuration targets
one explicit month. Keep collectors for months that AWS may still revise, and
add a reviewed configuration when a new month starts. This is a single-host
collector, not a distributed scheduling service.

Collection health appears in **Billing reconciliation** and failures/staleness
also appear in **Operations** and private Prometheus metrics. A failed attempt
preserves the last accepted snapshot and last-success time. A stopped watcher
becomes stale after two intervals. Restart retries the current complete assembly.
Private snapshot exports include S3 keys, ETags, optional version IDs, compressed
part hashes, and manifest hash. They are provenance, not invoice signatures.

No real AWS export was available during implementation. S3 protocol, changing
assemblies, decompression limits, replay, refresh, concurrent writes, and failure
recovery are checked with authored objects and SDK stubs. Customer-host scheduling
and real-data acceptance still require the customer's export and access.
