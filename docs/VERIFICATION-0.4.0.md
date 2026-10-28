# Workbench 0.4.0 verification — October 28, 2026

This report covers the source release, recorded demonstration, and existing
seeded/clean AWS acceptance workspaces. It does not establish customer capacity,
general model quality, invoice reconciliation or availability guarantees.

## Release verification

| Check | Result |
|---|---|
| Extracted source installation | Fresh locked Python 3.13 environment with the Bedrock extra; clean Node 22 installation |
| Backend, including PostgreSQL | 92 passed; two inapplicable SQLite concurrency variants skipped; PostgreSQL variants passed |
| Local demo and media | 13 browser checks passed |
| Authenticated PostgreSQL workspace | 11 browser checks passed |
| Exact static public build | Three browser checks passed under the repository path prefix |
| Playback and architecture | Actual bundled MP4/MP3 playback, seeking, captions, chapters, narration, moving solid circles, pause/resume, keyboard controls and reduced motion |
| Public boundary | Static build blocks API/WebSocket connections; authenticated production remains protected |
| Artifact privacy | Source allowlist, media checksums, documentation links and editable architecture checks passed |
| Secret scanning | Git history, extracted source and static public output passed Gitleaks |

Local media checks disabled only the test browser's audio output to avoid a
host audio-device stall. The media decoder and playback clock remained real.
Linux CI uses the normal headless browser configuration.

The repository's CI additionally clean-installs on Python 3.12 and 3.13, checks
dependencies and runtime images, and exercises seeded/clean containers and
backup restoration. The proxy's backport tests and actual runtime self-test
gate its image-specific SBOM/VEX evidence. Its resolved finding is scoped to
the patched component and scanned image; other findings remain visible.
See the [backport provenance and checks](../deploy/images/proxy/patches/README.md).

The Bedrock development checks retain their original scope and date in
[VERIFICATION-BEDROCK.md](VERIFICATION-BEDROCK.md). They cover SDK request/response
contracts, retry/capture gaps, interrupted streams, exact pricing, durable delivery,
source/team access, collector aggregation and explicit schema migration.

## Hosted acceptance

The application at commit `07f5ecc` was deployed and verified on October 28.
This release's publication follow-up changes documentation and download links;
the application and runtime build recipes are the same verified code.

- Both existing workspaces run version 0.4.0 and schema 3.
- The seeded workspace preserved 144 events, 72 tasks and the saved
  `$0.088074750` API estimate. The clean workspace remained empty.
- Company-style Cognito sign-in, source/task guidance, seven scrollable panels,
  video/audio/captions and narrated architecture passed.
- A temporary Bedrock source delivered the two-record synthetic fixture through
  real authenticated HTTPS ingestion. Replay created no duplicate charges.
  Native token details, collector health and mobile task inspection passed.
- The synthetic fixture and its temporary source/token/collector were removed
  afterward; the original demo totals and clean isolation were rechecked.
- Fresh encrypted off-host backups were downloaded, checksummed and restored
  into isolated databases; schema, totals and saved evidence were verified.
- Pre-upgrade databases and application/proxy images were retained for rollback.

Private endpoints, account identifiers, credentials and operational receipts are
excluded from this public report and the source archive. The single-host AWS
test uses its explicitly selected password-only sign-in; it does not verify
production MFA or high availability.

All release and hosted checks made **zero paid model calls**. The Bedrock fixture's
counts, timings and `$0.000129500` estimate are synthetic. No new measured model
quality, latency, savings or invoice costs are claimed. The unchanged support
recording remains a small authored example with no qualifying default route.

The release's attached `SHA256SUMS` identifies the exact downloadable archive.
Follow [download verification](RELEASE-0.4.0.md#download-and-verify) to check its
bytes; the checksum is not a publisher signature.
