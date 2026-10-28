# Workbench 0.5.0 verification — October 28, 2026

Scope: the company-neutral v0.5.0 source distribution, its public walkthrough,
and the previously verified seeded/clean AWS acceptance workspaces.

## Packaged-source checks

| Check | Result |
|---|---|
| Clean installation | Extracted source installed with locked Python 3.13 dependencies, the Bedrock extra, and a clean Node 22 install |
| Backend and PostgreSQL | 148 passed; four inapplicable SQLite concurrency variants skipped; PostgreSQL variants passed |
| Local demo and media | 13 browser checks passed |
| Authenticated PostgreSQL workspace | 13 browser checks passed, including billing import, declared scopes, revisions, export, retention refresh, access boundaries, and existing screens |
| Exact public build | Three browser checks passed under the repository path prefix, including the v0.5.0 download link |
| Playback and architecture | Real bundled audio/video, seeking, captions, narrated flows, moving solid circles, pause/resume, keyboard controls, and reduced motion passed |
| Public boundary | Public assets resolve without application APIs or WebSockets; authenticated deployment boundaries remain enforced |
| Artifact privacy | Source allowlist, documentation links, media checksums, editable architecture, and clean public output passed |

Local macOS browser checks disabled only browser audio output to avoid the
previous host audio-device stall. Media decoding and playback clocks remained
real; Linux CI retains the normal headless configuration.

Repository history and the publication working tree passed Gitleaks. Final
archive and public-output scans are part of the publication receipt. The tested
runtime, dependency locks, and tests are preserved in the final archive;
verification, provenance, and connector upgrade documentation were finalized afterward.

CI additionally installs Python 3.12 and 3.13, checks dependencies and runtime
images, and exercises seeded/clean containers and backup restoration.
The existing proxy backport, actual-binary checks, and image-specific SBOM/VEX
evidence remain unchanged.

## Existing implementation and hosted evidence

The [billing implementation report](VERIFICATION-BILLING.md) records format,
Decimal arithmetic, scope, authorization, retention, revision, concurrency,
and schema-migration checks. The [hosted acceptance](VERIFICATION-HOSTED-BILLING.md)
records both workspaces running 0.5.0/schema 4, real Cognito sign-in, preserved
original data, all eight scrollable panels, the isolated fictional billing
example, and downloaded encrypted backup restores.

The hosted application was verified at `abcdb60`. This publication updates
documentation and download references, without another AWS application deployment.
Both test workspaces retain their explicit password-only sign-in exception;
this does not establish production MFA or high availability.

## Evidence limits

New billing tests use authored CSV rows and synthetic usage. No paid model calls,
customer exports, or AWS billing API calls are part of release verification.
No general invoice authenticity, customer export compatibility, workload capacity,
or realized savings claim is made. Per-call invoice costs remain unknown.

The bundled support recording, audio/video, captions, and narrated architecture
remain their existing evidence; no new measured model quality or latency is claimed.
The recording does not demonstrate the newly added billing screen.

The release's attached `SHA256SUMS` identifies the exact downloadable archive.
See [download verification](RELEASE-0.5.0.md#download-and-verify). It is an integrity
checksum, not a publisher signature. Private operational receipts and test
credentials remain outside Git and release assets.
