# Authored coding-tool usage examples

These three files are fictional wire-format examples, not captured customer
traffic. They include a private-content sentinel to exercise metadata filtering.
The sentinel must not reach the outbox or Workbench's stored events.

Use `--fixture` with the [connector guide](../../docs/CODING-TOOL-CONNECTORS.md).
No vendor access, login credentials, or model calls are needed.

Expected metadata:

- `codex.jsonl`: one turn, 100 input tokens (80 cached), 12 output tokens;
  model is a configured label, monetary cost and duration unknown.
- `claude-otel.json`: one API response, separate cache categories, 125 ms,
  tool-reported model estimate USD `0.324501000`. The response-content
  event is discarded.
- `cursor-usage.json`: two vendor records; model amount USD `0.201823200`;
  vendor usage amount USD `0.213623200`, including one explicitly reported zero.
  Request-unit counts must not be priced as dollars.

Amounts with different bases are not added together. No source authenticates an
invoice, allocates a subscription, or establishes code quality.
