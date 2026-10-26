# Workbench 0.2.0 verification

Local release checks performed on **October 26, 2026**, on an Apple Silicon
development host with Docker. These results describe the shipped example and
tested configuration; they are not customer capacity or availability guarantees.

## Functional checks

| Check | Result |
|---|---|
| Python 3.13 suite, including PostgreSQL | 74 passed, 1 skipped |
| Fresh source archive on Python 3.12, including PostgreSQL | 74 passed, 1 skipped |
| Demo browser journeys | 7 passed |
| Team browser journeys, including Operations and pagination | 9 passed |
| Seeded deployment | Ready; 144 recorded calls, 72 tasks, 1 completed evaluation, 1 saved review |
| Clean deployment | Ready; zero usage, sources, recordings, evaluations, or reviews |
| Shared browser context | Both deployments remain signed in; signing out of one preserves the other session |
| Offline evaluation and database restore | Passed; exact `$0.088074750` captured-call estimate, saved evaluation and review preserved |
| Schema 1→2 | Transactional migration preserves saved accounting and unknown costs |
| Company identity | Signed mock OIDC provider exercises PKCE, token claims, MFA, explicit subject provisioning, state replay, and browser binding |
| Production proxy configuration | Validated with the patched image and a reserved example domain |
| Source archive | SHA-256 verified; private runtime directories excluded; Gitleaks found no secrets |

The skipped test is the SQLite concurrency variant of a PostgreSQL-specific
locking check. The suite also tests role boundaries, stale worker recovery,
retention previews and deletion, old-event retry rejection, and request-log
redaction. No paid model calls were made.

The 24-case recorded workload produces pass counts of 20/24, 18/24, and 14/24.
All models fail at least one critical case, so the default routing review
correctly returns **no eligible model**.

## Local metadata load check

`scripts/check_load.py` creates an isolated synthetic PostgreSQL schema. Its
25,000 events represent 12,500 tasks; these are metadata fixtures, not live model
traffic. Full totals remained correct and fixtures stayed excluded by default.

| Measurement | Result |
|---|---|
| Ingestion, batches of 100 | 5.74 seconds |
| Ingestion throughput | 4,354.8 events/second |
| Batch latency, p95 | 29.04 ms |
| Usage-page latency, p95 | 146.12 ms |

This is a single-client local check, run while other verification was active.
Measure the company's host, concurrency, retention volume, and ingestion pattern
before choosing operating limits.

## Dependency and runtime checks

Trivy 0.76.1 found **zero high or critical vulnerabilities** in each resulting
application, PostgreSQL, and Caddy runtime image at verification time. The database
helper and proxy were rebuilt with patched Go; the proxy's networking module was
updated, and unused curl packages were removed. No vulnerability exclusions were
used. This scan does not assert that lower-severity or undiscovered issues are absent.

The locked runtime registry packages passed `pip-audit` 2.9.0. AxonLLM and Ostiari
remain pinned to Git revisions; they are outside that registry audit's coverage.
CI includes dependency, runtime-image, and secret checks. The reported results
above are local verification, not a report of a GitHub Actions run.

## Installer acceptance

The [production guide](PRODUCTION.md) covers company-owned OIDC/MFA configuration,
TLS, monitoring, retention, backups, and upgrades. Each installation must verify
its actual identity-provider claims, alert delivery, encrypted storage, recovery,
and representative held-out workload. Those values belong in private deployment
configuration, not in the source release.
