# Workbench 0.5.0 — Bedrock billing reconciliation

Compare complete monthly Bedrock billing exports with captured application
estimates, while keeping incomplete comparisons, credits, and unassigned charges
visible. This release adds billing evidence to the existing usage, evaluation,
and routing-review workspace.

- Import Legacy CUR or CUR 2.0 CSV snapshots with exact Decimal amounts,
  explicit account/month/currency scope, preview, and atomic validation.
- Keep immutable revisions, reject stale previews, and deduplicate exact replays
  without appending the same monthly charges twice.
- Declare which charge groups match an application source, exact model, region,
  service tier, and performance mode. Prevent overlapping comparisons from
  reusing captured estimates.
- Inspect known differences, incomplete capture, unsupported prices, fees,
  credits, and unassigned spend. Missing evidence remains unknown.
- Download reconciliation JSON with normalized records, hashes, declared scope,
  calculation time, and limitations. Imports and mapping changes require an
  administrator; team members can inspect and export.
- Load an explicitly fictional five-row bill and two synthetic calls without
  invoking a model. The example stays separate from normal usage totals.
- Recover the billing view when retention removes a selected snapshot, clearing
  stale totals and export actions when no reports remain.

AxonLLM Ledger supplies pinned, pure schema normalization. Workbench owns financial
validation, snapshot storage, and declared comparisons. Imported records are not
independently authenticated invoices, and aggregate links do not allocate invoice
costs to individual tasks. A difference does not establish realized savings.

The existing Bedrock connector, AxonLLM integration, Ostiari draft-action checks,
saved support evaluation, narrated demo, audio/captions, and animated architecture
remain included. The public walkthrough uses bundled media and makes no
application API, identity-provider, or model requests.

The video shows the existing support workflow; it is not a recording of the new
billing screen. Explore billing in an authenticated local or company-owned
installation using the [billing guide](BILLING.md).

## Download and verify

From [GitHub Release v0.5.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.5.0),
download `ai-operations-workbench-0.5.0.tar.gz` and `SHA256SUMS` together:

```sh
# macOS
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.5.0.tar.gz
cd ai-operations-workbench-0.5.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

Docker Compose is required for the isolated seeded and clean installations.
Each generates its own private credentials. In the seeded workspace, choose
**Billing reconciliation → Load fictional billing example**; `seed-demo` alone
does not import a bill. Leave the clean workspace empty for onboarding tests.
For the recorded demo without Docker, follow the [quickstart](../README.md#run-it).
To capture Bedrock application usage, install the optional SDK with
`uv sync --locked --extra bedrock` and follow [Bedrock setup](BEDROCK.md).

The checksum verifies the attached archive, not GitHub's generated source ZIP
or tarball. It provides integrity checking, not a publisher signature.
Source, tests, locked dependencies, deployment recipes, documentation, media,
and editable/static architecture assets are included. Installation downloads
dependencies; this is not an offline dependency bundle. Company configuration,
credentials, outboxes, databases, and private recordings are excluded.

## Upgrade and rollback

**Version 0.5.0 requires schema 4. Version 0.4.0 uses schema 3.**
The additive migration creates four billing tables while preserving original
events, fingerprints, accounting facts, collector health, evaluations, and reviews.
Production startup checks the schema; it does not migrate silently.

Preserve each deployment's configuration, secrets, volumes, and previous images.
Stop the API, worker, and maintenance together, take a private PostgreSQL backup,
and verify that it restores before migrating. For the standard production profile,
choose an unused backup filename:

```sh
docker compose --env-file .pilot/production.env -f compose.production.yaml stop app worker maintenance
umask 077
mkdir -p .pilot/backups
docker compose --env-file .pilot/production.env -f compose.production.yaml exec -T db \
  pg_dump -U workbench -d workbench -Fc > .pilot/backups/pre-v0.5.0.dump
```

Copy and verify the backup according to the company's encrypted recovery policy.
Then build matching services and run the explicit migration with the existing
deployment settings:

```sh
docker compose --env-file .pilot/production.env -f compose.production.yaml build
docker compose --env-file .pilot/production.env -f compose.production.yaml run --rm app \
  python -m workbench.pilot migrate
docker compose --env-file .pilot/production.env -f compose.production.yaml up --wait
```

Use the corresponding environment and Compose files for each pilot, seeded,
clean, or hosted-test installation. Verify readiness, login, original usage
totals, saved evidence, source delivery, and billing after restart.
Retain the pre-upgrade backup and previous images. To roll back, stop all writers,
restore that backup, and start the matching previous services. Do not run v0.4.0
against schema 4 or manually decrement the schema marker.

See [billing scope and retention](BILLING.md),
[production recovery](PRODUCTION.md#backup-restore-and-upgrade),
[release verification](VERIFICATION-0.5.0.md), and the
[completed hosted upgrade](VERIFICATION-HOSTED-BILLING.md).

This release preserves company production MFA requirements and the explicitly
selected password-only AWS test exception. It adds no automated billing download,
subscription allocation, native coding-tool connector, arbitrary workload
evaluation, high-availability guarantee, or automatic routing activation.
