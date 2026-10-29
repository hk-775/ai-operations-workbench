# Workbench 0.9.1 — consistent schema-5 setup guidance

This documentation patch corrects setup guides that still directed operators to
schema 4 after v0.9.0 introduced schema 5. Codex/Claude Code/Cursor, Bedrock,
billing collection, reconciliation and pilot instructions now agree with the
application's startup checks. Earlier release and verification reports retain
their historical scope.

All [eight v0.9.0 review fixes](RELEASE-0.9.0.md) remain included. Application
code, locked dependencies and database schema are unchanged from v0.9.0.
**No additional migration is needed from v0.9.0/schema 5.** Upgrades from v0.8.0
or earlier still require the [explicit schema-5 procedure](REVIEW-FIXES.md),
including backup, stopped writers, matching services and cursor compatibility.

## Download and verify

Download `ai-operations-workbench-0.9.1.tar.gz` and `SHA256SUMS` from
[GitHub Release v0.9.1](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.9.1).

```sh
shasum -a 256 -c SHA256SUMS
tar -xzf ai-operations-workbench-0.9.1.tar.gz
cd ai-operations-workbench-0.9.1
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

The canonical player and source archive identify v0.9.1. Existing audio, video,
captions, animated architecture and editable AWS diagrams remain included.
Follow [production installation](PRODUCTION.md) for company-owned deployment.

## Validation scope

The [v0.9.0 verification report](VERIFICATION-0.9.0.md) covers the unchanged
application code, including a populated upgrade from the published v0.8.0
archive. Patch checks cover locked archive installation, documentation links,
runtime/dependency equality, public download checksums and browser acceptance
for the updated version. GitHub CI runs the repository's required checks.

Native connector fixtures remain authored examples. No real vendor-account
acceptance is asserted without operator-provided usage inputs and delivery
evidence. Private credentials, recordings and deployment receipts are excluded
from Git and the archive. MIT-0; previous release assets are preserved.
SHA256SUMS verifies bytes and is not a publisher signature.
