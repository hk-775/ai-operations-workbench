# Coding tasks: cost per accepted patch

This separate workload asks whether a candidate fixes a known bug and preserves
existing behavior. It does not relabel the support recording as coding evidence.
Open **Coding evaluations** in the authenticated application to inspect the
bundled result or preview a private result file. Previews are read-only, not
stored in the company database, and clear on sign-out.

## Run the reproducible demonstration

The dataset contains six small Python functions: precise charges, exclusive
billing windows, source-scoped deduplication, bounded retries, qualified routing,
and credential-header redaction. Each includes a broken source snapshot, public
tests, acceptance tests, and a reference repair. Both broken and reference
baselines must behave as expected before any candidate result is accepted.

```sh
uv sync --locked
docker pull python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741
uv run --locked python -m workbench.coding evaluate \
  --image python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741 \
  --output .pilot/coding/example-result.json
```

Load that JSON using **Preview a coding result**. The sample candidate patches,
tokens, API estimates, and model latency are **authored fixtures**. Docker test
outcomes and replay duration are actually measured. Replaying makes zero model
calls. The three teaching candidates show why cost per attempt can be misleading:

| Authored candidate | Accepted / tasks | Attempts | Fictional API estimate | Fictional API cost / accepted patch |
|---|---:|---:|---:|---:|
| example-fast | 2 / 6 | 6 | 0.012 | 0.006 |
| example-repair | 6 / 6 | 12 | 0.024 | 0.004 |
| example-careful | 6 / 6 | 6 | 0.030 | 0.005 |

These are teaching values, not model rankings or measured model costs.

## Collect actual model patches explicitly

The separate recorder uses the existing pinned AxonLLM OpenAI router and model
configuration. It sends the same broken snapshots/public tests to every selected
model, permits bounded repair attempts, disables router retries, and records
token usage, saved API estimates, patches, and actual end-to-end task duration.
Public test feedback can trigger repair; acceptance tests are withheld until
offline evaluation. A cheaper patch is useful only if the task ultimately passes.

Set `OPENAI_API_KEY` privately on your execution host. Review the bundled dated
price configuration and account/model availability before a paid run. This
command requires explicit consent and a configured-price budget:

```sh
uv run --locked python -m workbench.coding_collect \
  --model gpt-4o-mini-2024-07-18 \
  --budget-usd 1 --max-attempts 2 --allow-model-calls \
  --image python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741 \
  --output .pilot/coding/model-recording.json
uv run --locked python -m workbench.coding evaluate \
  --recording .pilot/coding/model-recording.json \
  --image python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741 \
  --output .pilot/coding/model-result.json
```

Repeat `--model` with other IDs supported by `--help` for a common-case comparison.
The conservative envelope reserves 12,000 input and 1,024 output tokens per
permitted call before dispatch. Budget values must be positive and at most USD 5.
This bounds the configured-price plan, not an AWS/OpenAI invoice. Provider errors
without usage keep cost unknown. Every in-flight call is written to an owner-only
partial recording before dispatch; interrupted recordings are incomplete evidence.
Output paths cannot overwrite prior recordings.

The existing router uses Chat Completions for its configured non-reasoning
models. OpenAI's [request and usage reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
documents token limits and usage fields; its legacy `max_tokens` parameter is
not suitable for arbitrary reasoning models. Adding models/providers requires
reviewing the router contract, rates, usage categories and budget assumptions.
No paid model calls were made to verify this milestone.

## Contract and accounting

Generate candidate inputs without acceptance tests or reference repairs:

```sh
uv run --locked python -m workbench.coding prompts \
  --output .pilot/coding/prompts.json
```

Other recording producers can use `workbench.coding.recording.v1`, illustrated
in [the authored recording](../data/coding/example-recording.json). Keep
`mode: recorded` separate from fixture data; declare provenance, each call's
stable identity, estimates or unknown costs, latency, final source replacement,
attempt sequence, and optional original end-to-end duration. Repetitions are
explicit. This is an artifact interface, not a native Codex/Cursor/Claude Code
subscription connector.

Only `solution.py` can change. Each attempt starts from the frozen case snapshot.
The last submitted patch determines acceptance; an earlier pass cannot hide a
broken final patch. Regressions are checks that passed in the broken baseline
and fail after the patch. All submitted API estimates, including external-tool
API amounts, repair attempts and failed tasks, contribute to cost per accepted
patch. If any relevant cost is unknown, that measure stays unknown.

Model latency comes from the recording. Test duration is measured separately
during replay. Actual end-to-end duration is present only when the recording
producer measured it; replay never invents it by adding unrelated clocks.
Hardware/electricity remain unmeasured. API calls made by the replay itself cost
zero because there are none. Human review remains unmeasured unless supplied.

## Execution boundary and evidence limits

The operator CLI resolves a locally installed Python image to its immutable image
ID. Each attempt uses a disposable container with no network, read-only root/source,
non-root UID, no capabilities, no host secrets or Docker socket mount, a bounded
temporary filesystem, 128 MB memory, one CPU, 32 processes, eight-second timeout,
and 100 KB captured-output limit. Hidden inputs are passed only during grading;
expected outputs stay in the host grader. Candidate exceptions do not expose logs
or host paths in results. Timeout/output overflow fails the attempt and removes
the container. The web server never executes imported patches.

Use a dedicated disposable Docker execution environment for untrusted candidates.
These controls are a local demonstration boundary, not a certified hostile-code
multi-tenant sandbox. No arbitrary repository checkout, dependencies, shell tools,
internet access, or credential forwarding is supported.

Hashes bind dataset, recording, source patch, evaluator file and result. The
viewer validates identity and accounting, but cannot independently authenticate
the recording or executor. The six authored tasks and public acceptance tests
are not a secret held-out dataset or sufficient for a publishable model ranking.
For customer decisions, use a separate representative dataset, repeated runs,
independent review and customer-specific acceptance thresholds.
