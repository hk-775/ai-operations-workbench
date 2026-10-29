# Connect an Amazon Bedrock application

This connector attributes instrumented **boto3 Converse and ConverseStream**
calls to application tasks. It captures provider-reported token counts, client
duration, provider latency when present, SDK retry count and request ID.
Your existing application keeps the prompts and responses; Workbench receives
metadata only.

This is an application connector, not an account-wide AWS billing collector.
InvokeModel, Agents, AgentCore, Mantle, historical invocation logs and invoices
are outside its coverage. It does not prove answer quality.

## Upgrade an existing Workbench installation

Use the [current release](RELEASE-0.9.1.md), which includes this connector and
billing reconciliation. Current releases require **database schema 5**.
Stop capture, delivery, API, worker and maintenance,
take and verify your normal database backup, then run the explicit migration
with the deployment's existing private environment:

```bash
uv run --locked python -m workbench.pilot migrate
```

Restart all services from the same checkout/image. The earlier schema-3 migration
added collector heartbeats and the reviewed price snapshot; schema 4 added billing
storage, and schema 5 adds stable call pagination. Existing event payloads,
fingerprints, costs, evaluations and reviews are preserved. Migration is
idempotent. Resume collectors after readiness checks pass. Rollback requires
restoring the pre-upgrade database backup with matching previous services.
Do not change the version marker by hand. See [upgrade and cursor compatibility](REVIEW-FIXES.md).
Do not run migration with a different company's environment.

## 1. Create a source

In the authenticated workspace, open **Usage sources**. Select **Amazon Bedrock**,
name your application, create the source, and issue a token. Save the token in a
private file on the application host. Tokens are displayed once and expire after
30 days. Use one source for each logical application and one persistent outbox
per collector. Copies of the same outbox must not run on multiple hosts.

Use either this connector or the AxonLLM wrapper for a given model call.
Capturing it through both creates two source-scoped records; Workbench cannot
prove they are duplicates.

## 2. Run the no-charge example first

From this checkout:

```bash
uv sync --locked --extra bedrock
export WORKBENCH_INGEST_URL=http://127.0.0.1:8768/api/pilot/ingest
export WORKBENCH_INGEST_TOKEN_FILE="$PWD/.pilot/bedrock-token"

uv run --locked python scripts/bedrock_example.py \
  --outbox .pilot/bedrock-fixture.outbox.db
uv run --locked python -m workbench.connector \
  --outbox .pilot/bedrock-fixture.outbox.db deliver
```

Use your real HTTPS Workbench origin outside loopback, and save the source token
to the file before delivery. The example creates **two synthetic calls in one
task**, with synthetic counts and timings, and makes **zero model calls**. The
events are labeled `fixture` and excluded by default. In Usage overview, select
the new source and **Include synthetic test data**, then apply filters.
The synthetic token estimate is **$0.000129500**; it is not measured spending.
Repeating this example against the same source does not duplicate its events.

Use a separate source/outbox for real application traffic.

## 3. Capture your existing calls

Install the optional SDK in the application environment. Use AWS's normal
credential provider chain and your application's IAM role, not credentials
copied into Workbench. Reuse a `bedrock-runtime` client:

```python
from pathlib import Path
import boto3
from botocore.config import Config
from workbench.bedrock import capture_converse, capture_converse_stream
from workbench.connector import Outbox

client = boto3.Session(region_name="us-east-1").client(
    "bedrock-runtime",
    config=Config(
        retries={"total_max_attempts": 3, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=60,
    ),
)
outbox = Outbox(Path(".pilot/bedrock.outbox.db"))

response = capture_converse(
    client, outbox,
    task_id="support-run-001",
    project="support",
    stage="classify",
    modelId="amazon.nova-micro-v1:0",
    messages=messages,  # Your application's existing messages.
    inferenceConfig={"maxTokens": 256},
)

# Always use the context manager, including when breaking out early.
with capture_converse_stream(
    client, outbox,
    task_id="support-run-001",
    project="support",
    stage="draft",
    modelId="amazon.nova-micro-v1:0",
    messages=reply_messages,
    inferenceConfig={"maxTokens": 512},
) as stream:
    for event in stream:
        handle_in_your_application(event)
```

These wrappers perform your normal, billable model operations. Verify model
availability and access in the selected region. Scope the application's existing
IAM permissions to the chosen model or inference profile, using
`bedrock:InvokeModel` for Converse and `bedrock:InvokeModelWithResponseStream`
for streaming. Workbench's ingestion token grants no AWS permissions.

Use opaque, non-sensitive task/project/stage identifiers. Keep a task ID for all
stages of a run; use a new one when repeating the task. The connector generates
a fresh application event ID before each invocation. Provider IDs are correlation
only. All event IDs and metadata are validated before the billable operation.

Set `maxTokens` explicitly. Versioned managed prompt ARNs own their inference
configuration; the wrapper preserves that API behavior, but cannot price those
calls. Client duration includes SDK retries and, for streams, the application's
time spent consuming the stream. Provider latency is shown separately.

An optional bounded real example makes exactly two SDK calls, with SDK retries
disabled and at most 64 output tokens requested per call:

```bash
uv run --locked --extra bedrock python scripts/bedrock_example.py \
  --outbox .pilot/bedrock.outbox.db \
  --invoke --region us-east-1 --model amazon.nova-micro-v1:0
```

Add `--stream` to exercise streaming instead. This example can incur charges;
default operation without `--invoke` remains synthetic.

## 4. Supervise delivery and inspect health

Run this separate process on the application host:

```bash
uv run --locked python -m workbench.connector \
  --outbox .pilot/bedrock.outbox.db deliver --watch
```

Keep the outbox on a persistent private volume. The delivery process polls every
five seconds, sends at most 100 events per batch, and backs off failures up to
five minutes. It does not invoke or retry models. Source-scoped identical event
replays are acknowledged; changed payloads under the same ID reject the batch.
The outbox is bound to its Workbench destination and authenticated source.
Rotating a token for that source preserves the queue and collector identity.

**Usage sources** refreshes every 15 seconds:

| State | Meaning and next action |
| --- | --- |
| Active token required | Issue or rotate the token and restart delivery. |
| Health not reported | Start the supervised delivery process. |
| Connected | Delivery reported within three minutes; the application may be idle. |
| Delivery backlog | The last report includes pending events; check delivery and retries. |
| Collector stopped reporting | At least one collector missed the three-minute window; inspect its host. |

The Operations page flags stopped collectors and reported backlogs. Heartbeats
also feed the private `workbench_stale_usage_sources` and
`workbench_backlog_usage_sources` metrics and bundled Prometheus alert rules.
No company/source IDs appear in metric labels. Heartbeats
are independent of traffic: zero events does not imply a broken connection.
A heartbeat proves the sender is reachable, not that every application path is
instrumented. Queue counts are **last reported**; disconnected collectors can
have additional unknown backlog. Multiple collectors are tracked separately so
a healthy one cannot hide a stopped one.

`deliver` without `--watch` reports health once and exits. Its report becomes
stale after three minutes; use `--watch` for continuous collection. A
compatibility `--no-health` flag is available for old AxonLLM servers and provides
no heartbeat monitoring. Bedrock ingestion itself needs this upgraded server.

Inspect the local queue without sending anything:

```bash
uv run --locked python -m workbench.connector \
  --outbox .pilot/bedrock.outbox.db status
```

The local status includes its opaque collector ID, pending events, retries,
in-progress reservations and oldest pending timestamp. It contains no token or
response text. A source supports 100 collectors. After permanently stopping one,
check its remaining outbox before using the administrator's **Retire collector**
action. Its usage history stays intact. A retired process that runs again
reports itself again.

## Crash recovery and unknown costs

The wrapper reserves metadata durably before calling AWS and finalizes it after
the response. Disk write failures are surfaced to the application; they do not
silently discard accounting. An exception after a billable call must not trigger
a blind application retry: check the reservation/outbox first.

After a crash, **stop all capture processes for that outbox**, then run:

```bash
uv run --locked python -m workbench.connector \
  --outbox .pilot/bedrock.outbox.db recover-inflight
```

Recovery creates interrupted records with unknown usage, cost and duration. It
does not repeat a model call. A crash after enqueue but before reservation
cleanup does not create another record.

An early stream close, missing terminal metadata, SDK error or malformed usage
produces a visible incomplete record. Completed responses with
`RetryAttempts > 0` retain final-response usage and explicitly incomplete attempt
coverage: earlier retries may have consumed tokens. Missing retry metadata also
prevents a complete-attempt claim.

## Pricing and compatibility

`bedrock.usage.v1` is separate from legacy `axon.usage.v1`; existing Axon event
fingerprints stay unchanged. The authenticated source selects the accepted
schema. Neither schema accepts client-provided prices, team IDs, prompts or
response bodies.

Bedrock's input, output, total, cache-read and cache-write categories are retained
as reported, without applying OpenAI's cached-input subtraction. The initial
server rate card deliberately prices only **uncached direct Nova Micro,
us-east-1, standard performance, default service tier**:

| Unit | USD per million tokens |
| --- | ---: |
| Input | 0.035 |
| Output | 0.14 |

Verified October 27, 2026 against the AWS Price List, published October 16, with
terms effective October 1. `config/bedrock-prices.json` preserves the source URL,
AWS rate codes, original per-1K units and the conversion. Its 30-day review
deadline is a Workbench policy, not a guarantee that AWS prices remain fixed.
Calls outside the reviewed effective/review window are unknown.

Rates are selected by the exact model ID, source region, service tier,
performance and event date. Profiles/ARNs are never stripped or guessed.
Cached calls, guardrails and other additional features, other models/regions,
reserved/flex/priority tiers, and unreviewed dates remain **unknown**.
An operator can review and extend the server-owned snapshot, migrate to register
it, then restart services. Do not copy a rate to a different region/model without
checking that billing contract. Stored events are never automatically repriced.

All money is Decimal text in USD. Invoices and hardware/electricity remain
unmeasured. Estimates and partial known subtotals are not a reconciled bill.
Usage metadata does not make these tasks eligible for support-v1 evaluations.

## Verification

Tests use boto3's Stubber and synthetic streaming responses, authenticated
ingestion, SQLite and PostgreSQL, lost acknowledgments, token rotation/revocation,
source/team isolation, schema migration, and the real CLI delivery process in
browser tests. No paid model calls are part of automated verification.
See `tests/test_bedrock.py` and `tests/pilot-browser/bedrock.spec.js`.
This is SDK-contract and application integration evidence, not a measured live
AWS model run.

Primary references:

- [Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
- [ConverseStream API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html)
- [TokenUsage](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_TokenUsage.html)
- [AWS public price list used for the initial snapshot](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json)
