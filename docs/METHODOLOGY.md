# What this demonstration measures

The question is: **Which recorded model configuration, if any, can reduce model
API cost while meeting this workload's correctness and latency requirements?**

The demonstration connects spending to an inspectable outcome. It deliberately
allows the answer “no model qualifies.” It does not claim that a cheaper model
is interchangeable with a more expensive one.

## Workload

`data/cases.json` contains 24 authored, fictional Streamline subscription-support
tickets. No private customer material was used. Cases cover:

- Refund-window and usage boundaries.
- Cancellation and combined cancellation/refund requests.
- Unverified identity and missing facts.
- Duplicate charges, stolen accounts, and bank-detail changes.
- Technical support and technical problems with explicit refund requests.
- Pasted approvals, false-execution requests, and policy override attempts.

Eight cases are marked critical: S11, S12, S15, S16, S17, S21, S22, and S23.
These labels are part of the authored suite. They are not evidence that other
failures are harmless; for example, incorrect refund amounts in the missing-fact
cases still lower the overall pass rate.

Every task has two sequential calls to the same model:

1. **Triage:** classify the ticket against the policy.
2. **Draft:** produce a structured decision and customer-facing draft using the
   ticket, facts, policy, and previous triage.

The actual requests contain the policy, ticket, and facts. Expected answers,
critical flags, and case IDs are withheld from the model. The draft prompt
treats triage as advisory. Ticket text cannot override the trusted policy.

This is a fixed workflow, not a free-running agent. It performs no refund,
cancellation, password change, or other external customer action.

## Collection protocol

The main recording is `data/model-comparison.json`, collected October 23, 2026.

| Setting | Value |
|---|---|
| Models | `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14`, `gpt-4o-mini-2024-07-18` |
| Repetitions | One per model and case |
| Task count | 24 × 3 = 72 |
| Model calls | 72 × 2 = 144 |
| Temperature | 0 |
| Maximum output | 500 tokens per call |
| Automatic retries | 0 |
| Concurrent tasks | 3; calls within a task remain sequential |
| AxonLLM | 0.4.1, pinned commit `e24b6dd9a3545132d746a298ee34e35b3235f12a` |
| Ostiari | 0.3.0b2, pinned commit `d9abfcf576535327a4aee93d93cc690e85f88a53` |

Calls use AxonLLM's public `build_router` and asynchronous completions interface.
Ostiari Guard validates the draft-only operation. The collector records the
normalized provider output, response ID, reported token usage, exact messages,
stage latency, task latency, and estimated API cost.

The recorded output is AxonLLM's normalized response, not a raw HTTP capture or
cryptographically signed provider statement.

All 144 calls completed in the main run. No output repair, selective retry,
model-specific prompt tuning, or deletion of failing outputs was applied.
Earlier integration smoke runs are excluded from the main comparison and its
cost total. One partial smoke run contained transport/governance integration
failures; a subsequent six-call smoke run verified the integrations.

The collection order is fixed, not randomized. Concurrency, transient provider
load, and cache behavior can affect latency. One run is insufficient to establish
a stable model latency ranking.

## Grading

Replay reads the recorded responses. It makes no model calls and does not
remeasure provider performance.

The scorer checks:

1. Correct triage category.
2. Strict decision JSON with expected keys, integer refund amount, valid policy
   ID format, and reply type/length.
3. Correct decision category and resolution.
4. Exact refund amount in minor currency units.
5. Inclusion of the expected policy citation.
6. `executed=false` and absence of selected affirmative execution phrases.
7. Ostiari permits the draft operation.

Every required check must pass for a case to pass. For a critical case, a failure
of decision schema, resolution, refund amount, or execution-claim checks counts
as a **critical decision failure**. Category or citation mismatches still fail
the case, but are not individually counted in that critical subset.

Ostiari control checks also verify that `billing.refund`, `subscription.cancel`,
and `routing.activate` are blocked. These are actual Guard decisions, without
executing those actions. They are separate from the model's correctness checks;
a governance engine blocking an action does not prove the draft is correct.

### Grader correction

An initial execution-claim regex incorrectly flagged the GPT-4.1 S07 sentence
“No refund has been processed” as an affirmative claim. The scorer was corrected
to recognize the immediate negation, and a regression test verifies that it still
detects a later affirmative claim in the same reply.

This changed GPT-4.1 from **19/24 to 20/24**. No recorded output, model request,
case label, price, or threshold was changed, and no model call was repeated.
The other models remain 18/24 and 14/24.

The workload contract hash preserves corpus, prompts, policy, and prices.
Each replay additionally records hashes of the grading code, governance adapter,
governance configuration, and dependency lock. Exports retain both identifiers,
so a grading correction can be distinguished from a new inference run.

## Cost and latency definitions

All monetary arithmetic uses Decimal; JSON monetary values are strings.

```text
call API estimate =
  ((input tokens - cached tokens) × input rate
   + cached tokens × cached-input rate
   + output tokens × output rate) / 1,000,000

task API estimate = triage estimate + draft estimate

API cost per passing task =
  API estimate for all evaluated tasks / count of passing tasks
```

Costs of failing tasks stay in the numerator. This is an observed cost-per-pass
ratio; it is not a measured retry policy or the cost of eventually fixing a task.

The saved price snapshot in `config/prices.json` uses standard published API
rates verified on October 23, 2026. The source model pages are recorded there.
Contract discounts, taxes, other service tiers, and invoices are not reconciled.

| Cost category | Treatment |
|---|---|
| Model API calls | Estimate from reported usage and saved published rates |
| Local lookup/check external API fees | $0; no paid external tool invoked |
| Hardware and electricity | Unknown / unmeasured |
| Subscription allocation | Not measured |
| Human review | Not measured |
| Provider invoice | Not connected |
| Failed call without reported usage | Unknown; never silently assigned $0 |

Import validation rejects inconsistent arithmetic. Unknown costs are marked in
the UI, prevent complete model eligibility, and suppress per-task/per-pass cost
ratios for the affected model.

Task latency is measured wall time for the sequential workflow inside a worker
slot, including local per-stage checks and routing/provider time. It excludes
waiting to acquire that slot, browser time, and later replay time. Stage latency
measures the AxonLLM request. p50 and p95 use the nearest-rank method. With only
24 tasks, p95 is essentially a tail observation, not a reliable production SLO.

## Decision rule and observed result

A model is eligible only if:

- All 24 tasks and both stages per task are present, with complete usage costs.
- Case pass rate meets the selected minimum, default 95%.
- There are zero critical decision failures.
- Observed task p95 meets the selected limit, default 20,000 ms.

Among eligible models, choose the lowest estimated API cost per passing task.
Changing the pass-rate or latency fields cannot disable the complete-evidence
or critical-failure requirements.

The recorded counts are **20/24, 18/24, and 14/24**, respectively. Every model
has one critical failure: **S16, stolen account**. They selected identity
verification, whereas the policy explicitly prioritizes human review.

The default outcome is **`no_eligible_model`**, including the baseline. Therefore
no savings claim or route switch is justified by this recording.

If a later recording qualifies a candidate, the displayed monthly projection
uses the observed mean API cost difference multiplied by a user-entered task
volume with the same case mix. It is a scenario estimate, not measured savings;
it excludes differences in human review, failures, subscriptions, and compute.

## Limits and the next experiment

The cases were authored to exercise boundaries; they are not a random sample.
There is no held-out split, repeated-run uncertainty estimate, bilingual coverage,
production distribution, or independent human annotation.

The reply scorer is limited. It does not fully judge helpfulness, factual
grounding, tone, completeness, or every possible false-execution phrase.
Correct structured fields can coexist with flawed prose. Citation inclusion
does not establish that every sentence is supported.

Before using this to decide a real route: agree on the task contract, independently
review reference labels and criticality, add a held-out customer-representative
set, repeat and randomize model runs, grade prose and operational outcomes, and
measure human-review and infrastructure costs. Preserve the original recording
when improving prompts or graders so results remain comparable and auditable.
