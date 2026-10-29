# Recorded coding calibration: October 29, 2026

This run compares the cost of an accepted repair across **18 authored Python
tasks**, three pinned models, and three repetitions. It tests the complete
collection → isolated grading → result-preview workflow. It is a calibration
example, not a general coding leaderboard or a customer routing recommendation.
Open **Coding evaluations → Load recorded calibration** to inspect it without
making model calls or adding the example to company usage.

| Candidate snapshot | Accepted / runs | Model calls | Recorded API estimate | API estimate / accepted repair | Hardware and electricity |
|---|---:|---:|---:|---:|---|
| GPT-4.1 `2025-04-14` | 51 / 54 | 54 | $0.050872 | $0.0009974902 | Unmeasured |
| GPT-4.1 mini `2025-04-14` | 50 / 54 | 54 | $0.0094544 | $0.000189088 | Unmeasured |
| GPT-4o mini `2024-07-18` | 39 / 54 | 57 | $0.003672 | $0.0000941538 | Unmeasured |

Total: **162 task runs, 165 model calls, USD 0.0639984 in recorded API estimates**.
Every planned run has known recorded usage and cost; no final patch introduced
a detected regression. Estimates include failed tasks and repair attempts.
They are not provider invoice charges. Human review and hardware costs are
unmeasured. Offline replay makes zero model calls.

## What this demonstrates

Visible tests can provide false confidence. All three models failed the
incomplete-total task in all repetitions despite passing its public test.
The prompt requires Decimal arithmetic, fixed-point text, null propagation,
and an exact empty-input result. Its acceptance checks catch numeric-format
and precision mistakes that a simple example misses.

GPT-4.1 mini also failed one percentile run. GPT-4o mini failed the decimal-charge,
incomplete-total, percentile, qualified-routing and UTC-month tasks in all three
repetitions. Its extra repairs were triggered only by public test failures.
The saved histories show the actual patches and individual checks.

At a 100% acceptance requirement, **none qualifies**. Relaxing a threshold in the
viewer explores this dataset's tradeoff; it does not authorize a production
routing change. A one-run difference between two candidates is not evidence of
a general performance difference.

## Frozen protocol and evidence

- [Recorded model patches and usage](../data/coding/calibration-recording.json)
- [Independently replayed result](../data/coding/calibration-result.json)
- [Collector and replay commands](CODING-EVALS.md#run-the-larger-frozen-comparison)

The version 2 recording embeds the exact dataset and complete schedule. The seed
is `20261029`; task/repetition blocks are shuffled, with rotating candidate order.
Each candidate receives the broken source and public tests. Reference repairs
and acceptance inputs/answers are excluded from model prompts and repair feedback.
There are at most two attempts per run, temperature zero, 1,024 output tokens,
and no router retries.

All 76 reference checks passed, and broken baselines failed 41 checks, before
candidate results were evaluated. Docker replay uses the pinned Python image,
no network or secrets, bounded CPU/memory/output/time, and read-only source.
Hashes bind dataset, schedule, recording, patches, evaluator and result.
The viewer checks consistency; it cannot authenticate provider records or the
executor independently.

The configured OpenAI rates were checked against the official model/pricing
documentation before collection. The pinned snapshots match Workbench's earlier
model configuration; they are not a claim to be the latest available models.
The recording retains its pricebook hash and provider-reported token categories.

## A benchmark defect caught during review

An initial run exposed an underspecified requirement: the decimal task requested
exact text, while its grader rejected scientific notation. Numerically exact
scientific notation satisfied that original wording. The expanded prompt was
clarified to require fixed-point text, a new dataset hash was frozen, and the
**entire comparison** was rerun. The table above uses only the corrected run.
The original six-task fixture contract is retained for compatibility.

The original private run remains in the operational evidence. The first and
corrected comparisons together used USD 0.1273451 in recorded OpenAI estimates,
within the approved USD 5 limit. No results were selectively repaired or
substituted into the final comparison.

## Limits

Three repetitions of 18 tasks remain **18 distinct problems**. The authored
cases and acceptance tests are public, so this is not a secret holdout.
Small function repairs do not represent repository navigation, dependencies,
agent tools, multi-file changes, security review, or production maintenance.
Latency was measured sequentially on one execution setup; human effort and
infrastructure costs are not inferred from API prices.

Use a separately frozen, representative customer workload and independent review
before making model or routing decisions.
