# AI Operations Workbench v0.1.0

The first release connects recorded model spending to task outcomes and a
reviewable model-routing decision.

## Explore the complete workflow

- Connect the bundled recording or import a compatible Workbench JSON recording.
- Inspect the most expensive baseline task, both model calls, token usage, and
  recorded latency.
- Replay decision checks and actual Ostiari Guard controls locally.
- Compare cost per passing task, critical failures, and task p95.
- Tune acceptance criteria and export the evidence and routing proposal.

The interface uses the AxonLLM/Ostiari light product theme, with blue usage,
yellow inspection, violet comparison, and teal review stages. It supports
desktop and mobile layouts, keyboard navigation, and pausable solid-circle
workflow animation.

## Evidence included

The source contains 144 actual recorded model API calls across 24 fictional
support cases and three model snapshots. Case pass counts are 20/24, 18/24,
and 14/24. Each model has one critical decision failure.

At the default thresholds, **no model qualifies**. The release makes no savings
claim and never applies a production routing change.

The total estimated model API cost is **$0.088074750**, calculated from
provider-reported tokens and the saved rate card. It is not an invoice.
Hardware, electricity, subscriptions, and human review remain unmeasured.
Read [METHODOLOGY.md](METHODOLOGY.md) for definitions and limitations.

## Install and run

Download and extract the source archive, then from its root:

```bash
uv sync --locked --python 3.13
uv run --locked uvicorn workbench.app:app --host 127.0.0.1 --port 8767
```

Open `http://127.0.0.1:8767/`. Installation downloads public dependencies.
Exploration and replay require no API key and make no new model calls.

This release is distributed as source, not a PyPI package, container, or hosted
service. `SHA256SUMS` covers the attached source archive. Checksums detect a
changed download; they are not a digital signature or provenance attestation.

## Current limits

One run per model and 24 authored synthetic cases do not establish a general
model ranking or production savings. There are no native tool billing
connectors, company-wide spend history, authentication, or remote deployment.
Run on localhost and use fictional, non-sensitive data.

License: **MIT-0**.
