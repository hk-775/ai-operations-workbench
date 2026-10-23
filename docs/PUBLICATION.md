# v0.1.0 publication inventory

## Destination and distribution

- Repository: `hk-775/ai-operations-workbench`.
- Canonical public entry point: the repository README.
- Distribution: GitHub source release `v0.1.0`.
- Intended runtime: the user's local workstation, bound to loopback.
- No package registry, container registry, public app backend, or AWS resources
  are part of this release.

The existing FastAPI-served frontend is the product UI. The README embeds
screenshots of that UI and links the quickstart; no separate mock dashboard or
static imitation is published.

## Artifacts and provenance

| Artifact | Source and interpretation |
|---|---|
| Code and documentation | Authored for this project; MIT-0 |
| `data/cases.json` | 24 authored, fictional Streamline support cases |
| `data/model-comparison.json` | Actual saved model responses to those fictional cases; normalized by AxonLLM |
| `docs/images/*.png` | Screenshots generated from the project's actual frontend and bundled recording |
| `docs/architecture/workbench.drawio` | Editable diagram of the implemented local workflow |
| `docs/architecture/workbench.svg` and `.png` | Original vector diagram and static rendered companion; no third-party artwork |
| AxonLLM and Ostiari | Public MIT-0 dependencies, pinned to immutable Git revisions |

The recording includes provider response IDs for event deduplication; these
are not credentials or proof of provider-authenticated provenance. Local paths,
credentials, customer material, and runtime databases are not release artifacts.
Upstream dependencies and their transitive packages retain their own licenses.

## Workflow animation

The canonical local UI includes moving solid circles, pause/resume, and
reduced-motion support, exercised by browser tests. Motion is illustrative and
does not represent live collection or measured execution timing.

GitHub README images and release screenshots are static platform companions.
They do not replace the animated workflow in the runnable app.

## AWS services reference architecture: not applicable to v0.1.0

This release is a workstation application with an explicit loopback boundary,
local SQLite, and local replay workers. The source contains no AWS SDK
integration, AWS IaC, remote ingestion service, or selected AWS deployment
target. Its model collection path uses an external model API through AxonLLM.

The roadmap describes product capabilities, but does not select a hosting
platform or define a credible AWS deployment contract. Adding AWS services
would imply deployment choices this release has not made. The separate
application diagram documents what is implemented. Revisit the AWS reference
architecture when a remote deployment design is selected.

## Release checks

CI clean-installs locked Python dependencies on Python 3.12 and 3.13, runs the
accounting, recommendation, API, and integration tests, and exercises the
browser workflow on Node 22 with Chromium. It also scans all fetched Git
history and the checked-out tree with a checksum-verified Gitleaks binary.
Actions are pinned to full commit SHAs and use read-only repository permissions.

Before publication, review the screenshots and bundled fictional content,
scan history and release archive contents, and install/test the actual source
archive from a clean environment. Verify the downloaded release archive
against its attached SHA-256 checksum after publication.
