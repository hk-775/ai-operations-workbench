# Reproducible production reference drill

Use the actual application image over loopback HTTP to check concurrent traffic,
worker lease recovery and database restoration before customer acceptance.
The harness creates two disposable Compose projects and removes only those
projects and their volumes. Existing demo, clean and AWS deployments are not used.

```sh
uv sync --locked --python 3.13
docker build -t ai-operations-workbench:reference .
docker build -f deploy/images/Dockerfile.postgres \
  -t ai-operations-workbench-postgres:0.2.0 deploy/images
uv run --locked python scripts/check_reference.py \
  --image ai-operations-workbench:reference \
  --events 25000 --clients 4 --seconds 300 \
  --output .pilot/reference/receipt.json
```

Only locally available images are used, resolved to their content IDs. The
runtime uses the shipped app, non-superuser database role, read-only application
filesystem, resource limits, and private generated credentials. HTTP addresses
bind to loopback. The reference profile uses local password authentication.

The drill:

1. Sends every synthetic 100-event batch twice through four concurrent HTTP
   clients, interleaving duplicate delivery. Asserts exact added/duplicate totals.
2. Runs concurrent paginated usage reads for five minutes with 100 ms pacing per
   client, checking totals and page sizes on every response. Verifies fixtures
   remain excluded from normal usage.
3. Stops its worker, queues saved offline evaluation, claims a five-second lease
   in a process that exits, and restarts the worker. Verifies recovery on attempt
   two, one completion audit, and rejection of writes from the abandoned owner.
4. Loads recorded support evidence and the explicitly fictional billing example,
   evaluates it and saves a routing review. Stops writers for a consistent dump.
5. Restores into a separate PostgreSQL container, volume, network and generated
   database credentials. Compares **every table's row count and content hash**
   before starting the destination app, then checks restored HTTP usage,
   evaluation availability and Ledger financial comparisons.

The receipt includes image IDs, resource limits, workload, latency percentiles,
request counts, worker checks and restoration checks. It is written only after
all checks and cleanup succeed. Credentials and the in-memory database backup
are not included. The short CI profile uses 1,000 events and a 15-second read
phase; it is distinct from the longer local reference run.

This is a **separate stack on the same Docker host**. It does not verify loss of
the physical/AWS host, multi-host availability, customer OIDC/TLS/MFA, human
on-call delivery, real billing exports or customer capacity. A five-minute paced
read phase is not an extended leak test or an arrival-rate capacity guarantee.
Reported recovery duration is the measured drill, not a contracted RTO.

For customer acceptance, prepare a separately provisioned host using
[the production runbook](PRODUCTION.md), restore an encrypted customer-owned
backup with their secret/identity setup, and verify their DNS, HTTPS, roles,
retention, monitoring and agreed RPO/RTO. Drive representative concurrent ingest,
reads and evaluations using agreed arrival rates and durations, and have the
named on-call owner acknowledge a test notification. Record dated evidence.
The existing hosted password-only test exception remains unchanged; these
reference checks do not establish production MFA acceptance.
