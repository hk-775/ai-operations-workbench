# Workbench 0.6.0 — Ledger, coding evidence and reference acceptance

This release brings the latest billing and coding features into the downloadable
product and adds repeatable preparation and operational acceptance tools.

- Actual pinned AxonLLM Ledger cost aggregation and integrity checks through a
  lossless billing adapter, retaining credits, unassigned charges and unknown
  per-call invoice costs.
- Downloadable fictional Bedrock billing sample, independent acceptance checks,
  and an opt-in scheduler for complete versioned Legacy CUR CSV/gzip deliveries.
- Six-task coding demonstration with isolated patch execution, saved attempts,
  exact API accounting and read-only previews; optional bounded model recording.
- Private billing handoff kit and an 18-task coding calibration packet with a
  reproducible 162-run comparison schedule, with no model calls required.
- Concurrent HTTP/replay checks, paced soak testing, abandoned worker lease
  recovery and restoration into a separate PostgreSQL container.

See [preparation](PREPARATION.md), [reference drill](REFERENCE-ACCEPTANCE.md),
[coding evaluations](CODING-EVALS.md), [billing collection](BILLING-COLLECTION.md)
and [dated verification](VERIFICATION-0.6.0.md).

Real customer billing/S3 delivery, funded live model comparisons and customer
production acceptance remain pending. The 18-task packet is calibration
preparation; the live recorder and UI retain their six-task contract. The
reference restoration uses a separate stack on the same Docker host.
No new native Codex/Cursor/Claude Code connector or routing activation is claimed.

## Download and verify

Download `ai-operations-workbench-0.6.0.tar.gz` and `SHA256SUMS` from
[GitHub Release v0.6.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.6.0).

```sh
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.6.0.tar.gz
cd ai-operations-workbench-0.6.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

Docker Compose is required for the isolated seeded/clean deployments. Credentials
are generated privately per installation. For the no-key recording demo without
Docker, follow [the quickstart](../README.md#run-it).

## Upgrade and distribution

Schema remains **4**. Installations already on v0.5.0/schema 4 need no new schema
migration. Earlier releases must follow the explicit
[schema-4 backup/migration procedure](RELEASE-0.5.0.md#upgrade-and-rollback).
Preserve private configuration, take a verified backup, rebuild application
images, restart services and verify identity, ingestion, jobs and billing.
Scheduled S3 collection is opt-in and is not started automatically by upgrading.

The public player, audio/captions, video and interactive architecture remain
included with their existing palette, animated solid circles and reduced-motion
controls. The video describes the recorded support workflow; it does not show
the new operator tools. AWS architecture files remain the existing single-host
test topology. This release creates no AWS resources or hosted deployment.

The MIT-0 source archive is company-neutral and contains no customer identity,
credentials, billing exports or runtime database. Previous release assets are
preserved. SHA256SUMS checks downloaded bytes, not a cryptographic publisher
signature. No package or container registry is introduced.
