# Workbench 0.9.2 — retain Codex cache-write usage

Codex JSONL streams can include `usage.cache_write_input_tokens` on completed
turns. Earlier collectors discarded that category. New captures now retain the
reported count, including zero, alongside input, output, cache-read and reasoning
tokens. An omitted category remains unknown. Counts are not added to the reported
input total, and coding-tool records are not repriced as API calls.

## Collector upgrade and replay

Stop capture and delivery, back up the complete private outbox, and upgrade both
processes together. Keep the same outbox, project and source. On opening it, the
collector adds local normalization-version metadata without rewriting existing
payloads, fingerprints or delivery acknowledgments.

Replays of events saved by v0.9.1 or earlier use their original normalization.
Cache writes omitted by those collectors remain unknown in those historical
records. New events in the same outbox retain reported cache writes. Changes to
fields retained by an event's original normalization remain replay conflicts.
Historical facts are not silently backfilled.

An older collector cannot reliably replay newer records. Rollback requires the
matching prior collector and backed-up outbox with writers stopped. Do not create
another production source/outbox to append the same historical usage.
See [Codex setup and upgrade details](CODING-TOOL-CONNECTORS.md#upgrading-codex-collectors).

**PostgreSQL remains on schema 5.** No additional server migration is needed from
v0.9.0 or v0.9.1. The existing usage schema and dashboard already support this
token category. Upgrades from v0.8.0 or earlier still require the
[explicit schema-5 procedure and cursor compatibility update](REVIEW-FIXES.md).
Dependency pins and deployment topology are unchanged.

## Download and verify

Download `ai-operations-workbench-0.9.2.tar.gz` and `SHA256SUMS` from
[GitHub Release v0.9.2](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.9.2).

```sh
shasum -a 256 -c SHA256SUMS
tar -xzf ai-operations-workbench-0.9.2.tar.gz
cd ai-operations-workbench-0.9.2
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

Verification covers reported zero/nonzero cache writes, missing-versus-zero
replay conflicts, original legacy payload/fingerprint preservation, new captures
in an upgraded outbox, unsupported future formats, and existing source/delivery
boundaries. Public-demo checks cover the updated release link. Required GitHub
CI runs the repository's backend, browser, container/restore and security checks.

MIT-0. Existing media, editable diagrams and earlier release assets are retained.
Private vendor inputs, credentials and account-specific acceptance receipts are
excluded. No broad vendor-account or desktop-telemetry acceptance is implied.
SHA256SUMS verifies bytes; no publisher signature is asserted.
