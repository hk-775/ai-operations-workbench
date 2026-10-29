# Review fixes in v0.9.0

These changes address the eight findings in the October 29, 2026 code and feature
review and are included in v0.9.0. See the [release instructions](RELEASE-0.9.0.md)
for the downloadable archive. Installation-specific acceptance records are
private and are not included in the source distribution.

## Upgrade: schema 5

Stop API, worker and maintenance services and pause collectors. Back up the
database and private connector outboxes using the existing deployment runbook.
Run the explicit `uv run --locked python -m workbench.pilot migrate`
command with the target deployment's private database configuration and this
checkout's locked dependencies (or the equivalent migration container).
Restart matching API, worker and maintenance versions, check health, then resume
collectors. Preserve the backup until acceptance is complete.

The migration adds `ingest_sequence` to sources and events. Existing events start
at zero; new ingestion batches advance the source's counter under its existing
transaction lock. Payloads, fingerprints, captured accounting and historical
pricebooks are preserved. Repeating migration is safe. Production refuses to
start against schema 4 with this checkout.

Rollback requires stopping services and restoring the pre-upgrade database
alongside the matching prior images. Old services intentionally reject schema 5.
Do not manually downgrade the version marker.

## Stable call pages and explicit cost ranking

`GET /api/pilot/usage` accepts `cost_basis`:

| Basis | Meaning |
| --- | --- |
| `api_estimate_usd` | Captured API estimate; default |
| `reported_model_estimate_usd` | Model amount reported by a coding tool |
| `reported_charge_usd` | Cursor-reported usage amount |

Tasks sort by the selected basis, descending, with unknown amounts last.
An explicit zero remains a known zero. Partial amounts remain subtotals. Bases
are never added together or presented as reconciled invoices. Task explorer
shows the selected amount and coverage on each card.

Each task with more than 100 calls includes `calls_cursor`. Pass it to
`GET /api/pilot/calls` with the same source, task and filters. Continue with
`next_cursor` until it is null. Nonzero `offset` now returns 422; update callers
that used offsets. Treat cursors as opaque and discard them when filters change.

The cursor fences ingestion as well as timestamp/event ordering. Concurrent,
backdated and same-timestamp arrivals appear after refresh, without repeating
previously loaded calls. This is not permanent snapshot storage: retention can
remove expired calls while browsing. Task-list pages themselves remain ranked
pages; refresh to see their current ordering.

## Connector recovery

New outboxes verify the connector kind before binding to an authenticated source.
Using an AxonLLM token for a Bedrock outbox, for example, leaves pending evidence
available for retry with the correct token.

For an existing v0.8.0 outbox stranded by a wrong-kind source binding, stop capture
and delivery and back up the complete outbox using SQLite's backup facility or
the deployment runbook. Retain any in-flight reservation directory. Configure
the same `WORKBENCH_INGEST_URL` and the **original wrong-kind source token** via
`WORKBENCH_INGEST_TOKEN_FILE`, then run:

```sh
uv run --locked python -m workbench.connector --outbox /private/path/usage.outbox.db repair-source-binding
```

Repair authenticates the original source and detaches only a binding whose kind
could not have accepted the outbox's events and that has no acknowledged rows.
Then configure the correct token and resume delivery. Event IDs, payloads and
fingerprints remain unchanged.

Repair refuses same-kind source changes, uncertain successful delivery,
acknowledged rows, mixed-schema outboxes, and unverified original tokens. Preserve
such outboxes for operator review. Do not delete bindings manually or copy
pending records into another source, which could double-count usage.

## Evaluation and routing evidence

Malformed container output, including NaN, infinity, overflow, duplicate JSON
keys and excessive nesting, produces a failed attempt. Remaining candidates
continue and the failed attempt's cost stays in the denominator.
Saved support answers also reject numeric overflow and excessive nesting as
failed decision checks while preserving the original answer and captured cost.

Fixture-only support evaluations cannot select a measured winner or project
savings in either the local demo or authenticated workspace, even when every
authored answer passes. Recorded evidence still must satisfy coverage, cost,
pass-rate, critical-case and latency requirements.

Model evaluations now opens individual failed/critical cases with supplied
facts, expected and actual decisions, checks, requests and saved answers.
The coding inspector offers candidate/outcome filters and twelve patches per page.

Routing review retains its summary export and adds **Download evidence bundle**.
The authenticated, team-scoped endpoint
`GET /api/pilot/proposals/{id}/export` includes the original recording, saved
analysis and proposal, with integrity checksums and evaluator identity.
Download the original response bytes; reserializing JSON can change the original
recording's content identity. Check a downloaded bundle offline:

```sh
uv run --locked python -m workbench.proposals verify routing-evidence.json
```

Verification makes no model calls. It checks saved integrity and identity links;
it does not authenticate the provider, rerun an older evaluator, or certify
model quality. The bundle contains saved requests and answers: share only with
authorized reviewers. Retention can make a bundle unavailable after evidence
expires. Previously generated, checksummed coding reports remain historical;
current connector capabilities are described in the README and connector guide.

## Local verification · October 29, 2026

- Backend: 242 passed, six skipped. PostgreSQL-only checks ran against an isolated
  PostgreSQL instance and skip their SQLite variants. The optional Docker check
  was run separately and passed.
- Browser: 18 authenticated-workspace checks and 13 demo/architecture checks
  passed, including concurrent call arrivals, cost-basis selection, failed-case
  inspection, evidence downloads, mobile layout and sign-out clearing.
- Real Docker execution rejected NaN, infinity, overflow and excessive nesting.
  A complete result remained exportable after a malformed candidate, with its
  cost retained and the next candidate evaluated.
- Visible Chromium used the actual window viewport (1200 × 759 CSS pixels).
  All nine panels reached their footer with wheel and keyboard scrolling;
  no JavaScript errors or external requests occurred.
- Downloaded routing evidence passed offline integrity verification. Changed
  source files passed secret scanning. Historical checksummed data was unchanged.

These local checks made no paid model calls. They do not establish live
vendor-account acceptance or a customer's deployment outcome.
