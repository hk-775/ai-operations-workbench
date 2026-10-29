# Workbench 0.8.0 verification

The connector implementation was checked on October 29, 2026:

- **215 backend tests passed**, covering SQLite and PostgreSQL 16. Five skips
  comprised database-specific checks that do not apply to SQLite and the
  separately enabled coding-execution container test.
- **17 authenticated browser checks passed**, including all three native CLI
  imports, source-token delivery, duplicate replay, separate exact Decimal totals,
  synthetic-data filtering, mobile layout and sign-out clearing.
- A visible browser using its actual window dimensions checked wheel and keyboard
  scrolling and a visible footer on all nine workspace panels.
- Gitleaks scans covered code, tests, documentation, authored native data and
  frontend assets. Private verification receipts remain outside Git.

The contract tests also cover wrong-tool token rejection before outbox binding,
removal of private-content sentinels, OTLP batch rollback, Cursor pagination and
redirect rejection, complete frozen windows, explicit zero versus unknown cost,
cache-category semantics and preservation of legacy event fingerprints.

Operations tests verify that native usage cannot trigger or dilute the alert for
missing AxonLLM/Bedrock API prices. No model calls or authenticated vendor API reads
were made in these checks. Cursor HTTP responses and native input files were
authored fixtures; this is not live vendor-account acceptance.

## Release and deployment checks

The clean local release checkout repeated all 215 backend checks with PostgreSQL
and passed **33 browser checks**: 13 demo, 17 authenticated workspace and three
public Pages checks. The extracted source archive also clean-installed and passed
11 connector/packaging checks; its three PostgreSQL variants were covered by the
full database run. The archive's 275 files matched the reviewed source, and its
contents passed a separate secret scan.

The release pipeline clean-installs locked Python 3.12/3.13 and Node dependencies,
runs backend and browser suites, checks local containers and restore behavior,
audits dependencies/images, scans Git history, and tests the public Pages build.
The public walkthrough retains its static-only network boundary, bundled
narration, animated circles, pause and reduced-motion controls.

Release publication verifies the actual source archive, its download checksum,
included native examples and private-file exclusions. Hosted acceptance checks
each workspace's source/image version, unchanged schema and stable data,
production configuration, anonymous HTTPS boundary, real company sign-in,
connector choices and all nine panels. Installation addresses and credentials
are retained only in private operational receipts.

CI and deployment receipts establish the final release result; the implementation
counts above describe the completed local checkpoint. Deploying these collectors
does not automatically configure or authenticate a user's coding-tool account.
Real billing delivery, human alert acknowledgment, representative customer
holdouts and subscription allocation remain separate acceptance work.
