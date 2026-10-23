# AI Operations Workbench

**Follow the cost of an AI task, inspect its outcome, and compare models before changing a route.**

Workbench is a separate, runnable local product demonstration. Its first workflow is:

**Connect recorded usage → inspect an expensive support task → evaluate alternatives → export a justified routing proposal.**

It uses actual AxonLLM model calls and actual Ostiari Guard decisions. The bundled
evidence contains **144 recorded API calls across 24 synthetic cases and three models**.
You can explore and regrade that recording without an API key or new model charges.

## Run it

Requirements: Git and [uv](https://docs.astral.sh/uv/). Python 3.13 is the tested
runtime; `uv` can install it. Node is only needed for browser tests.

From this directory:

```bash
uv sync --locked --python 3.13
uv run --locked uvicorn workbench.app:app --host 127.0.0.1 --port 8767
```

Open **http://127.0.0.1:8767/**.

1. Choose **Connect recorded usage**, then **Connect recorded run**.
2. Select **Inspect this task** to see the two calls, their token usage, and cost.
3. Choose **Evaluate alternatives** to replay the saved outputs through the checks.
4. Open **Review routing proposal**. Tune the quality or latency requirements.
5. **Export evidence and proposal** downloads the original recording, assessments,
   model summaries, constraints, source hashes, and recommendation.

The bundled run recommends **no model** at the default thresholds. That is an
intentional result of the evidence: even the baseline fails the acceptance criteria.
There is no routing activation endpoint.

Dependencies download during installation. The browser workflow and evaluation
replay then run locally; they do not call a model provider.

## What is working

| Capability | Current implementation |
|---|---|
| Usage connection | Bundled AxonLLM recording or compatible JSON import |
| Ledger | Local SQLite; transactional imports and provider-event deduplication |
| Task inspection | Synthetic input, both requests and responses, token usage, API estimates, observed latency |
| Model evaluation | Deterministic decision checks across all saved cases; failures retained |
| Governance | Actual Ostiari Guard in the evaluation subprocess; draft permission and three blocked action controls |
| Model selection | Complete evidence, minimum pass rate, zero critical failures, p95 limit, then lowest cost per passing task |
| Review | Adjustable criteria and portable evidence export; no deployment |
| Interface | Navy/cyan/cream; desktop and mobile; small moving circles with pause and reduced-motion support |

**Not yet implemented:** native Codex, Cursor, Claude Code, or Bedrock billing
connectors; subscription invoice reconciliation; a coding workload; multi-company
authentication; or production routing changes. This is a support-workflow
demonstration, not a finished company-wide observability service.

## Recorded result

Collection date: **October 23, 2026**. Each model completed 24 tasks, with two
sequential API calls per task. “Pass” means the specific authored contract checks
passed, not general model accuracy.

| Model snapshot | Cases passed | Critical decision failures | Estimated API cost / task | Estimated API cost / passing task | Task p95 |
|---|---:|---:|---:|---:|---:|
| GPT-4.1 `2025-04-14` | 20/24 | 1 | $0.002906083 | $0.003487300 | 2.38 s |
| GPT-4.1 mini `2025-04-14` | 18/24 | 1 | $0.000552567 | $0.000736756 | 2.57 s |
| GPT-4o mini `2024-07-18` | 14/24 | 1 | $0.000211131 | $0.000361939 | 2.17 s |

Total API estimate for the main comparison: **$0.088074750**. This is reported
token usage multiplied by the saved public rate card, not a provider invoice.
Local external-tool API fees are **$0**. Hardware/electricity, subscriptions,
and human-review costs remain **unmeasured**.

At the default **95% pass rate, zero critical failures, and 20 s p95** thresholds,
none qualifies. In the stolen-account case, all three models selected identity
verification instead of the policy's higher-priority human review.

These are 24 authored synthetic examples and one run per model. They are not
production traffic, a representative benchmark, or statistically substantiated
savings. Read [the methodology](docs/METHODOLOGY.md) before interpreting them.

## Replay or collect evidence

Regrade the bundled recording locally:

```bash
uv run --locked python -m workbench.worker replay \
  data/model-comparison.json --output artifacts/analysis.json
```

A fresh collection makes paid API calls. Provide `OPENAI_API_KEY` through your
shell's secret manager, then explicitly run:

```bash
uv run --locked python -m workbench.worker collect \
  --output artifacts/my-comparison.json --budget-usd 1.00
```

The collector refuses to overwrite an existing recording or partial run. It
checks a conservative estimate against the supplied budget, allows at most $5
per run, disables retries, and checkpoints completed tasks. This estimate uses
the configured rate card; it is **not a provider-account billing limit**.
Choose a new output path for each run. A `--max-cases 1` smoke test is incomplete
evidence and cannot qualify a model for a proposal.

Import a fresh result using **Connect usage → Choose a recording**. Imports must
match this version's workload and prices. Structure, requests, and cost arithmetic
are checked; an imported file's claimed provider provenance is not independently
authenticated. Do not import sensitive customer content into this unauthenticated
local demonstration.

## Verification

```bash
uv run --locked pytest -q
```

Browser checks require Node 22 or newer:

```bash
npm ci
npx playwright install chromium
npm test
```

Browser tests use a separate temporary ledger and port 18769. Set
`WORKBENCH_TEST_PORT` if that port is occupied. They cover the full journey,
cost deduplication, proposal export and threshold changes, animation controls,
mobile layouts, and invalid imports.

Local state lives in `.state/`; generated reports and screenshots go in
`artifacts/`. Both are ignored by Git. To use a fresh workspace without deleting
anything:

```bash
WORKBENCH_STATE_DIR=/tmp/workbench-new-demo \
  uv run --locked uvicorn workbench.app:app --host 127.0.0.1 --port 8767
```

Evaluation results are cached for the running server. After restarting, connected
recordings persist and you can replay their checks again.

## Design and next steps

- [Methodology and result interpretation](docs/METHODOLOGY.md)
- [Component boundaries, data flow, and current limitations](docs/ARCHITECTURE.md)
- [Product direction and staged roadmap](docs/ROADMAP.md)
- [MIT-0 license](LICENSE)

AxonLLM and Ostiari are pinned to immutable Git revisions in `pyproject.toml` and
`uv.lock`. They remain separate projects; this app does not patch their source.
