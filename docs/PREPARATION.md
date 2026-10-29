# Prepare real billing and coding comparisons

These operator tools create reviewable packets without contacting AWS or model
providers. They preserve missing inputs as missing; a preparation packet is not
an acceptance receipt or a model ranking. Keep generated files outside Git.

## Billing handoff

```sh
uv sync --locked --python 3.13
uv run --locked python -m workbench.billing_prepare create --directory .pilot/billing-acceptance
```

The new owner-only directory contains acceptance and collection configurations,
review attestations, instructions, and a readiness report. Account, month, bucket,
team, independent control totals, reviewer, CSV parts and reconciliation are
initially absent. The generator refuses to overwrite an existing directory.

The billing owner supplies a complete export generation and calculates signed
totals independently. The application owner supplies captured-call counts and
saved estimates from an independent run log. Import and map the reviewed scope,
then download the reconciliation JSON beside the private source CSV files.
Confirm origin, completeness, independence and capture scope in `review.json`.

```sh
uv run --locked python -m workbench.billing_prepare check --directory .pilot/billing-acceptance
uv run --locked python -m workbench.billing_acceptance \
  --config .pilot/billing-acceptance/acceptance.json \
  --output .pilot/billing-acceptance/receipt.json
```

The readiness command exits 2 for missing inputs. It checks configuration shape,
bounded local files, imported evidence and attestations; the second command
performs exact financial and snapshot checks. Neither command authenticates an
invoice or proves complete instrumented capture.

For scheduled delivery, fill `collection.json` and follow
[the collector guide](BILLING-COLLECTION.md). Its dry-run **reads S3**.
Observe initial delivery, an exact replay, a newer complete replacement, and a
controlled failure/recovery in an isolated customer test workspace. Record these
observations in the last two review fields and retain delivery receipts.
Offline readiness deliberately keeps scheduled-delivery acceptance pending.
The scheduler supports bounded versioned Legacy CUR CSV/gzip assemblies; CUR 2.0
automated exports and larger multi-account reports need additional work.

## Larger coding calibration packet

```sh
docker pull python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741
uv run --locked python -m workbench.coding_prepare \
  --image python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741 \
  --output-dir .pilot/coding-calibration
```

The packet has **18 distinct authored Python tasks**, including dependency ordering,
stable pagination, UTC billing boundaries, credit preservation and exact cent
allocation. It combines the six existing demonstration tasks with 12 additions.
Each broken implementation must fail at least one check and each reference must
pass every check inside a disposable network-disabled Docker container.

Defaults prepare three candidate slots × three repetitions × 18 tasks:
**162 planned task runs**, up to two attempts each. Task/repetition blocks are
shuffled reproducibly; candidate order rotates to distribute position effects.
Repetitions measure stability, not additional independent tasks.

The packet contains:

- `plan.json`: frozen dataset hash, schedule, unset candidate models and budget.
- `prompts.json`: broken code, instructions and public tests only.
- `operator-dataset.json`: references and acceptance tests for the operator.
- `baseline-check.json`: measured container outcomes when `--image` is supplied.

Acceptance tests are omitted from prompts but published in this repository.
These are calibration tasks, **not a private holdout or representative coding
benchmark**. Before a publishable comparison, freeze additional representative
private tasks, exact model versions, dated pricing, a collection adapter, budget,
retry/time limits and reviewer rubric. Keep failures and every attempt in the
denominator; report cost completeness, cost per accepted patch, regressions,
per-task paired outcomes and uncertainty across distinct tasks. Report human
review separately. Hardware/electricity stays unmeasured.

The packet itself contains no model results. The
[recorder and result viewer](CODING-EVALS.md) support its frozen dataset through
version 2 recordings. Pass `--dataset`, `--repetitions`, and `--seed` to collect
the full schedule, then replay the recording before importing the result.
The bounded six-task collector remains available
after credentials, exact model choice and spending authorization are supplied.
