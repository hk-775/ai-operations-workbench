# Workbench 0.3.0 — a shareable walkthrough and hosted acceptance

This release makes the complete cost-to-review workflow easier to inspect,
share, and install. It includes the actual UI walkthrough, standalone narration,
captions, twelve chapters, and narrated product/AWS architecture tours. The
[public player](https://hk-775.github.io/ai-operations-workbench/) serves the same
canonical frontend and bundled media without a login or application API.

The source download also includes the additions made after v0.2.0:

- An optional AWS hosted test with isolated seeded and clean workspaces.
- Explicit password-only Cognito sign-in for that test, as selected by its owner.
- Encrypted off-host backups, isolated restores, and tested alert delivery to a queue.
- Guided team screens, named support tasks, per-call costs, clearer evaluation
  guidance, and overview cards matching the selected sidebar color.
- Narrated architecture with small moving circles, pause/resume, keyboard controls,
  reduced-motion support, and downloadable PNG/draw.io companions.
- A static Pages build with an explicit asset inventory, media checksums,
  browser-enforced API/WebSocket blocking, and public-route browser tests.

The evidence remains **24 fictional tickets, three models, 144 saved calls**.
The captured API estimate is `$0.088074750`; pass counts are 20/24, 18/24, and
14/24. The default review still returns **No model qualifies**. Playing or
regrading this example makes no new model calls. These are saved example
results, not reconciled invoices, general accuracy, or realized savings.

See [demo playback and rebuilding](DEMO.md), [company installation](PRODUCTION.md),
[release verification](VERIFICATION-0.3.0.md), and the
[dated hosted acceptance report](VERIFICATION-HOSTED-2026-10-26.md).
The AWS test remains a single-host installation. Its password-only profile
does not establish production MFA; its queue receipt does not establish
human on-call coverage.

## Download and verify

From [GitHub Release v0.3.0](https://github.com/hk-775/ai-operations-workbench/releases/tag/v0.3.0),
download `ai-operations-workbench-0.3.0.tar.gz` and `SHA256SUMS` into the same directory:

```sh
# macOS
shasum -a 256 -c SHA256SUMS
# Linux alternative: sha256sum -c SHA256SUMS
tar -xzf ai-operations-workbench-0.3.0.tar.gz
cd ai-operations-workbench-0.3.0
uv sync --locked --python 3.13
uv run --locked python scripts/deploy_instances.py
```

The checksum covers the attached source archive, not GitHub's generated source
ZIP/tarball. It verifies file integrity; no publisher signature is claimed.
The archive includes the video, audio, captions, narration clips, locked
dependency manifests, architecture sources, AWS recipes, tests, and documentation.
Dependencies download during installation; this is not an offline dependency bundle.

The seeded and clean installations each generate separate private credentials.
Company DNS, identity, secrets, and runtime data are supplied at installation
and are excluded from the release. Existing v0.2.0 assets remain unchanged.

## Upgrade

There is no new database schema or repricing migration in 0.3.0; schema version 2
and the supported support-v1 contract are unchanged. Follow the
[backup and upgrade procedure](PRODUCTION.md#backup-restore-and-upgrade), preserve
private configuration and volumes, and install matching app, worker, and
maintenance code. The PostgreSQL and proxy recipes retain their existing pinned
component versions.

Native subscription-tool connectors, invoice reconciliation, arbitrary workload
evaluators, and production routing activation remain future features.
