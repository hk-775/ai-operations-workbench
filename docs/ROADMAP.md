# From demonstration to product

The product question is: **What did this AI outcome cost, and is there evidence
for a better model choice?**

The initial demonstration answers that question for a fixed support workflow.
It does not yet capture every AI tool used by a company.

## 1. Completed vertical demonstration

- Connect a real saved usage run.
- Inspect the most expensive baseline task and both model calls.
- Regrade every model on the same cases.
- Explain why a model qualifies or is excluded.
- Export the evidence and criteria without changing production routing.

The support example gives us an inspectable decision contract. Its “no model
qualifies” result exercises the product's refusal to recommend an unsupported
cost reduction.

## 2. Completed first production milestone

The first production milestone has now added a single-team pilot alongside the
support demonstration: local accounts/RBAC, an AxonLLM application connector,
PostgreSQL persistence, recoverable evaluation jobs, and saved read-only reviews.
See the [pilot guide](PILOT.md).

The 0.2 self-hosted release adds company OIDC/MFA, PostgreSQL query pagination,
time-window totals, private metrics and an Operations page, scheduled data
retention, schema migration, HTTPS deployment, and isolated seeded/clean test
deployments. See [production installation](PRODUCTION.md).
The product scope remains one organization; the feature expansions below are
not implied by the presence of a production deployment profile.

The 0.3 release packages the optional AWS hosted acceptance, improved team UI,
and public narrated demo/architecture. The public site is a static walkthrough;
the authenticated application remains a customer-owned deployment.

## 3. Coding-task demonstration

Implemented in the source checkout: a reproducible **bug fix plus tests**
workflow with six separate cases, frozen snapshots, Docker execution, public
and acceptance tests, recorded final patches, every attempt's API accounting,
and a read-only result screen. An optional bounded AxonLLM recorder collects
actual model patches. Version 0.7 adds a frozen 18-task dataset, balanced repeated
collection, version 2 previews, and a [recorded calibration](CODING-CALIBRATION-2026-10-29.md).
See [coding evaluations](CODING-EVALS.md).

Each task should use an isolated repository snapshot with a known bug, a bounded
tool environment, hidden acceptance tests, and a recorded final patch. Measure
the entire task, including repair attempts and tool steps. Compare:

- Acceptance-test success and regressions.
- Model API usage and total observed task duration.
- Cost per accepted patch, including failed attempts.
- Human-review effort and compute costs when actually measured.

The coding adapter has its own dataset, contract, artifact format, and integrity
checks. It preserves the support recording. Representative private held-out
workloads, native subscription-tool capture, and customer
model recommendations remain future work.

## 4. Expand connector coverage

Implemented for the first pilot: AxonLLM application events with stable
application IDs, a durable local outbox, authenticated ingestion, source-scoped
deduplication, and explicit usage/attempt-coverage semantics. This does not
capture every AI tool or reconcile company-wide spending.

The common event contract needs source, workspace/team, task/session, parent call,
provider and model, timestamps, reported usage, cost basis, currency, and stable
deduplication identity. Preserve whether money is **estimated**, **billed**,
**allocated from a subscription**, or **unknown**.

The v0.4.0 release adds the first additional connector: **Bedrock Converse and
ConverseStream application capture**. It retains AWS token categories, reports
SDK retry coverage, records incomplete streams/crashes, and delivers through the
same durable outbox. Source-scoped heartbeats expose backlogs and stopped
collectors; the setup guide includes a no-charge fixture and an explicit bounded
live-call example. One reviewed model/region/mode rate is supported; other prices
remain unknown. This is not AWS invoice ingestion. See [Bedrock](BEDROCK.md).
An explicit schema-3 migration is required when upgrading an earlier installation.
See the [release and verification notes](RELEASE-0.4.0.md).

Add the remaining Codex, Cursor and Claude Code sources only after
validating what their supported exports and APIs actually expose. Product names
in the roadmap do not imply working integrations.

## 5. Reconcile the bill and attribute outcomes

Released in v0.5.0: [Bedrock billing reconciliation](BILLING.md), with
Ledger schema normalization and Workbench-owned snapshot persistence. Administrators
import complete monthly CSV exports and declare source/model scopes. The screen
shows precise differences, incomplete comparisons, credits/fees and other
unassigned charges, revisions, and exportable provenance. A fictional example
exercises the full flow without model calls. Schema 4 is required; this feature
is not included in the v0.4.0 release.
The existing seeded and clean AWS test workspaces have been
[upgraded and verified on schema 4](VERIFICATION-HOSTED-BILLING.md), including
fresh restore checks and the isolated fictional billing example.

Version 0.6.0 adds [independent billing acceptance checks](BILLING-ACCEPTANCE.md),
a [downloadable fictional sample](../data/billing-sample/README.md), and
[scheduled collection](BILLING-COLLECTION.md) for versioned Legacy CUR CSV/gzip
assemblies in S3. Collection status, failure preservation and alerts are included.
These additions, native Ledger aggregation and integrity checks are included in the v0.6.0 archive.

Real customer export acceptance and a real scheduled S3 delivery remain pending.
The optional export has now been provisioned in the selected account, with a
small real Bedrock sequence captured for comparison; the supplied downloadable
sample remains explicitly fictional. Next validate the delivered private evidence, then expand supported formats,
large organization exports and other providers. Imported records are not independently
authenticated invoices, and aggregate links do not allocate bills to tasks.

Decide how to attribute subscriptions, shared infrastructure, retries, caches,
human review, and incomplete traces. Unknown values must remain visible instead
of being converted to zero.

## 6. Production evidence and controlled changes

Provenance, role-based access, durable jobs/results, restart recovery, and
readiness checks are in the pilot. Next add representative held-out workloads,
repeated evaluation, independent review, customer billing validation, and customer-specific
load/restore objectives. SSO/MFA, scheduled retention, monitoring/alert rules,
and repeatable local load/restore checks are implemented in 0.2.

Only after that, design a reviewed rollout through AxonLLM/Ostiari with a
canary, rollback, and outcome monitoring. A proposal's projected API savings
should be compared with realized cost and quality after rollout.

The product can grow around these components without turning AxonLLM or Ostiari
into an unrelated company-wide dashboard.

## Historical v0.6.0 operational follow-through

The [reference drill](REFERENCE-ACCEPTANCE.md) now checks concurrent HTTP/replay,
paced reads, abandoned worker recovery and restoration into a separate PostgreSQL
container with exact table hashes and billing comparisons. It runs on one Docker
host; customer load objectives, fresh AWS host recovery and human alert delivery
remain acceptance work.

The [preparation tools](PREPARATION.md) create private billing input templates and
an 18-task coding calibration packet with balanced repeated candidate scheduling.
Real billing exports, scheduled S3 delivery, exact live models/budget, and a
representative private coding holdout remain required. Preparation is not a
customer acceptance pass or a model leaderboard.

## v0.7.0 acceptance tools

The expanded collector and viewer now run the full frozen schedule and expose
missing coverage. Recorded calibration results are included with their exact
inputs, attempts, costs, and limitations. The original underspecified decimal
prompt was corrected before the full published comparison was rerun.

Optional [AWS procedures](ACCEPTANCE-OPERATIONS.md) provision private billing
delivery and recover backups on a disposable independent host. Completion
evidence is recorded in [verification](VERIFICATION-0.7.0.md).
First billing delivery, independent customer controls, and a confirmed human
alert recipient remain separate acceptance gates.
