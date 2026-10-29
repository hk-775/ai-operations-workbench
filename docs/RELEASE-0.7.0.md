# Workbench 0.7.0 — repeated coding comparisons and AWS acceptance tools

This release turns the larger coding packet into an executable comparison and
adds account-owned billing export and independent-host recovery procedures.

- Version 2 recordings embed frozen datasets and complete balanced schedules.
  Repeated collection checks the budget and broken/reference baselines before
  paid calls; unknown attribution stops the run and preserves incomplete coverage.
- **Coding evaluations → Load recorded calibration** shows an actual 18-task,
  three-model, three-repetition comparison. The full 165-call recording and
  independently replayed result are included. The six-task fixture remains compatible.
- Optional CloudFormation creates a private versioned Legacy CUR CSV/gzip export
  that matches the existing collector's supported format.
- A disposable SSM-only recovery host restores scheduled backups onto independent
  disks, verifies every application table, and checks readiness/authentication.
  Its role cannot overwrite source backups or publish source monitoring metrics.

See the [recorded methodology and results](CODING-CALIBRATION-2026-10-29.md),
[coding guide](CODING-EVALS.md), [AWS procedures](ACCEPTANCE-OPERATIONS.md), and
[dated verification](VERIFICATION-0.7.0.md).

The published cases are calibration data, not a representative private holdout.
Real billing delivery/acceptance and actual human alert acknowledgment remain
distinct from infrastructure provisioning. No native subscription-tool capture,
automatic production routing, DNS failover, or high-availability claim is added.

## Download and verify

Download `ai-operations-workbench-0.7.0.tar.gz` and `SHA256SUMS` from
[GitHub Release v0.7.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.7.0).

```sh
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.7.0.tar.gz
cd ai-operations-workbench-0.7.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

Docker Compose is required for isolated seeded/clean installations; credentials
are generated privately. The [local quickstart](../README.md#run-it) remains
available without company identity or model keys. Load the recorded coding
calibration in an authenticated workspace without making new model calls.

## Upgrade and distribution

Schema remains **4**. Installations on v0.5.0 or v0.6.0 need no new schema
migration. Earlier releases require the explicit
[schema-4 procedure](RELEASE-0.5.0.md#upgrade-and-rollback).
Preserve private configuration, verify a backup, rebuild/restart the application,
and verify identity, usage, jobs, billing and coding previews.

The AWS export and recovery stacks are opt-in; upgrading the application does
not create them or start billing collection. The original hosted-test password-only
exception remains explicit. Normal production still requires verified MFA.

The public player retains the existing video, narration, palette, moving circles,
pause and reduced-motion behavior. Its video describes the support workflow.
The additional AWS topology is an editable/static companion documenting optional
acceptance services.

The MIT-0 source archive includes authored calibration cases and recorded model
outputs, but no customer data, billing exports, credentials or deployment identities.
Earlier release assets are preserved. `SHA256SUMS` verifies bytes; no publisher
signature, package registry or container registry is introduced.
