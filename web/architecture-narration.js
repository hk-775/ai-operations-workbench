'use strict';
// Authored narration; no runtime synthesis or cloud calls.
window.WorkbenchNarration = {
  "product-app": {
    "src": "media/narration/product-app.mp3",
    "duration": 18.264,
    "text": "The journey starts in your application. AxonLLM calls the model, and the Workbench connector captures usage in a durable outbox. Related calls share a task identifier. Captured usage tells us what happened, but a successful API call does not prove the answer was correct."
  },
  "product-ingest": {
    "src": "media/narration/product-ingest.mp3",
    "duration": 16.608,
    "text": "A scoped source token sends usage to Workbench. The server derives the team and source from that token, validates each batch, and acknowledges repeated events. A conflicting payload rolls back the batch. Prompt and answer text are separate from this metadata feed."
  },
  "product-ledger": {
    "src": "media/narration/product-ledger.mp3",
    "duration": 18.792,
    "text": "PostgreSQL preserves the usage ledger, historical price facts, saved evidence, jobs, results, and reviews. Known API estimates remain precise decimal amounts. Missing usage or unsupported prices stay unknown. These estimates are not reconciled provider invoices."
  },
  "product-recording": {
    "src": "media/narration/product-recording.mp3",
    "duration": 17.352,
    "text": "Quality evaluation starts with saved support answers. The bundled comparison contains twenty-four fictional subscription-support tickets and three models. Workbench validates the recording contract before replay. Application usage alone cannot establish answer quality."
  },
  "product-worker": {
    "src": "media/narration/product-worker.mp3",
    "duration": 17.496,
    "text": "An offline evaluation worker claims a persisted job and replays its recording. Work continues after the browser closes. Leases and ownership checks prevent stale workers from overwriting results. Replay grades saved responses; it makes no new model API calls."
  },
  "product-checks": {
    "src": "media/narration/product-checks.mp3",
    "duration": 18.072,
    "text": "Deterministic checks grade the support decision. The real Ostiari Guard package checks the configured action boundaries. Together they produce ticket passes, critical-case failures, and explanations. Workbench embeds Guard, not Ostiari's entire gateway or control plane."
  },
  "product-results": {
    "src": "media/narration/product-results.mp3",
    "duration": 17.136,
    "text": "Saved evaluation results stay linked to the original recording and evaluator revision. You can inspect pass counts, critical failures, recorded timing, and cost per passing ticket. These results describe this support workload, not a general ranking of model intelligence."
  },
  "product-review": {
    "src": "media/narration/product-review.mp3",
    "duration": 18.648,
    "text": "The routing review applies explicit requirements before comparing costs: a minimum pass rate, zero critical failures, and a response-time limit. It returns a justified candidate, or says no model qualifies. Projected savings require complete evidence and are not guaranteed savings."
  },
  "product-dashboard": {
    "src": "media/narration/product-dashboard.mp3",
    "duration": 14.952,
    "text": "The team dashboard connects task costs, evaluation results, and saved routing reviews. People see the views allowed by their role and can export supporting evidence. Workbench explains a model choice; it does not activate a production route."
  },
  "aws-browser": {
    "src": "media/narration/aws-browser.mp3",
    "duration": 16.848,
    "text": "The hosted test has separate HTTPS origins and browser cookie namespaces for the seeded and clean workspaces. A sign-in to the demo does not create an authenticated clean-workspace session. This diagram illustrates the deployment and sends no live requests."
  },
  "aws-edge": {
    "src": "media/narration/aws-edge.mp3",
    "duration": 18.144,
    "text": "CloudFront provides HTTPS and forwards requests to a private origin in the VPC. Caching is disabled, and AWS WAF applies an IP request-rate limit. HTTPS ends at CloudFront. The private origin and container hops use HTTP."
  },
  "aws-identity": {
    "src": "media/narration/aws-identity.mp3",
    "duration": 17.784,
    "text": "Amazon Cognito provides real sign-in with a separate application client for each workspace. Exact provider identities map to Workbench roles. Password-only sign-in is an explicit hosted-test exception. Standard production configuration retains its MFA requirement."
  },
  "aws-proxy": {
    "src": "media/narration/aws-proxy.mp3",
    "duration": 14.76,
    "text": "Inside the host, Caddy routes each hostname to the appropriate application listener. The two workspaces keep separate application state and cookies. They still share one EC2 host, so this test does not demonstrate high availability."
  },
  "aws-demo": {
    "src": "media/narration/aws-demo.mp3",
    "duration": 16.92,
    "text": "The seeded workspace has its own API, evaluation worker, maintenance process, and PostgreSQL database. Explicit seeding loads the saved support comparison, its evaluation, and a review. The tickets are fictional, and replay makes no new model calls."
  },
  "aws-clean": {
    "src": "media/narration/aws-clean.mp3",
    "duration": 17.472,
    "text": "The clean workspace starts without example evidence. It has separate credentials, database, identity-provider client, origin, and browser cookies. Companies then connect their own usage and upload compatible evidence. The shared host remains a common failure boundary."
  },
  "aws-timers": {
    "src": "media/narration/aws-timers.mp3",
    "duration": 16.68,
    "text": "Host timers run daily database backups and minutely monitoring. Protected jobs use temporary AWS credentials from the host role. Acceptance exercised the actual scheduled jobs. Stopping the host suspends the applications and their backup jobs."
  },
  "aws-backup": {
    "src": "media/narration/aws-backup.mp3",
    "duration": 18.624,
    "text": "Private, encrypted, versioned backups are stored in Amazon S3. Acceptance downloaded both scheduled backups, verified their checksums, and restored them into temporary databases. Backups expire after thirty days. This did not establish recovery on a newly built host."
  },
  "aws-monitor": {
    "src": "media/narration/aws-monitor.mp3",
    "duration": 16.152,
    "text": "CloudWatch monitors readiness and backup age for each workspace. Missing metric samples also alarm. A controlled demo-worker outage produced an alarm, followed by a recovery notification. Those signals still need an operational response process."
  },
  "aws-alerts": {
    "src": "media/narration/aws-alerts.mp3",
    "duration": 16.872,
    "text": "CloudWatch notifications pass through an encrypted Amazon SNS topic to a private SQS queue. The test verified delivery of outage and recovery receipts. No person receives these test notifications. Human on-call delivery remains an operator choice."
  },
  "scene-intro": {
    "src": "media/narration/scene-intro.mp3",
    "duration": 16.656,
    "text": "AI operations starts with two questions. What did a task cost? And did it do the job well enough? Workbench brings those answers together before you change models. Let's follow a subscription-support task from captured usage to a justified routing review."
  },
  "scene-clean": {
    "src": "media/narration/scene-clean.mp3",
    "duration": 18.072,
    "text": "A clean workspace starts without application data. The screen explains how to begin. For this walkthrough, we explicitly load the recorded support example. The cases are fictional, and the model responses were saved earlier. No new model calls are made during this demonstration."
  },
  "scene-usage": {
    "src": "media/narration/scene-usage.mp3",
    "duration": 20.496,
    "text": "The overview shows twenty-four tickets compared across three models: seventy-two task runs and one hundred forty-four captured calls. Their recorded API estimate is about nine cents. This is a saved comparison, not a company invoice. Missing prices stay unknown, and hardware and electricity remain unmeasured."
  },
  "scene-task": {
    "src": "media/narration/scene-task.mp3",
    "duration": 19.368,
    "text": "Open the refund-inside-the-window task. Workbench shows the customer request and the calls behind it: classify the request, then draft the decision and reply. Each step has its captured cost. Call completed means the API returned successfully. Answer quality still needs evaluation."
  },
  "scene-sources": {
    "src": "media/narration/scene-sources.mp3",
    "duration": 20.808,
    "text": "For your own application, create an AxonLLM source and configure its scoped connector. A durable outbox retries unacknowledged usage. The feed contains metadata, while saved answers are imported separately for quality checks. The recorded example is clearly labeled as a saved source, not a live connection."
  },
  "scene-evaluate": {
    "src": "media/narration/scene-evaluate.mp3",
    "duration": 18.0,
    "text": "Now run the evaluation. Workbench replays saved answers against the subscription-support contract and real Ostiari Guard checks. It checks policy decisions and action boundaries. The worker continues in the background, and the result remains available after you leave the page."
  },
  "scene-results": {
    "src": "media/narration/scene-results.mp3",
    "duration": 18.432,
    "text": "The result compares tickets passed, critical failures, recorded response time, and cost per passing ticket. Money spent on failed tickets is included in that cost. These checks grade the saved responses. They do not establish today's model quality or performance on unrelated workloads."
  },
  "scene-review": {
    "src": "media/narration/scene-review.mp3",
    "duration": 19.488,
    "text": "Set the requirements before looking for savings. With the saved strict criteria, no model qualifies. Workbench explains each exclusion instead of inventing a winning model. The next decision is to investigate the failing cases. Export the review with its evidence; no production route has been changed."
  },
  "scene-architecture": {
    "src": "media/narration/scene-architecture.mp3",
    "duration": 21.264,
    "text": "The interactive architecture connects the pieces. AxonLLM supplies captured calls. Workbench owns the ledger and review. The worker and Ostiari Guard evaluate saved evidence. Select a component or play a narrated flow. Small solid circles show the direction, with pause and reduced-motion controls."
  },
  "scene-operations": {
    "src": "media/narration/scene-operations.mp3",
    "duration": 18.96,
    "text": "Administrators can inspect evaluation-service health, queued work, failed evaluations, and calls without a price. The recorded demo is not new application traffic, so these recent-traffic counts can be zero. Company operators configure retention, backups, monitoring, and their response process."
  },
  "scene-aws": {
    "src": "media/narration/scene-aws.mp3",
    "duration": 21.48,
    "text": "The optional AWS hosted test uses separate seeded and clean stacks, real Cognito sign-in, private CloudFront origins, encrypted off-host backups, and alarm receipts. Its architecture is interactive too. This is a single-host test, with an explicit no-MFA exception, not a high-availability production guarantee."
  },
  "scene-close": {
    "src": "media/narration/scene-close.mp3",
    "duration": 15.336,
    "text": "Workbench makes one complete decision path visible: connect usage, inspect a task, evaluate saved answers, and review the model choice with evidence. Explore the source, run the recorded demo, and connect your own application when you are ready."
  }
};
