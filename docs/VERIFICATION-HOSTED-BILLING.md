# Hosted billing verification — October 28, 2026

The existing seeded and clean AWS acceptance workspaces were upgraded to
**0.5.0 / schema 4** from merged commit `abcdb60301b91fac70f68bd3ebf3d23cf90762c2`.
This records a hosted source deployment. The published v0.4.0 archive remains
unchanged; a v0.5.0 release has not been published.

## Migration and preserved evidence

The deployment archive was built from the exact merged source and passed its
secret scan. Runtime files in the built image matched that source.

After stopping application writers, both databases were backed up to the existing
encrypted off-host storage. The actual stored backups were downloaded, checksummed,
and restored into separate candidate databases. Schema 4 was applied to those
copies. Every existing table's rows matched the stopped database, except for the
schema marker; the four new billing tables were empty.

Only the verified copies were activated. Previous databases, source files, and
the application image were retained for rollback. Both workspaces restarted
with healthy API, worker, maintenance, and database services.

| Workspace | Original recorded calls | Original tasks | Original API estimate |
|---|---:|---:|---:|
| Seeded demo | 144 | 72 | USD 0.088074750 |
| Clean | 0 | 0 | USD 0.000000000 |

Existing accounts, linked identities, sources, accounting facts, evaluations,
and saved reviews were preserved.

## Hosted acceptance

- Real Cognito sign-in and sign-out passed in both workspaces. Anonymous billing
  access was rejected; billing writes without CSRF were rejected.
- The seeded workspace now contains the explicitly loaded **fictional billing
  example**: five authored charge rows, one declared comparison, and two synthetic
  calls. It remains separate from the original recorded usage totals.
- The example displayed imported charges of `0.0121475`, a comparable captured
  estimate of `0.0001295`, and a selected-group difference of `0.000018` USD.
  Separate unassigned charges and the negative adjustment remained visible.
- JSON download preserved exact Decimal values and fixture provenance. Repeated
  example loading created no duplicate snapshots or calls. Task inspection
  showed the two synthetic calls; per-call invoice costs remained unknown.
- The clean workspace retained zero sources, usage, and billing reports. Its
  authenticated session could not retrieve the demo's billing report.
- Desktop and mobile billing checks passed, including matching sidebar/card
  colors, no horizontal page overflow, footer scrolling, and clearing private
  billing content at sign-out.
- A visible browser using the actual window viewport completed all eight panels
  in both workspaces. All 16 panels reached their footer with wheel scrolling.
  Existing task context, evaluation guidance, overview colors, and empty-state
  actions passed.

The hosted browser harness now includes Billing reconciliation and waits for its
content before checking scrolling. Its SSO navigation waits for the application
DOM, then verifies the visible workspace and authenticated session; waiting for
the full page load had timed out in the visible-browser run.

## Recovery and operations

Fresh schema-4 backups were uploaded after loading the example. Both were
downloaded, checksummed, and restored into temporary databases. Preserved
application tables and the four billing tables matched. The restored billing
export was identical except for the recalculated timestamp. The temporary
restore databases were removed without replacing either running workspace.

HTTPS, readiness, protected metrics, disabled local login, and authorization-code
SSO with PKCE passed. Scheduled backup and monitoring timers were active, and all
four existing readiness/backup alarms were OK after the upgrade.

## Scope and limits

This acceptance used zero paid model calls and no customer billing files or
AWS billing APIs. The example is authored evidence, not an authenticated invoice,
measured savings, or customer export compatibility proof.

The existing password-only hosted-test exception remains explicit; this does not
verify production MFA. This single-host acceptance does not establish high
availability or customer workload capacity. Private endpoints, account identifiers,
credentials, backups, screenshots, and operational receipts remain outside Git.

See [billing interpretation and upgrade instructions](BILLING.md), the
[local implementation checks](VERIFICATION-BILLING.md), and the
[hosted test guide](HOSTED-TEST.md).
