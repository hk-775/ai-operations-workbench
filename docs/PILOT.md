# Run the first team pilot

This milestone adds one authenticated team, an AxonLLM usage connector, a
PostgreSQL usage ledger, durable offline evaluation jobs, and saved routing
reviews. It is a self-hosted pilot with local accounts. Company OIDC/MFA and
production operations are available in the [production profile](PRODUCTION.md). Billing
reconciliation, arbitrary evaluation plugins, and routing activation remain
outside this milestone.

The original no-login demonstration still runs on port 8767. Pilot mode is
explicit and has separate routes, storage, and a sign-in screen.

## Start locally

Requirements: Linux or macOS (Windows via WSL2), Docker with Compose, Git, and
Python 3.12+ (or the project's uv-managed Python). Run setup as an ordinary
user, without sudo.

```bash
uv sync --locked --python 3.13
uv run --locked python scripts/setup_pilot.py
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml up --build -d
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml exec app \
  python -m workbench.pilot init --team "My AI team" --username admin
```

The last command prompts twice for your administrator password (14–128
characters). There is no default password. Open **http://127.0.0.1:8768/** and
sign in. `init` refuses to replace an existing team. If a password is lost, use
the same command with `reset-password --username admin` instead of `init`.
Automation can pass `--password-file` pointing to a private, mode-600 file
inside the container; do not put a plaintext password in a command argument.

If port 8768 is occupied, add both lines below to `.pilot/compose.env`, then run
the Compose command again:

```dotenv
WORKBENCH_PILOT_PORT=8769
WORKBENCH_PUBLIC_ORIGIN=http://127.0.0.1:8769
```

Setup generates database secrets in `.pilot/`, a mode-700, gitignored directory.
Two files mounted only into PostgreSQL are readable by its nonroot process;
the directory prevents other host users from reading them. The application
uses a separate nonsuperuser database role, not PostgreSQL's administrator.
App/worker processes run under the host UID/GID from `.pilot/compose.env` so
their mode-600 connection file stays private. Setup preserves existing secrets.
The Docker build context excludes `.pilot/`, `.env`, local ledgers, and outboxes.

Check the services:

```bash
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml ps
curl --fail http://127.0.0.1:8768/health/ready
```

`/health/live` checks the API process. `/health/ready` additionally requires a
recent database-backed worker heartbeat. Change the URL if you selected another
port. The worker health check checks that container's own worker identity.

## Use the team dashboard

1. In **Team & audit**, create individual accounts. Viewers read evidence;
   analysts import recordings, queue/cancel evaluations, and save reviews;
   administrators also manage users and ingestion tokens.
2. In **Usage sources**, create an AxonLLM or Amazon Bedrock source and issue its token. Save the
   token once in a private file on the application host. Tokens expire after
   30 days.
3. Deliver usage events with the connector below. The overview refreshes every
   ten seconds while visible. Filter by project/source and inspect captured
   task calls in the yellow **Task explorer**.
4. In **Model evaluations**, load the bundled recorded example or upload a
   compatible support-v1 recording. Queue the offline evaluation.
5. In **Routing review**, select a completed evaluation, tune pass-rate/latency
   criteria and the monthly-volume assumption, then save/export the review.

The bundled example contains 144 historical calls on fictional tickets.
Importing it produces 72 captured tasks and a **$0.088074750 API estimate**.
The recorded pass counts remain 20/24, 18/24, and 14/24. Each model has a critical
failure, so default routing review returns **no eligible model**. No new model
calls or charges are incurred by this workflow.

Usage metadata cannot establish output quality. The evaluation engine currently
accepts only the versioned support-v1 contract. It does not evaluate arbitrary
application tasks just because their usage appears in the ledger. A generic
workload adapter and representative held-out data are future milestones.

For native boto3 Converse/ConverseStream application capture, follow
[the Bedrock guide](BEDROCK.md). The AxonLLM wrapper below retains its existing
nonstreaming contract. Source tokens accept their selected connector's schema.
Version 0.4.0 requires an explicit migration to schema 3 for collector
health; v0.3.0 deployments use schema 2.
Version 0.5.0 source requires schema 4 for
[Bedrock billing reconciliation](BILLING.md), including its explicit fictional
example. Follow the backup and migration instructions before upgrading.

## First connector delivery, without model calls

Use a dedicated **historical backfill** source for this check. Save its token in
a mode-600 file, for example `.pilot/ingest-token`, without committing it.

```bash
export WORKBENCH_INGEST_URL=http://127.0.0.1:8768/api/pilot/ingest
export WORKBENCH_INGEST_TOKEN_FILE="$PWD/.pilot/ingest-token"
uv run --locked python -m workbench.connector \
  --outbox .pilot/backfill.outbox.db backfill data/model-comparison.json
uv run --locked python -m workbench.connector \
  --outbox .pilot/backfill.outbox.db deliver
```

Running the same backfill/delivery again adds no duplicate events to that source.
Backfill retains the `recorded` evidence label. Fixtures retain `fixture`, are
excluded from normal usage views, and cannot produce a measured recommendation
or savings figure.

Do not combine this historical source with the dashboard's imported comparison
source when interpreting a total: they represent the same saved calls through
two intentional demonstrations of ingestion. Deduplication is **within a
source**, not an unverifiable match across applications. Use the source filter,
and use a fresh source for each actual application.

## Instrument AxonLLM

Run the integration in an environment containing this checkout and its locked
dependencies. The adapter consumes the pinned public `ChatCompletionResponse`
contract; no changes to AxonLLM are required.

```python
from pathlib import Path
from workbench.connector import Outbox, capture_completion

outbox = Outbox(Path(".usage/application.outbox.db"))

# router is your existing AxonLLM AsyncRouter. Keep the same task_id for all
# stages of a task, and use non-sensitive project/stage identifiers.
response = await capture_completion(
    router, outbox,
    task_id="support-2026-001",
    project="support",
    stage="draft",
    model="your-configured-logical-model",
    messages=messages,
    usage_basis="unknown",
    attempt_coverage="final_response_only",
)
```

This wrapper performs the application model call and persists metadata locally.
**It can incur your application's normal model costs.** Delivery is separate:

```bash
uv run --locked python -m workbench.connector \
  --outbox .usage/application.outbox.db deliver --watch
```

Run delivery under your existing process supervisor. It checks for ready events
every five seconds and retries with bounded backoff. It never sends prompts,
response content, provider credentials, or a client-computed cost. The outbox
binds to both the destination and the authenticated source; rotating a token for
the same source is supported, switching it to another source is rejected.

Set `usage_basis="provider_reported"` only when your provider path supplies
actual counts. AxonLLM's normalized response does not prove whether missing usage
was estimated, or whether every cache category was retained. The conservative
default is therefore unknown. `attempt_coverage="single_attempt"` is an explicit
application assertion: use it only when retries/fallbacks are disabled and the
captured response covers the one attempt. The default does not claim to account
for retry costs.

The wrapper generates an application call ID before invocation; provider
response IDs are only correlation metadata and may repeat. It reserves the call
durably, then finalizes a success/error event. Failed calls with no reported
usage have unknown cost. Local disk failures are surfaced, never silently ignored.
Persist and monitor the outbox volume; it is part of the accounting path.

After an application crash, **stop all capture processes using that outbox**
before recovering unfinished calls:

```bash
uv run --locked python -m workbench.connector \
  --outbox .usage/application.outbox.db recover-inflight
```

Recovered calls are labeled interrupted with unknown usage/cost. Recovery does
not invent provider results or automatically rerun paid calls. Restart the
application and delivery supervisor afterward. Streaming through AxonLLM,
per-attempt provider hooks, automatic invoice reconciliation, and an installable
standalone connector package are not implemented. The separate Bedrock connector
supports ConverseStream.

The delivery CLI now sends source-scoped heartbeats. Use `deliver --watch` under
a supervisor for continuous health; a one-shot delivery becomes stale after
three minutes. `status` inspects the local queue without sending data.
`--no-health` explicitly disables monitoring for old AxonLLM servers. See the
[collector health guide](BEDROCK.md#4-supervise-delivery-and-inspect-health).

## Event and accounting contract

`UsageEvent` in `workbench/pilot/events.py` is the strict `axon.usage.v1` schema.
Each batch has 1–100 events and is transactional. Duplicate IDs with identical
payloads are acknowledged; changed data under an existing ID rejects the whole
batch. Team/source identity comes from the bearer token, never from event input.
Unknown fields, nonfinite numbers, invalid cache counts, and unzoned/future
timestamps are rejected.

| Field | Meaning |
|---|---|
| `event_id`, `task_id` | Stable application event ID; grouping ID within a source |
| `project`, `stage` | Non-sensitive application labels |
| `provider`, `model` | Actual provider/model when known, not an assumed mapping |
| `occurred_at`, `latency_ms`, `status` | Source timestamp, captured duration, success/error/interrupted |
| `evidence` | observed, recorded, or fixture |
| `usage_basis` | provider_reported, estimated, or unknown |
| `attempt_coverage` | single_attempt, final_response_only, or unknown |
| `usage` | Input/output/cache token counts, or null |
| `provider_response_id` | Optional correlation identifier, never the deduplication key |

Workbench recomputes USD amounts using Decimal and the immutable saved pricebook.
Only reviewed OpenAI model snapshots in `config/prices.json` are priced.
Unsupported models, unreported/estimated counts, and unsupported cache-creation
units remain unknown. Pricebook hashes are retained with events; changing prices
does not rewrite old charges.

The displayed amount is a **captured-call estimate/subtotal**, not a reconciled
end-to-end bill. Unknown call costs and incomplete attempt coverage are counted
separately. Hardware/electricity and invoice costs remain unmeasured. Source
authentication identifies who submitted data; it does not attest provider
provenance or prove that unobserved calls do not exist.

Usage totals are aggregated in the database, with paginated task and call details
and optional UTC time windows. The former 10,000-event working-set limit is
removed. The production profile adds retention scheduling and monitoring.
Invoice reconciliation and cost-enforcement budgets remain separate features.

## Persistence and recovery

PostgreSQL stores team accounts, revocable sessions, sources/token hashes, immutable
usage events and pricebooks, original recordings, leased jobs, evaluation results,
saved routing reviews, and metadata audit events. The first schema migration is
idempotent and advisory-lock protected. Schema 3 adds collector health while
preserving prior payloads, costs and fingerprints. An unknown schema version
refuses startup.

Queueing is serialized per team and deduplicated by recording plus evaluator
revision. Workers claim with `FOR UPDATE SKIP LOCKED`, renew a 30-second lease,
and persist results only while they still own an unexpired lease. A crashed
worker's job is recovered after lease expiry, at most three attempts. Cancellation
revokes ownership. A separate 90-second watchdog stops the evaluator even with
no browser open. Evaluator code/configuration/lock hashes remain attached to
results; a changed evaluator requires a fresh replay before a new proposal.

Stop/restart without discarding the volume:

```bash
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml stop
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml up -d
```

Keep `.pilot/` with the volume. Regenerating passwords does not rotate credentials
inside an already initialized PostgreSQL volume. Rotate through PostgreSQL and
update mounted secrets as one coordinated operator action.

For a consistent backup (run with a private umask):

```bash
umask 077
mkdir -p .pilot/backups
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml exec -T db \
  pg_dump -U workbench -d workbench -Fc > .pilot/backups/workbench.dump
```

Validate the archive in an **empty restore database**, not over the running
pilot. For example, create `workbench_restore` as the database administrator,
restore as its owner, and point a separate pilot instance at it:

```bash
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml exec -T db \
  createdb -U postgres -O workbench workbench_restore
docker compose --env-file .pilot/compose.env -f compose.pilot.yaml exec -T db \
  pg_restore -U workbench -d workbench_restore --no-owner --exit-on-error \
  < .pilot/backups/workbench.dump
```

Check usage totals, saved evaluations/proposals, and sign-in after restoration.
Backups include uploaded model content and account/session/token hashes; encrypt
them with your host's backup system and restrict access. The Compose volume
itself is not application-encrypted. Set retention and test restores before
using sensitive customer data.

Before an upgrade, back up, stop app/worker, deploy a matched image to both, and
run `python -m workbench.pilot migrate` with the new image/database configuration.
Then start both and check readiness. Code rollback is safe only with a compatible
schema; otherwise restore the pre-upgrade backup into a separate database.

## Team deployment boundary

The supplied Compose stack binds only to loopback. To serve a team remotely,
put it behind your managed HTTPS reverse proxy, set
`WORKBENCH_PUBLIC_ORIGIN=https://your-host`, preserve that Host header, and keep
the application/database ports private. The pilot rejects non-loopback HTTP
origins. Cookies become Secure under HTTPS. The supplied Uvicorn command ignores
forwarded client-IP headers, so sign-in rate limits conservatively share the
proxy IP; configure trusted proxy handling deliberately if required.

Sessions are opaque, hashed server-side, HttpOnly/SameSite Strict, and expire
after eight hours or thirty minutes idle. Writes require session-derived CSRF
tokens. Login throttling is persisted. Disable an account to revoke its sessions;
the last active administrator cannot be disabled. Source tokens cannot read team
data or use browser endpoints. Issue a replacement token, move the connector,
then revoke old credentials as described below.

For rotation, issue a replacement token, deploy it to the connector, verify
delivery, then revoke the previous token using its displayed prefix. Other
tokens for that source remain valid. **Revoke all tokens** is available when the
entire source must be disconnected; its outbox can catch up after a new token is
deployed.

The offline evaluator gets a small allowlisted environment and no database,
source, or provider credentials. It runs the fixed trusted grader, not arbitrary
uploaded code. This is not a general-purpose sandbox. The app/worker containers
have read-only filesystems, temporary scratch space, resource limits, dropped
capabilities, and no routing-activation endpoint.

This local-account configuration does not deploy a cloud service or assert SaaS
tenant isolation, certify compliance, or establish operating SLOs. Those are
customer-specific operational checks. The production profile configures company
SSO/MFA without embedding any company's identity information in the release.

## Verify changes

```bash
uv run --locked pytest -q
npm ci
npx playwright install chromium
npx playwright test --config=playwright.pilot.config.js
```

Set `WORKBENCH_TEST_DATABASE_URL_FILE` to a private file containing a PostgreSQL
connection URL to exercise concurrency/lease behavior against PostgreSQL.
The test role must be able to create/drop **test schemas** in that dedicated test
database. Tests create unique schemas and never drop the whole database. Without
that variable, the fast SQLite tests run and PostgreSQL-specific tests skip.
CI provides PostgreSQL and runs both demo and pilot browser journeys.
The container job also builds the shipped image, bootstraps a temporary database,
replays evidence, and restores a backup. Run that same check against a running
local Compose stack with:

```bash
uv run --locked python scripts/check_pilot_stack.py
```

It creates and removes uniquely named smoke-test databases. It does not initialize
or replace the main pilot's team, records, or administrator password.

Tests use generated credentials and offline evidence. They cover access control,
CSRF, expiry/revocation, conflicting batches, repeated provider IDs, unknown/zero
costs, source/team boundaries, lost delivery acknowledgments, worker leases and
timeouts, restart persistence, fixture safeguards, mobile layout, escaped input,
and motion controls. No paid model calls are part of the test suite.
