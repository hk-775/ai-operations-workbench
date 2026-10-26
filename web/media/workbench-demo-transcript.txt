# AI Operations Workbench — narrated demo

Approximately four minutes. Stock synthetic narration: Amazon Polly neural, Joanna.
The video captures the actual local authenticated UI with fictional support cases,
saved model responses, and an isolated PostgreSQL workspace. No new model calls.
Architecture motion illustrates service relationships.

## 00:00:00 · Follow the cost. Prove the model choice.

AI operations starts with two questions. What did a task cost? And did it do the job well enough? Workbench brings those answers together before you change models. Let's follow a subscription-support task from captured usage to a justified routing review.

## 00:00:17 · Start clean, or explore saved evidence

A clean workspace starts without application data. The screen explains how to begin. For this walkthrough, we explicitly load the recorded support example. The cases are fictional, and the model responses were saved earlier. No new model calls are made during this demonstration.

## 00:00:36 · A task is more than one API call

The overview shows twenty-four tickets compared across three models: seventy-two task runs and one hundred forty-four captured calls. Their recorded API estimate is about nine cents. This is a saved comparison, not a company invoice. Missing prices stay unknown, and hardware and electricity remain unmeasured.

## 00:00:57 · Follow a refund request, step by step

Open the refund-inside-the-window task. Workbench shows the customer request and the calls behind it: classify the request, then draft the decision and reply. Each step has its captured cost. Call completed means the API returned successfully. Answer quality still needs evaluation.

## 00:01:18 · Connect application usage deliberately

For your own application, create an AxonLLM source and configure its scoped connector. A durable outbox retries unacknowledged usage. The feed contains metadata, while saved answers are imported separately for quality checks. The recorded example is clearly labeled as a saved source, not a live connection.

## 00:01:39 · A cheaper answer still has to pass

Now run the evaluation. Workbench replays saved answers against the subscription-support contract and real Ostiari Guard checks. It checks policy decisions and action boundaries. The worker continues in the background, and the result remains available after you leave the page.

## 00:01:58 · Compare quality alongside cost

The result compares tickets passed, critical failures, recorded response time, and cost per passing ticket. Money spent on failed tickets is included in that cost. These checks grade the saved responses. They do not establish today's model quality or performance on unrelated workloads.

## 00:02:17 · “No model qualifies” is a useful result

Set the requirements before looking for savings. With the saved strict criteria, no model qualifies. Workbench explains each exclusion instead of inventing a winning model. The next decision is to investigate the failing cases. Export the review with its evidence; no production route has been changed.

## 00:02:38 · See how the evidence moves

The interactive architecture connects the pieces. AxonLLM supplies captured calls. Workbench owns the ledger and review. The worker and Ostiari Guard evaluate saved evidence. Select a component or play a narrated flow. Small solid circles show the direction, with pause and reduced-motion controls.

## 00:03:00 · Keep the workspace operating

Administrators can inspect evaluation-service health, queued work, failed evaluations, and calls without a price. The recorded demo is not new application traffic, so these recent-traffic counts can be zero. Company operators configure retention, backups, monitoring, and their response process.

## 00:03:20 · Seeded and clean hosted test stacks

The optional AWS hosted test uses separate seeded and clean stacks, real Cognito sign-in, private CloudFront origins, encrypted off-host backups, and alarm receipts. Its architecture is interactive too. This is a single-host test, with an explicit no-MFA exception, not a high-availability production guarantee.

## 00:03:42 · Know the cost. Keep the proof.

Workbench makes one complete decision path visible: connect usage, inspect a task, evaluate saved answers, and review the model choice with evidence. Explore the source, run the recorded demo, and connect your own application when you are ready.
