# Workbench 0.4.0 — Bedrock usage capture and collector health

Connect instrumented Amazon Bedrock application calls to task costs, then see
whether collectors are delivering their records. This release adds boto3
Converse and ConverseStream capture to the existing AxonLLM connector and
self-hosted workspace.

- Capture token categories, request IDs, SDK retry coverage, client duration,
  and provider latency when reported. Prompts and responses stay in the application.
- Reserve metadata before invocation and deliver through a durable outbox.
  Interrupted streams, crashes, retries and missing usage remain visible gaps.
- Inspect source-scoped collector heartbeats, delivery backlogs and stopped
  collectors in Usage sources, Operations and private metrics.
- Estimate captured calls using an exact reviewed model, region, service tier,
  performance mode and date. Unsupported rates, invoices, and hardware/electricity
  remain unknown or unmeasured.
- Try an explicitly labeled two-call fixture without invoking a model.
- Upgrade explicitly to schema 3 while preserving existing event fingerprints,
  stored accounting, evaluations and reviews.
- Build the proxy with a verified JOSE security backport, regression checks and
  an actual-binary self-test. CI binds the scoped VEX evidence to the image and
  SBOM being scanned; see the [backport provenance](../deploy/images/proxy/patches/README.md).

The reviewed Bedrock price snapshot covers uncached direct Nova Micro in
us-east-1, default tier and standard performance only. It does not ingest AWS
invoices or price every model, cache mode or inference profile. A healthy
collector proves delivery liveness, not complete application instrumentation.
Usage metadata alone does not establish answer quality or qualify arbitrary
tasks for the support-v1 evaluator.

The existing narrated video, audio, captions, chapters, interactive architecture,
small moving circles, pause/reduced-motion controls, and editable diagrams are
included. The [public walkthrough](https://hk-775.github.io/ai-operations-workbench/)
uses bundled media and connects to no application API or model service.
The saved support comparison remains 24 fictional cases, three models and
144 calls; the default review still returns **No model qualifies**.

See the [Bedrock setup guide](BEDROCK.md), [company installation](PRODUCTION.md),
and [dated release verification](VERIFICATION-0.4.0.md).

## Download and verify

From [GitHub Release v0.4.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.4.0),
download `ai-operations-workbench-0.4.0.tar.gz` and `SHA256SUMS` into the same directory:

```sh
# macOS
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.4.0.tar.gz
cd ai-operations-workbench-0.4.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

This starts separate seeded and clean local Docker deployments; Docker Compose
is required. Each creates its own private credentials. For the no-key recorded
demo without Docker, follow the [README quickstart](../README.md#run-it).
To instrument a Bedrock application, install the optional SDK with
`uv sync --locked --extra bedrock` and follow the connector guide.

The checksum covers the attached source archive, not GitHub's generated source
ZIP/tarball. It verifies integrity; no publisher signature is claimed.
The archive includes locked dependencies, source, tests, deployment recipes,
documentation, video/audio, captions, and architecture assets. Installation
downloads dependencies; this is not an offline dependency bundle.
Company configuration, credentials, outboxes, databases and private recordings
are excluded. Prior release assets remain unchanged.

## Upgrade and rollback

**Version 0.4.0 requires database schema 3. Version 0.3.0 uses schema 2.**
Preserve the company's existing private configuration, secrets and volumes.
Stop the API, worker and maintenance services and take a pre-upgrade database
backup. For the standard production Compose profile, choose an unused backup
filename and run:

```sh
docker compose --env-file .pilot/production.env -f compose.production.yaml stop app worker maintenance
umask 077
mkdir -p .pilot/backups
docker compose --env-file .pilot/production.env -f compose.production.yaml exec -T db \
  pg_dump -U workbench -d workbench -Fc > .pilot/backups/pre-v0.4.0.dump
```

Copy the backup to the company's encrypted backup destination and verify a restore
before migration, as described in
[backup, restore and upgrade](PRODUCTION.md#backup-restore-and-upgrade).
Then build matching v0.4.0 services and run the explicit migration with the
deployment's existing environment:

```sh
docker compose --env-file .pilot/production.env -f compose.production.yaml build
docker compose --env-file .pilot/production.env -f compose.production.yaml run --rm app \
  python -m workbench.pilot migrate
docker compose --env-file .pilot/production.env -f compose.production.yaml up --wait
```

Use the corresponding environment/Compose file for each seeded, clean or pilot
installation. Never reuse another deployment's database environment.

The migration is transactional and idempotent. Existing events are not repriced.
After restarting, verify readiness, sign-in, usage totals, source delivery and
saved reviews. Keep the old application/proxy images and the pre-upgrade dump.
To roll back, restore that dump into a separate database and start the matching
previous application and services before switching traffic. Do not point v0.3.0
at schema 3 or manually decrement the schema marker.

The AWS hosted tests retain their explicit password-only Cognito test profile.
The standard company production profile still requires its configured MFA claim.
This release does not add subscription-tool connectors, invoice reconciliation,
arbitrary workload evaluators, high availability or automatic routing changes.
