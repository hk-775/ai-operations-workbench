# Self-host Workbench

Workbench is a self-hosted, single-organization product. Each company runs its own
stack and supplies its own DNS name, OIDC identity provider, secrets, monitoring,
and backup storage. None of those company values belongs in the release archive.
There is no vendor-hosted service or license activation call.

The supported scope is AxonLLM and instrumented Bedrock usage capture, exact captured-call estimates,
task inspection, support-v1 saved-output evaluations, and read-only routing reviews.
Version 0.5.0 adds [manual Bedrock billing reconciliation](BILLING.md)
with declared aggregate scopes; the published 0.4.0 archive does not include it.
Native subscription-tool billing connectors, automatic billing collection, arbitrary
evaluation plugins, and automatic routing changes are separate product features.

## Try the seeded and clean deployments

Requirements: Docker with Compose v2, uv, Git, and sufficient capacity
for two PostgreSQL/app/worker stacks. On the development machine, budget at least
6 GB for Docker. uv installs the tested Python 3.13 runtime. These deployments
bind to loopback and use local accounts.
The first build downloads public Python and Go dependencies. If the standard Go
proxy is unavailable on the host network, set `WORKBENCH_GOPROXY` to an approved
Go module mirror; checksum-database verification remains enabled.

From the cloned repository or extracted release directory, install the locked
environment, then build, start, initialize, and seed the right instance:

```bash
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

It preserves existing accounts and data when run again. The equivalent individual
steps are:

```bash
uv run --locked python scripts/setup_instances.py
docker compose --env-file .pilot/instances/demo/compose.env -f compose.instances.yaml up --build --wait
docker compose --env-file .pilot/instances/demo/compose.env -f compose.instances.yaml exec -T app \
  python -m workbench.pilot init --team "Workbench recorded demo" --username admin \
  --password-file /run/secrets/admin_password
docker compose --env-file .pilot/instances/demo/compose.env -f compose.instances.yaml exec -T app \
  python -m workbench.pilot seed-demo

docker compose --env-file .pilot/instances/clean/compose.env -f compose.instances.yaml up --wait
docker compose --env-file .pilot/instances/clean/compose.env -f compose.instances.yaml exec -T app \
  python -m workbench.pilot init --team "My AI team" --username admin \
  --password-file /run/secrets/admin_password
```

| Deployment | Default address | Initial content |
|---|---|---|
| Demo | `http://127.0.0.1:8770/` | 144 recorded calls, 72 tasks, completed evaluation, saved routing review, audit history |
| Clean | `http://127.0.0.1:8771/` | Administrator account; zero usage, recordings, evaluations, or proposals |

Both use username `admin`. Passwords are generated independently in the private
`.pilot/instances/demo/admin-password` and `.pilot/instances/clean/admin-password`
files. There is no published default password. Read the appropriate file locally
when signing in; never copy it into source control, an issue, or a release.
Use `--demo-port` / `--clean-port` during setup if those ports are occupied.

The two Compose project names, volumes, database credentials, browser cookies, and session stores
are separate. Starting or seeding one does not initialize the other.
`init` refuses to replace an existing team. `seed-demo` is idempotent and resumes
its own interrupted seed; it refuses to seed an unrelated populated ledger.

The demo makes **zero paid model calls**. Its 144 saved calls cost an estimated
`$0.088074750` when originally recorded. The pass counts are 20/24, 18/24, and
14/24; every model has a critical failure, so the default review selects no model.
Recorded history is not labeled as live observed traffic in Operations.

Stop an instance with its same Compose arguments and `stop`. Resume with `up -d`.
Use `down` without `--volumes` to preserve its data.

## Configure a company's production installation

Use a separate production checkout and host. The production Compose project has
its own database volume. Choose the retention periods under the company's policy.
The examples below are installation placeholders, not shared credentials.

Register a confidential OIDC web client with the exact callback:

```text
https://workbench.company.example/api/auth/oidc/callback
```

Enable authorization-code flow, PKCE S256, and MFA in the identity provider.
Workbench verifies signed RS256/ES256 ID tokens, issuer, audience, expiry, nonce,
and the configured MFA claim. Determine what that provider actually emits:
`amr` is a list of authentication methods; `acr` is an assurance-level string.
Do not configure a claim that the provider does not return or treat a password-only
assurance level as MFA. The provider must support client-secret basic authentication.

```bash
uv run --locked python scripts/setup_production.py \
  --domain workbench.company.example \
  --issuer https://identity.company.example \
  --client-id company-issued-client-id \
  --required-amr mfa \
  --retention-days 90 --evidence-retention-days 365 --audit-retention-days 730
```

Use `--required-acr YOUR_MFA_ASSURANCE_LEVEL` instead of `--required-amr` when
appropriate. Preserve the exact issuer, including a trailing slash if it has one.
Setup prompts privately for the client secret and generates a separate metrics
credential. It creates `.pilot/production.env` and `.pilot/prometheus.yaml`,
preserves existing secrets, and refuses to replace an existing production config.
It starts no services and sends no credentials to a vendor.

Build, migrate, initialize, and link the first administrator before accepting traffic:

```bash
docker compose --env-file .pilot/production.env -f compose.production.yaml build app db proxy
docker compose --env-file .pilot/production.env -f compose.production.yaml up -d db
docker compose --env-file .pilot/production.env -f compose.production.yaml run --rm app \
  python -m workbench.pilot migrate
docker compose --env-file .pilot/production.env -f compose.production.yaml run --rm app \
  python -m workbench.pilot init --team "Company AI operations" --username admin
docker compose --env-file .pilot/production.env -f compose.production.yaml run --rm app \
  python -m workbench.pilot link-identity --username admin --subject COMPANY_ADMIN_SUBJECT
docker compose --env-file .pilot/production.env -f compose.production.yaml run --rm app \
  python -m workbench.pilot check-production
docker compose --env-file .pilot/production.env -f compose.production.yaml up --wait
```

The initialization password is for account bootstrap. Production disables local
password sign-in; use the linked company identity. Administrators provision further
company subjects in **Team & audit**. Email matching does not automatically link
accounts. Roles remain local and explicit. Disabling a Workbench account revokes
its sessions. Coordinate employee offboarding in both systems; this release does
not implement SCIM or back-channel identity-provider logout.

Point DNS to the host and permit the certificate challenge and HTTPS traffic.
The included Caddy proxy obtains and renews TLS certificates. For a private
intranet or existing managed proxy, replace the proxy service with that company's
TLS termination, preserve the configured Host, and keep app/database ports private.
Use encrypted host volumes and encrypted backup storage. Workbench does not
implement application-level encryption of database fields.

Production refuses startup without HTTPS, OIDC, an MFA requirement, monitoring
credentials, explicit retention periods, and schema version 4 in v0.5.0. The API and worker
check the schema rather than silently performing an upgrade. Install matching
images for the app, worker, and maintenance service.
The v0.3.0 release used schema 2. Version 0.4.0 adds collector
health in schema 3. Version 0.5.0 adds billing snapshots and declared
comparisons in schema 4; follow the backup/migrate/restart and rollback instructions
in [the billing guide](BILLING.md#access-retention-and-upgrade). Billing revisions
and mappings follow evidence retention. The v0.4.0 download remains schema 3.

## Monitor and operate

- **Operations** is administrator-only and shows worker heartbeat, queue age,
  failed evaluations, unknown-cost coverage, maintenance freshness, and sources
  with reported backlogs or stale collectors. **Usage sources** shows last-reported
  queue counts; disconnected collectors may have additional unknown backlog.
- `/metrics` requires the independent monitoring bearer token. Install the generated
  Prometheus scrape configuration, mount its token as
  `/run/secrets/workbench_metrics_token`, and install
  [the alert rules](../deploy/alerts.yaml) as `/etc/prometheus/workbench-alerts.yaml`.
  Connect those rules to the company's existing Alertmanager/on-call destination.
  Workbench does not send messages or silently create an external notification service.
- `/health/live` checks the API; `/health/ready` also checks worker and production
  maintenance freshness. Request logs contain generated request IDs, route templates,
  status, and duration; they exclude queries, headers, credentials, and payloads.
- Suggested initial operating objectives: alert within two minutes of API failure,
  investigate queue waits over five minutes, back up at least daily, and practice
  a restore within one hour. These are operator targets, not availability guarantees.

Read-only operational inspection:

```bash
docker compose --env-file .pilot/production.env -f compose.production.yaml exec -T app \
  python -m workbench.pilot operations
docker compose --env-file .pilot/production.env -f compose.production.yaml exec -T app \
  python -m workbench.pilot maintenance --dry-run
```

Usage pages aggregate in PostgreSQL and return bounded task/call pages. All totals
cover the selected filter, not just the current page. Time windows use UTC with an
inclusive start and exclusive end. Monetary calculations use integer nanodollars
and Decimal formatting; missing costs remain unknown. Pagination is a live view:
new ingestion may change task ordering between page requests.

The production scheduler runs hourly, in bounded batches. It expires operational
usage by event time, uploaded recording graphs by upload time, and audit entries by
creation time. Recording graphs include their calls, completed jobs, and saved reviews.
Active queued/running evaluations protect their recordings until they finish.
Export evidence that must be retained before its configured expiry.

Once an operational event cutoff advances, old connector events are rejected
rather than re-counted after a retry. A connector with an overdue historical outbox
requires operator review. Local test deployments disable scheduled data deletion.
Backups have their own retention and deletion policy, configured by the company.

## Backup, restore, and upgrade

Use a private shell umask and the company's encrypted backup destination:

```bash
umask 077
mkdir -p .pilot/backups
docker compose --env-file .pilot/production.env -f compose.production.yaml exec -T db \
  pg_dump -U workbench -d workbench -Fc > .pilot/backups/workbench.dump
```

Keep `.pilot/` securely with the recovery plan. Back up the Caddy certificate volume
or plan for certificate reissuance. Schedule database backups with the company's
backup service and alert on missing/failed backups. The maintenance process deletes
expired application data; it is not a backup service.

The container verification command creates separate temporary databases, checks a
real offline evaluation, restores a dump, and verifies exact totals and saved reviews:

```bash
uv run --locked python scripts/check_pilot_stack.py \
  --env-file .pilot/production.env --compose-file compose.production.yaml
```

It does not replace the running company database. For disaster recovery, restore
the archive into a new database, point a separate matched stack at it, and check
company sign-in, source delivery, totals, and reviews before switching traffic.

For an upgrade: back up; stop app, worker, and maintenance; build the new release;
run `migrate`; start the matched services; verify readiness and run the restore check.
Migration 1→2 backfills query facts from saved accounting without repricing events.
Migration 2→3 adds collector health and registers the reviewed Bedrock price
snapshot; it preserves existing event fingerprints, accounting, and reviews.
The migration is transactional and lock-protected. A failed migration rolls back.
Unknown newer schemas refuse startup. Keep the pre-upgrade dump and prior image;
do not downgrade the schema in place.

## Release acceptance

The automated suite exercises SQLite and PostgreSQL, conflicting/concurrent
ingestion, migrations, role boundaries, OIDC signatures and claims, MFA, browser-bound
single-use state, worker recovery, retention, desktop/mobile journeys, and offline
backup restoration. `scripts/check_load.py` measures a dedicated synthetic schema.

Each installer still verifies its own DNS/TLS, actual IdP claim behavior, encrypted
storage, alert delivery, and recovery on its host. Those are customer configuration
checks; they do not require a company identity to be embedded in the product release.
Representative held-out workload evaluation is required before acting on a review.
The bundled 24-case example is product demonstration evidence, not a universal
validation of a company's models.

The opt-in [AWS hosted acceptance test](HOSTED-TEST.md) exercises a dedicated
server with separate seeded and clean workspaces. Its explicitly selected
password-only SSO profile is a test exception; standard production still
requires a verified MFA claim.

## Runtime image maintenance

The application uses a minimal Alpine runtime without build tools. The database
keeps the pinned upstream PostgreSQL engine and entrypoint, with its `gosu` helper
rebuilt using patched Go. The standard Caddy proxy is built from pinned module
versions and `go.sum`, with patched Go/networking dependencies and unused curl
packages removed. These recipes are in `deploy/images/`; they do not modify
PostgreSQL's data format or add custom Caddy plugins.

The proxy build also includes a checksum-verified
[JOSE security backport](../deploy/images/proxy/patches/README.md) with its upstream
Apache-2.0 license, build regression checks, and a runtime self-test. CI binds its
VEX evidence to the actual scanned image and SBOM.

CI scans all three resulting runtime images for high and critical vulnerabilities.
Image and dependency pins still require updates as new findings appear. See the
dated [release verification](VERIFICATION-0.5.0.md) for this release's checks.
