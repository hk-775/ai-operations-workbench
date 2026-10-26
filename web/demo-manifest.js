'use strict';
window.WorkbenchDemo = {
  "duration": 238.767,
  "chapters": [
    {
      "id": "intro",
      "title": "Follow the cost. Prove the model choice.",
      "start": 0.0,
      "end": 17.533,
      "text": "AI operations starts with two questions. What did a task cost? And did it do the job well enough? Workbench brings those answers together before you change models. Let's follow a subscription-support task from captured usage to a justified routing review.",
      "chapter": "AI Operations Workbench",
      "color": "violet"
    },
    {
      "id": "clean",
      "title": "Start clean, or explore saved evidence",
      "start": 17.533,
      "end": 36.467,
      "text": "A clean workspace starts without application data. The screen explains how to begin. For this walkthrough, we explicitly load the recorded support example. The cases are fictional, and the model responses were saved earlier. No new model calls are made during this demonstration.",
      "chapter": "01 / Begin with evidence",
      "color": "sky"
    },
    {
      "id": "usage",
      "title": "A task is more than one API call",
      "start": 36.467,
      "end": 57.833,
      "text": "The overview shows twenty-four tickets compared across three models: seventy-two task runs and one hundred forty-four captured calls. Their recorded API estimate is about nine cents. This is a saved comparison, not a company invoice. Missing prices stay unknown, and hardware and electricity remain unmeasured.",
      "chapter": "02 / Understand the captured cost",
      "color": "sky"
    },
    {
      "id": "task",
      "title": "Follow a refund request, step by step",
      "start": 57.833,
      "end": 78.067,
      "text": "Open the refund-inside-the-window task. Workbench shows the customer request and the calls behind it: classify the request, then draft the decision and reply. Each step has its captured cost. Call completed means the API returned successfully. Answer quality still needs evaluation.",
      "chapter": "03 / Inspect the work",
      "color": "yellow"
    },
    {
      "id": "sources",
      "title": "Connect application usage deliberately",
      "start": 78.067,
      "end": 99.733,
      "text": "For your own application, create an AxonLLM source and configure its scoped connector. A durable outbox retries unacknowledged usage. The feed contains metadata, while saved answers are imported separately for quality checks. The recorded example is clearly labeled as a saved source, not a live connection.",
      "chapter": "04 / Know where the data came from",
      "color": "sky"
    },
    {
      "id": "evaluate",
      "title": "A cheaper answer still has to pass",
      "start": 99.733,
      "end": 118.6,
      "text": "Now run the evaluation. Workbench replays saved answers against the subscription-support contract and real Ostiari Guard checks. It checks policy decisions and action boundaries. The worker continues in the background, and the result remains available after you leave the page.",
      "chapter": "05 / Evaluate saved answers",
      "color": "violet"
    },
    {
      "id": "results",
      "title": "Compare quality alongside cost",
      "start": 118.6,
      "end": 137.9,
      "text": "The result compares tickets passed, critical failures, recorded response time, and cost per passing ticket. Money spent on failed tickets is included in that cost. These checks grade the saved responses. They do not establish today's model quality or performance on unrelated workloads.",
      "chapter": "06 / Read the evidence",
      "color": "violet"
    },
    {
      "id": "review",
      "title": "“No model qualifies” is a useful result",
      "start": 137.9,
      "end": 158.267,
      "text": "Set the requirements before looking for savings. With the saved strict criteria, no model qualifies. Workbench explains each exclusion instead of inventing a winning model. The next decision is to investigate the failing cases. Export the review with its evidence; no production route has been changed.",
      "chapter": "07 / Make the justified decision",
      "color": "teal"
    },
    {
      "id": "architecture",
      "title": "See how the evidence moves",
      "start": 158.267,
      "end": 180.4,
      "text": "The interactive architecture connects the pieces. AxonLLM supplies captured calls. Workbench owns the ledger and review. The worker and Ostiari Guard evaluate saved evidence. Select a component or play a narrated flow. Small solid circles show the direction, with pause and reduced-motion controls.",
      "chapter": "08 / Explore the architecture",
      "color": "violet"
    },
    {
      "id": "operations",
      "title": "Keep the workspace operating",
      "start": 180.4,
      "end": 200.233,
      "text": "Administrators can inspect evaluation-service health, queued work, failed evaluations, and calls without a price. The recorded demo is not new application traffic, so these recent-traffic counts can be zero. Company operators configure retention, backups, monitoring, and their response process.",
      "chapter": "09 / Inspect operational signals",
      "color": "teal"
    },
    {
      "id": "aws",
      "title": "Seeded and clean hosted test stacks",
      "start": 200.233,
      "end": 222.567,
      "text": "The optional AWS hosted test uses separate seeded and clean stacks, real Cognito sign-in, private CloudFront origins, encrypted off-host backups, and alarm receipts. Its architecture is interactive too. This is a single-host test, with an explicit no-MFA exception, not a high-availability production guarantee.",
      "chapter": "10 / Understand the deployment",
      "color": "teal"
    },
    {
      "id": "close",
      "title": "Know the cost. Keep the proof.",
      "start": 222.567,
      "end": 238.767,
      "text": "Workbench makes one complete decision path visible: connect usage, inspect a task, evaluate saved answers, and review the model choice with evidence. Explore the source, run the recorded demo, and connect your own application when you are ready.",
      "chapter": "AI Operations Workbench",
      "color": "violet"
    }
  ]
};
