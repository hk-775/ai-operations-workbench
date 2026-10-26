# Publication inventory

## Main branch additions after v0.2.0

The main branch now includes `compose.hosted-test.yaml`, AWS CloudFormation and
host configuration under `deploy/aws/`, and the hosted acceptance guide/report.
The optional AWS test has been deployed and verified; private account identifiers,
addresses, credentials, and operational receipts remain outside source control.
Public GitHub CI builds and tests code only; it does not deploy this stack.

The company-neutral source packager includes the hosted overlay, host utilities,
and both AWS architecture files. The editable diagram and its PNG use authored
draw.io shapes and official AWS service names; no third-party icon artwork is
bundled. Source and images are project-authored under MIT-0.

The team UI now explains task runs, recorded customer examples, individual model
steps, evaluation results, review requirements, connections, operations, and roles.
Overview cards match the selected sidebar fill. The hosted test uses password-only
Cognito SSO by explicit opt-in; standard production authentication remains unchanged.

These are additions to the repository, not a replacement of the published
v0.2.0 archive. Publishing another release is a separate operation.

## Published v0.2.0 destination and distribution

- Repository: `hk-775/ai-operations-workbench`.
- Canonical public entry point: the repository README.
- Distribution: GitHub source release `v0.2.0`, containing
  `ai-operations-workbench-0.2.0.tar.gz` and `SHA256SUMS`.
- Intended runtime: a local recorded demonstration or an independent,
  single-organization Docker Compose installation.
- The seeded and clean test deployments bind to loopback. A company's production
  installation supplies its own HTTPS domain, OIDC/MFA, secrets, monitoring, and
  encrypted host/backup storage.
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
| `docs/architecture/workbench.drawio` | Editable diagram of the original local demonstration workflow |
| `docs/architecture/workbench.svg` and `.png` | Original vector diagram and static rendered companion; no third-party artwork |
| `docs/ARCHITECTURE.md` | Editable Mermaid diagrams for the authenticated pilot and self-hosted production profile |
| `web/architecture.html`, `.css`, and `.js` | Offline-capable interactive product/AWS architecture; served at `/static/architecture.html` and linked from both dashboard footers |
| `compose*.yaml` and `deploy/` | Company-neutral deployment recipes; installation-specific files are generated privately |
| AxonLLM and Ostiari | Public MIT-0 dependencies, pinned to immutable Git revisions |
| Container build recipes | Pinned upstream Python, PostgreSQL, Go, uv, and Caddy images/modules; no prebuilt container images are distributed by this release |

The recording includes provider response IDs for event deduplication; these
are not credentials or proof of provider-authenticated provenance. Local paths,
credentials, customer material, and runtime databases are not release artifacts.
Upstream dependencies and their transitive packages retain their own licenses.

## Workflow animation

The canonical local UI includes moving solid circles, pause/resume, and
reduced-motion support, exercised by browser tests. Motion is illustrative and
does not represent live collection or measured execution timing.

The architecture explorer adds clickable components and manual step-by-step
walkthroughs for capture, evaluation, review, sign-in, backup, and alerts. It
uses the Workbench palette and needs no API, cloud connection, or third-party
assets. Browser tests cover both views, keyboard selection, mobile scrolling,
motion controls, direct file access, and asset loading under a path prefix.

GitHub README images and release screenshots are static platform companions.
They do not replace the animated workflow in the runnable app.

## AWS services reference architecture

The main branch's implemented test topology is available as an
[editable draw.io file](architecture/aws-hosted-test.drawio) and
[rendered PNG](architecture/aws-hosted-test.png), embedded in the README and
architecture guide. It corresponds to the current optional AWS CloudFormation
template and hosted acceptance results.

### Historical v0.2.0 decision

The supported installation contract is platform-neutral Docker Compose with
PostgreSQL, an HTTPS proxy, offline workers, and an external OIDC provider.
Companies choose their host and operating services. The v0.2.0 archive contains no AWS
IaC, AWS deployment automation, or selected AWS hosting target. Native Bedrock
usage ingestion remains a roadmap item.

An AWS host is possible, but choosing services such as ECS, RDS, Cognito, or a
managed backup service would introduce a deployment contract this release does
not implement or validate. The application and production-profile diagrams show
the actual supported boundaries. Add a separate AWS service diagram and its
editable source when an AWS installation target becomes part of the product;
the decision here is based on the platform-neutral scope, not on local-only status.

## Release checks

CI clean-installs locked Python dependencies on Python 3.12 and 3.13, runs the
accounting, recommendation, API, and integration tests, and exercises the
demo and authenticated browser workflows on Node 22 with Chromium. Container
checks initialize both seeded and clean deployments, replay evidence, and verify
database backup/restore. Dependency and high/critical runtime-image audits run
alongside scans of fetched Git history and the checked-out tree using Gitleaks.
Actions are pinned to full commit SHAs and use read-only repository permissions.

Before publication, review the screenshots and bundled fictional content,
scan history and release archive contents, and install/test the actual source
archive from a clean environment. Verify the downloaded release archive
against its attached SHA-256 checksum after publication.

The source archive excludes `.pilot/`, `.state/`, credentials, outboxes,
environments, and dependency caches. Its SHA-256 checksum verifies file integrity;
this release does not provide a cryptographic publisher signature. Company
SSO/TLS, alert delivery, encrypted storage, and restore acceptance remain
installation checks described in [PRODUCTION.md](PRODUCTION.md).
