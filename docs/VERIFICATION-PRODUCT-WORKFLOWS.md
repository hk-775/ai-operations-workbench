# Unreleased product-workflow verification

Local verification of the schema-6 source changes on October 29, 2026.
These results do not describe a published release or hosted deployment.
See the [workflow and upgrade guide](PRODUCT-WORKFLOWS.md).

| Check | Result |
| --- | --- |
| Backend suite, Python 3.13 with SQLite and PostgreSQL 16.13 | 301 passed, 7 skipped |
| Authenticated browser regression suite | 22 passed |
| Final new-workflow form/preview checks | 4 passed |
| Actual browser window, `viewport: null` | All 11 navigation views reached their footer; wheel scrolling passed |
| New result/setup headings | Visible below the sticky header |
| Schema 5 → 6 migration | Repeatable; original usage events and accounting facts preserved |
| Independent PostgreSQL backup and restore | Two suite revisions, a custom run, a budget and a cost pool restored with matching evidence |
| Documentation and source-packaging contracts | Passed |
| Tracked-source Gitleaks scan | No leaks found |
| JavaScript syntax and whitespace checks | Passed |

Six skipped backend variants exercise PostgreSQL-specific behavior and are
intentionally skipped on SQLite; their PostgreSQL variants ran. The remaining
skip is the existing opt-in Docker coding sandbox execution test. The new
saved-answer checks do not execute uploaded code or alter that sandbox runner.
Existing HTTP client deprecation warnings remain.

The tests cover exact financial allocation and rounding, revision replay,
stale-edit conflicts, concurrent pool creation, fixture isolation, source/team
scope, permissions and CSRF. Budget checks retain unknown amounts, distinguish
each tool-reported basis, and suppress projections for incomplete pricing,
attempt costs, retention or known collector gaps.

Custom evaluation checks cover duplicate/non-finite JSON rejection, decimal/type
equality, critical failures, absent model/case answers, failed-attempt costs,
immutable suite revisions, idempotent runs, comparisons and restart persistence.
Retention protects current active definitions and revisions referenced by
retained runs, then expires obsolete evidence in bounded batches.

Browser journeys create, preview, correct and void a shared expense; inspect a
budget warning; create and evaluate a suite; compare a critical regression;
download evidence; inspect setup without exposing tokens; and verify viewer
restrictions, safe rendering, sign-out clearing and mobile scrolling.
The local token helper refuses overwrites, symlinks/public receiver files and
fallback input that could echo a token.

All added test data is authored or uses existing bundled fixtures. No new model
calls, real vendor-account capture, external alert delivery, routing activation
or hosted upgrade was performed. Real Claude Code/Cursor acceptance, customer
workload quality and customer billing coverage remain separate validation work.
