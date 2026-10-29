# Workbench 0.9.0 — inspectable evidence and reliable ingestion

This release packages the eight fixes from the code and feature review.
Evaluation failures can now be inspected case by case, task costs can be ranked
by one explicit basis, and a routing review can be downloaded with its complete
saved evidence for offline verification.

- **Connector recovery:** validate the source kind before binding an outbox;
  safely repair a legacy wrong-kind binding while preserving queued evidence.
- **Stable call pages:** ingestion-fenced cursors exclude new, backdated and tied
  arrivals until refresh.
- **Malformed output:** reject invalid JSON, overflow and excessive nesting as
  failed attempts; retain their cost and continue evaluating other candidates.
- **Fixture gates:** authored answers cannot justify measured recommendations
  or projected savings.
- **Separate cost ranking:** API estimates, tool-reported model amounts and
  Cursor-reported charges remain distinct; unknown amounts sort after known ones.
- **Case inspection:** model/outcome filters, failed checks, expected/actual
  decisions, requests and saved answers; bounded coding-patch pages.
- **Portable evidence:** authenticated complete routing-evidence bundles with
  checksums and recording/evaluator identity, plus offline verification.
- **Accurate capabilities:** current connector documentation is separated from
  historical, checksummed reports.

The existing Codex, Claude Code and Cursor connectors remain included.
Creating a source does not connect a vendor account. Real customer input and
authenticated vendor access are separate from the authored tests.

## Download and verify

Download `ai-operations-workbench-0.9.0.tar.gz` and `SHA256SUMS` from
[GitHub Release v0.9.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.9.0).

```sh
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.9.0.tar.gz
cd ai-operations-workbench-0.9.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

Docker Compose creates separate seeded and clean installations. Each operator
supplies their own identity, domain and secrets. Follow
[production installation](PRODUCTION.md) for a company-owned deployment.

## Upgrade and rollback

**Schema 5 is required.** Stop API, worker and maintenance writers and pause
collectors. Back up the database and complete private outboxes. Run the explicit
migration using the new release's locked dependencies and private configuration.
Start matching application, worker and maintenance versions and verify health.
See the [detailed migration and connector repair procedure](REVIEW-FIXES.md).

Migration adds source/event ingestion sequences. Existing events start at zero;
original payloads, fingerprints, accounting and pricebooks remain unchanged.
Repeating migration is safe. Older services reject schema 5. Rollback requires
the matching prior image/source and pre-upgrade database, with writers stopped;
never lower the schema marker manually.

**API compatibility:** `/api/pilot/calls` no longer accepts nonzero `offset`.
Use each task's `calls_cursor`, then the response's `next_cursor`, with the same
source, task and filters. Discard cursors when filters change. Retention can
still remove expired calls.

Evidence bundles contain saved requests and answers. Share them only with
authorized reviewers. Check the original download without reserializing it:

```sh
uv run --locked python -m workbench.proposals verify routing-evidence.json
```

Checksums establish saved integrity and identity links, not provider
authenticity or current model quality.

The MIT-0 archive includes existing public examples, recorded calibration,
architecture sources and narrated media. It excludes private account inputs,
credentials and deployment receipts. Production authentication requirements
remain in place, including the explicit password-only hosted-test exception.
The release does not activate routing or start model calls. Previous release
assets are preserved. `SHA256SUMS` is a byte-integrity check, not a publisher
signature; no package or container registry is used.
