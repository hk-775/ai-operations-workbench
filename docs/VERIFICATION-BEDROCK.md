# Bedrock connector verification — October 27, 2026

Scope: the connector development branch after v0.3.0, with schema 3.
This is local SDK-contract/application integration evidence; no hosted deployment
or live AWS model run is claimed.

- **92 backend checks passed; two SQLite variants skipped because their
  concurrency checks require PostgreSQL.** Both SQLite and an isolated PostgreSQL 16 database were exercised
  with Python 3.13 and locked dependencies.
- **11 authenticated browser journeys passed** against PostgreSQL. The new
  Bedrock journey creates a source/token through the UI, runs the actual fixture
  and delivery CLI subprocesses, verifies a two-call task and $0.000129500
  synthetic estimate, repeats delivery without duplicate costs, and checks
  backlog warnings, mobile layout and footer scrolling.
- **SDK contract:** boto3 Stubber validates nonstreaming request/response shapes;
  synthetic streams exercise completion, early closure, missing metadata and
  failures. Response content, prompts, HTTP headers and error messages stay out
  of captured events.
- **Accounting:** exact Decimal pricing, region/mode/date mismatch, expired rate
  review, unknown/cache usage, retry coverage, and unreconciled invoice/hardware
  costs are covered. A cache TTL breakdown without its aggregate write count
  remains an explicit capture gap.
- **Durability:** reserve before invocation, surface local persistence failure,
  crash recovery before/after enqueue, lost delivery acknowledgment and replay,
  source binding and token rotation/revocation are covered.
- **Health and access:** authenticated/scoped reports, source-kind mismatch,
  viewer restrictions, team isolation, stale/backlog states, multiple collectors,
  retirement, aggregate private metrics and operational alerts are covered.
  Database tests advance the collector clock; the browser separately renders a
  simulated stale response.
- **Upgrade:** migration from schema 2 to 3 is explicit and idempotent and
  preserves existing events, costs and fingerprints.
- **Visual inspection:** desktop source setup/health, task inspection and mobile
  connection health retain the existing Workbench palette and fit the viewport.
- **Secret scan:** the allowlisted tracked/new source tree passed Gitleaks.

No paid model calls were made. No new real quality, latency, savings or billed
cost measurements were produced. The two-call fixture is excluded from normal
usage totals unless synthetic data is explicitly included.

Reproduce with the existing PostgreSQL test URL file:

```bash
uv sync --locked
WORKBENCH_TEST_DATABASE_URL_FILE=/private/path/database-url \
  uv run --locked pytest -q
npm ci
WORKBENCH_TEST_DATABASE_URL_FILE=/private/path/database-url \
  npx playwright test --config=playwright.pilot.config.js --reporter=line
```

The original local demo/media/public-site files were not changed. Their existing
release verification is in `VERIFICATION-0.3.0.md`; those media/browser suites
were not rerun for this connector-only change.
