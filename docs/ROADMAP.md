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

## 2. Coding-task demonstration

Add a reproducible **bug fix plus tests** workflow to address the Codex, Cursor,
and Claude Code customer conversations directly.

Each task should use an isolated repository snapshot with a known bug, a bounded
tool environment, hidden acceptance tests, and a recorded final patch. Measure
the entire task, including repair attempts and tool steps. Compare:

- Acceptance-test success and regressions.
- Model API usage and total observed task duration.
- Cost per accepted patch, including failed attempts.
- Human-review effort and compute costs when actually measured.

Do not replace the support recording or relabel it as coding evidence. A coding
adapter needs its own dataset, contract, artifact format, and integrity checks.

## 3. One authentic usage connector

Choose one source with reliable exported event IDs and usage semantics. Implement
and test that connector before advertising a multi-tool company dashboard.

The common event contract needs source, workspace/team, task/session, parent call,
provider and model, timestamps, reported usage, cost basis, currency, and stable
deduplication identity. Preserve whether money is **estimated**, **billed**,
**allocated from a subscription**, or **unknown**.

Add the remaining Codex, Cursor, Claude Code, and Bedrock sources only after
validating what their supported exports and APIs actually expose. Product names
in the roadmap do not imply working integrations.

## 4. Reconcile the bill and attribute outcomes

Consider AxonLLM Ledger for provider/cloud billing ingestion, then join its
financial records to the operational task events. Keep invoice reconciliation
separate from the pricing estimates already shown.

Decide how to attribute subscriptions, shared infrastructure, retries, caches,
human review, and incomplete traces. Unknown values must remain visible instead
of being converted to zero.

## 5. Production evidence and controlled changes

Add representative held-out workloads, repeated evaluation, independent review,
provenance and access control, persistence/retention, and observable job handling.

Only after that, design a reviewed rollout through AxonLLM/Ostiari with a
canary, rollback, and outcome monitoring. A proposal's projected API savings
should be compared with realized cost and quality after rollout.

The product can grow around these components without turning AxonLLM or Ostiari
into an unrelated company-wide dashboard.
