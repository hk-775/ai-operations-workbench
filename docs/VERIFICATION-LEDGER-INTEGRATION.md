# AxonLLM Ledger integration verification

Verified on 2026-10-28 against the existing pinned Ledger revision
`d773dafda758755100104123c58c3a658e5866e2`. These source changes expand the
normalization-only integration in v0.5.0. The AWS apps had not been updated at
the time of these implementation checks. The subsequent
[October 29 hosted acceptance](VERIFICATION-HOSTED-LEDGER.md) records their
deployment and verification.

## Implemented boundary

- Ledger's real `AggregationEngine` calculates billed account/group totals,
  linked and unassigned partitions, and positive/negative amounts.
- Ledger's real `DataIntegrityService` checks account and unattributed totals.
  The adapter also checks those amounts against the accepted source rows.
- Workbench retains the complete source snapshot, persisted revisions, declared
  source mappings, and comparison with captured-call estimates.
- Private cost projections retain empty user/model identities, anchor costs
  to the billing period, and exclude placeholder usage counters from every
  application event and export. Original dates and billing units are preserved.
- Ledger's CUR-versus-Budgets comparator is not invoked without a corresponding
  Budgets feed. Exports explicitly declare that integration as not connected.

## Checks

- Focused accounting, acceptance, collection and publication suite:
  **91 passed, 2 skipped**, with SQLite and PostgreSQL coverage. The two skipped
  cases are PostgreSQL-specific concurrency tests' SQLite variants; their
  PostgreSQL variants passed.
- Regression cases include missing identities, missing/prior-month usage
  timestamps, fees and credits, fractional non-token units, foreign currency,
  18-decimal-place amounts, a low-precision caller context, and failure before
  an import can replace the last accepted snapshot.
- Runtime observation verifies that preview, import, report, listing and export
  invoke the actual pinned Ledger aggregation implementation.
- Both authenticated billing browser journeys passed, including declared
  mappings, immutable refresh, export, mobile layout, retention and viewer access.
- A browser using its actual window viewport passed wheel/keyboard scrolling
  across all nine panels. The updated Ledger card was separately inspected in
  that viewport.
- The fictional billing bundle was rebuilt and verified with the same expected
  charges, adjustments and captured-estimate difference.

No paid model calls, AWS writes, schema changes, upstream repository edits, or
dependency changes were required. Real customer billing acceptance remains
dependent on representative private exports and matching captured usage.
