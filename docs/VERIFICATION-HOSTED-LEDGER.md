# Hosted Ledger verification — October 29, 2026 (UTC)

Both existing AWS acceptance workspaces were updated to merged source
`9ce307ef4ffcfccba0ae1b48e4408e982fb7cd46`. This brings native AxonLLM Ledger
billing totals, sample downloads, and coding evidence to the hosted applications.
The application remains on schema 4. Previously published v0.5.0 release
assets were preserved.

## Source and preserved data

All nine merged-commit GitHub checks passed. The exact deployment source archive
passed its secret scan, and the built image's runtime files matched that source.
API, worker, and maintenance services use the same new image in both workspaces.

| Workspace | Original recorded calls | Original tasks | Original API estimate |
|---|---:|---:|---:|
| Seeded demo | 144 | 72 | USD 0.088074750 |
| Clean | 0 | 0 | USD 0.000000000 |

Existing accounts, linked identities, sources, accounting facts, recordings,
evaluations, saved reviews, and billing rows were preserved. Private configuration
file hashes matched before and after replacement. The clean workspace retained
zero sources, usage, recordings, evaluations, reviews, and billing reports.

## Hosted feature acceptance

- Real Cognito sign-in and sign-out passed for both workspaces. Anonymous access,
  missing-CSRF rejection, workspace isolation, and clearing billing/coding
  content at sign-out passed.
- The demo's pre-existing fictional billing snapshot retains five charge rows,
  one declared comparison, and two isolated synthetic calls. Ledger's native
  aggregation and integrity checks calculate its report. Imported charges remain
  `0.0121475` USD, the comparable captured estimate remains `0.0001295` USD,
  and the selected-group difference remains `0.000018` USD. Credits and
  unassigned charges remain visible; per-call invoice costs remain unknown.
- Both sample ZIP downloads contained six files identical to the merged source.
  Exported billing evidence retained its exact amounts and fixture scope.
- The coding demonstration loaded saved results for three authored candidates
  across six cases. Acceptance tuning, result download, and file preview passed.
  These browser actions ran no patches or models and created no workspace records.
- All nine panels in both visible browser windows reached their footers with
  wheel and keyboard input. Task context, overview colors, evaluation guidance,
  and empty-state actions passed.

An initial rapid Home/End automation sequence timed out in Task explorer.
Waiting for 350 milliseconds of stable scroll position between opposing input
actions resolved the timeout, with all 18 panels passing. The reusable hosted
harness now includes Coding evaluations, the bounded settling check, and
`--show --close` for visible sign-out acceptance.

## Recovery and operations

After stopping writers, both databases were backed up to the existing encrypted
off-host storage. The stored backups were downloaded, checksummed, and restored
into temporary databases; every table matched its stopped original.
The application update required no schema migration or database replacement.

Fresh post-update backups also restored successfully. Preserved application
and billing rows matched, and recalculated Ledger exports were identical except
for the calculation timestamp. Temporary restore databases were removed.
Previous source, application images, and backup copies remain available for
rollback. This update's temporary S3 staging objects were removed.

All eight API, worker, maintenance, and database services were healthy. HTTPS,
readiness, protected metrics, disabled local login, and authorization-code SSO
with PKCE passed. Backup and monitoring timers were active, and all four existing
readiness/backup alarms were OK.

## Scope and limits

The existing password-only hosted-test exception and credentials were preserved;
this is not production MFA acceptance. The fictional billing snapshot is not an
authenticated customer invoice, and the coding model estimates remain authored
teaching values. No live billing collector, AWS Budgets feed, customer export, or
paid model call was added. Ledger's CUR-versus-Budgets comparator remains explicitly
not connected.

This single-host acceptance does not establish high availability or customer
workload capacity. Private endpoints, account identifiers, credentials, backups,
screenshots, and operational receipts remain outside Git.

See the [hosted test guide](HOSTED-TEST.md),
[Ledger implementation checks](VERIFICATION-LEDGER-INTEGRATION.md), and
[previous hosted billing migration](VERIFICATION-HOSTED-BILLING.md).
