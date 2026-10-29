# Codex, Cursor and Claude Code usage

Version 0.8.0 adds three core coding-tool connectors, included in the source archive.
Each uses an existing scoped Workbench source
token, a private durable outbox, retryable delivery, and collector heartbeats.
The browser does not log in to your vendor account or start model calls.

| Connector | Supported input | What one record represents | Available cost |
|---|---|---|---|
| Codex | Documented `codex exec --json` stream or saved JSONL | One completed, failed or interrupted turn | Unknown; the output has no monetary amount |
| Claude Code | OTLP/HTTP JSON logs, live or exported | An API response or API error | Tool-reported model estimate when supplied |
| Cursor | Team Admin API `filtered-usage-events`, or a complete JSON export | A vendor usage record; conversation grouping when supplied | Model amount and `chargedCents`, separately |

This does not scrape private Codex/Claude transcripts or Cursor databases.
Codex desktop/interactive telemetry, Cursor individual-account CSVs, OTLP
protobuf/gRPC, cumulative metrics, and automatic subscription allocation are
outside this first connector contract. Cursor API availability depends on the
account's administrator access.

## What is retained

Only allowlisted metadata reaches the outbox: tool and model labels, project,
opaque task/session identifiers, native token categories, available source
timestamps/duration, evidence type, and reported USD amounts. Identifier
pseudonyms use an outbox-specific HMAC key; retain that outbox during upgrades
and token rotation. Claude user emails are discarded. Cursor emails are used
only to derive stable pseudonyms and are never stored.
Back up the outbox. If it is lost, restore it before replaying old inputs:
creating a new outbox changes pseudonyms and can duplicate previously delivered
usage in the same Workbench source.

Prompt/response text, generated code, tool arguments/output, request bodies,
headers, vendor credentials, private error messages, and arbitrary telemetry
attributes are discarded. Input exports may already contain those values;
keep original files private and outside Git. Incoming source metadata is an
assertion from that source, not independently attested vendor evidence.

Three cost bases stay separate:

- **Estimated API spend:** existing server-priced AxonLLM/Bedrock usage.
- **Tool-reported model amount:** Claude's reported estimate or Cursor's model
  amount. It is not the cost allocated from a paid subscription.
- **Cursor-reported usage amount:** `chargedCents / 100`, including any vendor
  fee already in that field. Never substitute `requestsCosts`, add the model
  amount again, or infer actual cash payment from `isChargeable`.

Missing amounts remain unknown. An explicitly reported zero is retained.
Currency is USD for these documented fields. Decimal amounts use Workbench's
nine-place precision; unsupported precision is rejected. Claude's integer
microdollar field takes precedence when present. API invoice allocation,
subscription allocation, hardware/electricity and human review remain unknown.
Operations counts native coding-tool records separately. Its missing-API-price
alert covers AxonLLM and Bedrock calls; an unknown subscription allocation does
not trigger a failed-pricing alert.

Codex input includes cache-read tokens; Claude input excludes cache read/write.
Cursor's categories are retained as vendor-defined. Missing cache categories
are not replaced by zero. A coding-tool record does not prove one API attempt,
complete session coverage, an accepted patch, or output quality.

## Common setup and delivery

1. In **Usage sources**, create a Codex, Claude Code or Cursor source.
2. Issue a source token and save it in an owner-only file on the collector host.
3. Use one outbox per tool, project, vendor workspace and evidence mode.
4. Configure the relevant native collector below.
5. Run the existing delivery process with that same outbox:

```sh
uv sync --locked --python 3.13
export WORKBENCH_INGEST_URL=https://YOUR_WORKBENCH/api/pilot/ingest
export WORKBENCH_INGEST_TOKEN_FILE=/private/path/workbench-source-token
uv run --locked python -m workbench.connector \
  --outbox .pilot/codex.outbox.db deliver --watch
```

Replace the outbox filename for Claude Code or Cursor. Delivery is HTTPS except
on loopback. It checks the destination/source identity and leaves unacknowledged
events queued after failures. A token for one tool cannot ingest another tool's
records. Creating a source does not configure the vendor or prove capture.
Heartbeats prove the delivery process is running, not that every tool session
is being captured.

## Codex: documented turn output

Pass the JSONL output from an existing invocation to the metadata reader.
Use a unique `--capture-id` per invocation and retain it, the configured model
label and start time when replaying that same capture:

```sh
uv run --locked python -m workbench.coding_tools \
  --project engineering --outbox .pilot/codex.outbox.db codex \
  --input /private/path/codex-run.jsonl \
  --capture-id YOUR_UNIQUE_INVOCATION_ID \
  --started-at 2026-10-28T12:00:00Z \
  --model YOUR_CONFIGURED_MODEL
```

Use `--input -` to read stdin, for example after an explicitly chosen
`codex exec --json` invocation. That Codex command does its normal work and may
consume paid usage; Workbench's reader only collects metadata. Keep delivery
running separately to receive completed turns while a stream is still open.

The model name is a configured label because this JSON format does not attest
the response model. The timestamp is the retained invocation start; individual
turn durations are unmeasured. Do not use it as a per-request latency benchmark.
An unfinished turn at end of input is recorded as interrupted with unknown usage
and cost. Malformed input stops capture, preserving already queued completed
turns. Replaying different content under an existing event identity is rejected.

## Claude Code: native telemetry

Create an owner-only local receiver token without printing it:

```sh
uv run --locked python -c \
  'import os,secrets; from pathlib import Path; os.umask(0o077); p=Path(".pilot/claude-otel-token"); p.parent.mkdir(exist_ok=True); p.open("x").write(secrets.token_urlsafe(32))'
uv run --locked python -m workbench.coding_tools \
  --project engineering --outbox .pilot/claude.outbox.db claude-listen \
  --port 14318 --token-file .pilot/claude-otel-token
```

Configure the environment that launches Claude Code:

```sh
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_LOGS_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=none
export OTEL_TRACES_EXPORTER=none
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:14318/v1/logs
# Load the receiver token privately into YOUR_LOCAL_TELEMETRY_TOKEN.
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="Authorization=Bearer ${YOUR_LOCAL_TELEMETRY_TOKEN}"
export OTEL_LOG_USER_PROMPTS=0
export OTEL_LOG_ASSISTANT_RESPONSES=0
export OTEL_LOG_TOOL_DETAILS=0
export OTEL_LOG_TOOL_CONTENT=0
unset OTEL_LOG_RAW_API_BODIES
```

Set this at launch or through the vendor's supported administrator settings.
Existing managed settings can take precedence; this tool does not rewrite them.
The receiver binds only to `127.0.0.1`, requires its own token, accepts JSON only,
rejects browser-origin requests, and disables access logging. It persists only
API response/error metadata. All other log events, including bodies and tool
activity, are ignored. Metrics are not summed with logs.

A batch must validate and persist completely before acknowledgment. Source
timestamps and correlation metadata make exporter retries replayable. API errors
retain unknown token/cost values. Session IDs group events; when `prompt.id` is
present, requests for that prompt share a task. This does not assert that retries
or all sessions were exported.

For a saved OTLP JSON request:

```sh
uv run --locked python -m workbench.coding_tools \
  --project engineering --outbox .pilot/claude.outbox.db claude-import \
  --input /private/path/claude-otel.json
```

Supported bounds: 8 MB per OTLP JSON request, 1,000 log records per batch,
scalar usage attributes, no compression. Unsupported transports receive a
clear rejection. Receiver disk failures are retryable; invalid metadata requires
operator inspection.

## Cursor: complete, frozen reporting windows

Cursor documents delayed, hourly refreshed API data. Poll at most hourly and
prefer closed periods that have had time to settle. This connector does not
claim real-time Cursor accounting.

Save your own Cursor Admin API key in an owner-only regular file. Fetch one
closed window explicitly; `--start` is inclusive and `--before` exclusive:

```sh
uv run --locked python -m workbench.coding_tools \
  --project engineering --outbox .pilot/cursor.outbox.db cursor-fetch \
  --api-key-file /private/path/cursor-admin-key \
  --start 2026-10-28T00:00:00Z --before 2026-10-29T00:00:00Z
```

The collector converts the exclusive boundary to the final included millisecond
for Cursor's inclusive API bounds. It uses the fixed HTTPS vendor endpoint,
does not follow credential redirects, validates pagination/period/counts,
and commits only after fetching every page. No raw API response or key is saved.
Limits are 31 days, 20 pages, 1,000 rows per page and 20,000 records per window.
Choose smaller **non-overlapping** windows when needed.

An exported snapshot must contain all `usageEvents`,
`totalUsageEventsCount`, and the matching `period.startDate/endDate`:

```sh
uv run --locked python -m workbench.coding_tools \
  --project engineering --outbox .pilot/cursor.outbox.db cursor-import \
  --input /private/path/cursor-complete-window.json \
  --start 2026-10-28T00:00:00Z --before 2026-10-29T00:00:00Z
```

Identical replay is safe. Overlapping windows or changed previously imported
windows are rejected. The API does not supply a stable usage-event ID in this
contract, so the collector preserves identical-row multiplicity and detects
conflicts; it cannot independently certify the vendor's pagination snapshot.
Late corrections require reconciliation/review. Do not create another source
to append a corrected overlapping window: that would count the same usage twice.
Automatic correction/replacement is a future extension.

## Try authored examples without vendor access

All files in [the sample directory](../data/coding-tools/README.md) are fictional.
Use `--fixture` so they remain excluded from normal totals:

```sh
uv run --locked python -m workbench.coding_tools --fixture \
  --project coding-example --outbox .pilot/codex-example.db codex \
  --input data/coding-tools/codex.jsonl --capture-id authored-example \
  --started-at 2026-10-28T12:00:00Z --model configured-codex-model
uv run --locked python -m workbench.coding_tools --fixture \
  --project coding-example --outbox .pilot/claude-example.db claude-import \
  --input data/coding-tools/claude-otel.json
uv run --locked python -m workbench.coding_tools --fixture \
  --project coding-example --outbox .pilot/cursor-example.db cursor-import \
  --input data/coding-tools/cursor-usage.json \
  --start 2026-10-28T00:00:00Z --before 2026-10-29T00:00:00Z
```

Deliver each to its matching source. Select **Include synthetic test data**
in Usage overview. Inspect the separate amount cards and expand a coding
activity in Task explorer. No evaluation results or accepted patches are
inferred from these usage samples.

Database schema remains 4. Existing payloads, fingerprints, accounting, source
tokens and support/Bedrock behavior are preserved. Older servers will reject
the new source kinds; upgrade before connecting.

## Contract sources

Reviewed October 29, 2026. Version changes should be checked against these
official interfaces and new wire fixtures before expanding the adapters:

- [Codex non-interactive JSON output](https://developers.openai.com/codex/noninteractive)
- [Codex telemetry configuration](https://developers.openai.com/codex/config-advanced)
- [Claude Code monitoring and event attributes](https://code.claude.com/docs/en/monitoring-usage)
- [Cursor Admin API usage events](https://cursor.com/docs/account/teams/admin-api)
- [OTLP JSON protocol](https://opentelemetry.io/docs/specs/otlp/)
