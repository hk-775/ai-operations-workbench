# Workbench 0.8.0 — coding-tool usage connectors

This release adds three core metadata connectors to the authenticated workspace:

- **Codex:** documented `codex exec --json` turns, native token categories,
  and explicit unknown monetary cost and duration.
- **Claude Code:** an authenticated loopback OTLP HTTP/JSON receiver and file
  import for API usage, duration and tool-reported model estimates.
- **Cursor:** bounded team Admin API reads or complete JSON reporting windows,
  preserving separate model amounts and vendor-reported charges.

Each connector uses a private durable outbox, stable opaque identities, source
tokens, retryable delivery and collector heartbeats. Prompt/response content,
code, tool arguments, user email addresses and vendor keys are discarded before
persistence. Cursor reporting is delayed; overlapping or changed windows require
review instead of appending duplicate charges.

Usage overview and Task explorer show native records with separate cost bases.
Operations counts these records separately from API calls so unknown subscription
allocation does not trigger a failed-pricing alert. Tool metadata does not
establish code quality, complete attempt capture, an invoice or allocated
subscription cost.

See [setup and authored examples](CODING-TOOL-CONNECTORS.md) and
[verification boundaries](VERIFICATION-0.8.0.md). Creating a source does not connect
a vendor account. Cursor needs administrator API access; native capture must be
configured on the collector host. Broader desktop/individual-account capture and
automatic subscription allocation remain outside this contract.

## Download and verify

Download `ai-operations-workbench-0.8.0.tar.gz` and `SHA256SUMS` from
[GitHub Release v0.8.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.8.0).

```sh
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.8.0.tar.gz
cd ai-operations-workbench-0.8.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

Docker Compose starts isolated seeded and clean installations. Each installer
supplies their own company identity, domain and secrets. For an offline example
without vendor access, follow the [connector guide](CODING-TOOL-CONNECTORS.md#try-authored-examples-without-vendor-access).

## Upgrade and rollback

Schema remains **4**. Versions 0.5.0–0.7.0 need no new schema migration.
Earlier installations require the [schema-4 procedure](RELEASE-0.5.0.md#upgrade-and-rollback).
Preserve private configuration and existing outboxes, verify a backup, rebuild
the application, then check authentication, usage, evaluation jobs, billing and
collector health. Retain the previous image and source for rollback.

Pause new coding-tool collection before rolling back to an older server.
Older versions reject the new source kinds and cannot interpret all native records;
they may display misleading native token or cost details. A rollback must preserve
queued data and must not replay old native inputs through a newly created outbox.
Restoring a prior database snapshot is an explicit data-recovery operation,
not an automatic downgrade step.

The standard production profile still requires verified MFA. The existing
password-only hosted test remains an explicit opt-in. This release changes no AWS
topology and does not configure vendor credentials, create billable resources,
start model calls or activate routing.

The MIT-0 source archive contains public code, authored examples, the existing
recorded calibration, and the original narrated support demo and architecture.
It excludes customer exports, private receipts, credentials and deployment identities.
The public player retains narration, moving circles, pause and reduced-motion
behavior. Previous release assets remain unchanged. `SHA256SUMS` verifies bytes;
no publisher signature, package registry or container registry is introduced.
