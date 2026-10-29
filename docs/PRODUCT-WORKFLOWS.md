# Spend planning, custom evaluations and connector setup

**Unreleased source features.** These screens are in the authenticated Workbench
workspace and require **schema 6**. The published v0.9.2 archive remains on schema 5.
The no-key support demonstration and public video keep their existing workflow.
See [local verification and its boundaries](VERIFICATION-PRODUCT-WORKFLOWS.md).

## Spend planning

Open **Spend planning → Create or revise a budget**. Choose a UTC calendar month,
USD limit, warning percentage, optional project/source, and one cost basis:

| Basis | Included amounts |
| --- | --- |
| Estimated API spend | Original captured AxonLLM or Bedrock API estimates |
| Tool-reported model amount | Claude Code or Cursor reported model estimates |
| Cursor-reported usage amount | Cursor reported usage charges |
| Allocated monthly cost pools | Current administrator-entered allocations |

Never add these columns indiscriminately: a model estimate may describe usage
already covered by a subscription. Codex CLI records have no reported monetary
amount; absence stays unknown. An explicitly supplied zero stays zero.

For captured usage, the screen shows the known subtotal and its record coverage.
A known subtotal over the limit raises an alert even if other amounts are missing.
A linear month projection requires an administrator's coverage declaration,
at least one elapsed day, priced records, complete API attempt costs, and no
known retention or current collector gap. It describes the captured pace,
not a verified future bill. A source heartbeat alone does not establish coverage.

Allocated budgets use whole-month cost pools without extrapolating a daily rate.
The administrator confirms that the relevant monthly pools are entered.
An absent pool is unknown, not free service.

**Operations** and the Prometheus rules expose current-month non-fictional budget
breaches and warnings. Connect Prometheus rules to your existing Alertmanager
destination. These features do not send messages themselves or block model calls.

## Allocate a subscription or shared expense

Open **Create or revise a cost pool**. Enter the month, amount, category,
stable reference, reason, and project weights; preview before saving.
For example, a declared USD 30 subscription with weights `engineering=2` and
`support=1` allocates USD 20 and USD 10 respectively.

The split conserves the entered total at nine decimal places. Equal remainders
use project-name ordering. Decimal strings are required in JSON; numeric floats,
negative amounts, non-finite values and unsupported precision are rejected.
This initial workflow distributes nonnegative pools; it does not import invoice
credits. Billing reconciliation retains its separate signed adjustment support.

Revising the same reference, month and evidence type creates a new immutable
revision. An unchanged replay is deduplicated. A stale edit is rejected so one
administrator cannot silently overwrite another. **Void cost pool** excludes its
current allocation; its earlier revisions remain exportable until retention.
Use the original reference to correct an expense, rather than entering another
pool. This does not detect the same invoice entered under different references.

Company and fictional pools appear separately. Captured event payloads,
accounting, unknown per-call invoice costs and fingerprints are unchanged.
The allocation is an administrator's declaration, not invoice authentication
or a measured per-task subscription charge.

## Define checks for your own workload

Open **Custom evaluations**. Analysts and administrators can:

1. Create named cases with stable IDs, input context, checks and critical flags.
2. Save a suite revision and download its saved-answer template.
3. Fill the template with existing outputs, declared model labels, optional
   decimal costs and measured timings. Include the entire case cost, including
   failed attempts. Leave unmeasured amounts/timings `null`.
4. Upload the JSON and inspect every model/case result.
5. Compare two saved runs with the same suite revision, evaluator, model roster,
   cost basis and evidence type. Export the full evidence when needed.

Templates begin as `fixture`. Use `imported` for actual supplied outputs, while
recognizing that this is a source assertion. A fictional suite always produces
fictional results regardless of the answer file's label. **Try fictional cases**
prepares an editable example and makes no model calls.

Supported checks:

| Check | Contract |
| --- | --- |
| Exact text | Literal equality, including whitespace; optional case folding |
| Contains text | Nonempty literal substring, optionally ignoring case |
| Excludes text | Forbidden literal substring is absent |
| JSON object | Valid bounded JSON object, without duplicate keys or non-finite numbers |
| JSON field equals | JSON Pointer lookup with exact value and type equality |

For JSON field equality, use `/action` or `/items/0` as the pointer and a JSON
value such as `"escalate"`, `false`, or `0` as the expectation. Missing fields
do not equal `null`; booleans do not equal numbers; integer `1` and decimal `1.0`
are distinct. Long strings, nesting and rule counts are bounded.
Uploaded checks cannot contain executable code, regular expressions or model judges.

Each planned model is evaluated against **every case**, even when its answers
are absent. Missing cases and failed responses count as failures; critical cases
remain critical. An empty answer array records an entirely missing run.
Known failed-attempt costs remain in the total. Cost per passing case is unknown
unless every case has an amount and at least one passes. The displayed p95 uses
only supplied timings and includes the timing count.

This is a deterministic contract checker. It does not independently assess broad
answer quality, create representative datasets, attest provider models/costs,
or recommend and activate a route. Keep the existing support and sandboxed coding
evaluators for their richer, workload-specific acceptance contracts.

Limits are 100 cases per suite, 10 checks per case, 10 models and 1,000 answers
per run, and 2 MB per request. Lists show 25 items per page; case details are
paged. UI history shows the latest 25 revisions, with older retained revisions
available through the paginated history API. Run comparisons use the current
page's saved runs.
Each team supports up to 100 active definitions of each kind: budgets, cost pools
and suites. Archive or void unused definitions before adding more. Cost pools
support up to 100 project shares; project names match exactly, including case.

## Guided connection setup

Open **Usage sources**, create a supported source, then **Open setup guide**.
Set the collector's project. The guide provides source-specific commands and
four separate checks: source created, active connection token, collector
heartbeat/delivery, and observed records received. Fictional records cannot
complete the observed-record step.

Run generated commands from the matching Workbench checkout on the collector
host. Source tokens stay private. The helper below prompts without echo and
creates a new owner-only file; it refuses to replace an existing file:

```bash
uv run --locked python -m workbench.onboarding save-token --file .pilot/source.token
```

Use a fresh private filename when rotating a token, update the delivery process,
then revoke the old token using Usage sources. Keep each outbox and its identity.

Codex imports an existing CLI invocation with its original capture ID and start
time. Cursor imports a complete Admin API reporting window. Claude Code can import
existing OTLP/HTTP JSON logs or use a loopback receiver. Its optional
`workbench.onboarding claude-env` helper passes the receiver secret to the child
environment, with prompt/response/tool-content capture disabled; the helper does
not itself log in to an account. Running a normal vendor session can incur that
vendor's normal usage. No such session is started by the webpage.

AxonLLM and Bedrock guides point to their existing application capture wrappers.
Installation and coverage still depend on instrumenting the actual application.
The guide does not automatically discover credentials, connect vendor accounts,
or prove that every company tool is covered.
See [native connector contracts](CODING-TOOL-CONNECTORS.md),
[AxonLLM setup](PILOT.md), and [Bedrock capture](BEDROCK.md).

## Access, storage and retention

All reads and writes are scoped to the authenticated team. Viewers can inspect
and export; analysts can author custom evaluations; administrators also manage
budgets and allocations. Mutations require CSRF checks. Sensitive user-supplied
JSON is excluded from validation errors and operational logs.

Suite inputs and saved answers may contain confidential company information.
They are stored in the company's database and full evidence exports. List
responses use summaries rather than including raw case/answer payloads.
Use the deployment's encrypted storage, access control and backup policy.

The existing evidence-retention interval expires saved custom runs and obsolete
definition revisions in bounded batches. A retained run protects its referenced
suite revision. Active definitions retain their current revision as configuration,
including active declared cost pools. Archive suites/budgets or void pools to
allow their definitions to expire after the interval since their last edit.
Active definitions do not promise indefinite retention of every old revision.
Audit entries follow the independent audit-retention interval.

Budget exports freeze the policy revision and include a freshly calculated
status with its calculation time; they are not historical status snapshots.
Export evidence before its retention deadline when longer storage is required.

## Upgrade this development checkout to schema 6

1. Stop API, worker and maintenance writers; pause collectors.
2. Take and verify a restorable PostgreSQL backup and preserve matching previous
   images and private outboxes.
3. Install this checkout's locked dependencies or build its matching images.
4. Run the explicit migration with the target deployment's private configuration:

   ```bash
   uv run --locked python -m workbench.pilot migrate
   ```

5. Start matching services, verify readiness and original usage/billing totals,
   then exercise the new screens before resuming collectors.

Schema 6 adds scoped workflow definitions, immutable revisions and custom run
results. Migration from schema 5 creates these tables without rewriting prior
events, costs or facts. Repeating migration is safe. Upgrades from earlier
versions also apply their required migrations.
Older servers reject schema 6; rollback requires the pre-upgrade database backup
and matching old images. Never decrement the schema marker or mix service versions.
No hosted deployment is updated by building this branch.

## API entry points

Use the browser's authenticated company session and CSRF token; source ingestion
tokens cannot administer these workflows. No anonymous model-running endpoint
is introduced.

| Route under `/api/pilot` | Purpose |
| --- | --- |
| `GET/POST /spend/budgets`, `POST /spend/budgets/{id}` | List, create or revise a policy |
| `POST /spend/allocations/preview` | Validate and preview a declared pool |
| `GET/POST /spend/allocations`, `POST /spend/allocations/{id}` | List, save or revise pools |
| `GET /spend/summary?month=YYYY-MM` | Current non-fictional allocation totals |
| `GET /spend/{budget\|allocation}/{id}/history?page=0` | Retained revisions |
| `GET /spend/{budget\|allocation}/{id}/export?revision=N` | Download one revision |
| `GET/POST /custom-evals/suites`, `POST /custom-evals/suites/{id}` | Reusable definitions |
| `POST /custom-evals/suites/preview` | Validate an imported definition before editing |
| `GET /custom-evals/suites/{id}/template` | Download a saved-answer template |
| `GET /custom-evals/suites/{id}/history` or `/export` | Inspect retained suite revisions |
| `GET/POST /custom-evals/runs` | List summaries or evaluate saved answers |
| `GET /custom-evals/runs/{id}` or `/{id}/export` | Immutable detailed result |
| `GET /custom-evals/runs/{after}/compare/{before}` | Compatible run comparison |
| `GET /sources/{id}/setup?project=engineering` or `/setup/export` | Metadata-only setup guide |

Create/update requests for definitions use `{"value":{...},"revision":N}`:
`N=0` for a new reference, then the last saved revision for an edit.
The allocation preview uses the same definition wrapper.
