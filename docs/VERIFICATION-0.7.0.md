# Workbench 0.7.0 verification

Checked on October 29, 2026. Private account identifiers, host addresses,
credentials, billing inputs and operational receipts remain outside Git.

## Coding calibration

The corrected dataset contains 18 distinct tasks and 76 checks. All reference
checks passed; broken baselines failed 41. Three pinned models each completed
three repetitions, yielding 162 task runs and 165 actual model calls.
The recorded API estimate was USD 0.0639984. Docker replay independently graded
every attempt, with complete recorded cost and planned coverage.

See [methodology, protocol correction and results](CODING-CALIBRATION-2026-10-29.md).
No funded calls run in CI or the browser. Fixture results remain separate.

## Independent AWS host recovery

Actual scheduled encrypted backups were restored on a newly provisioned EC2
instance with independent encrypted disks, its own security group and SSM role.
The machine identity differed from the source host. Both workspaces matched all
**24 application tables** by row count and content hash before workers started.

| Workspace | Recorded calls | Identity links | Evaluations | Reviews |
|---|---:|---:|---:|---:|
| Seeded demo | 144 | 1 | 1 | 1 |
| Clean | 0 | 1 | 0 | 0 |

Production configuration checks passed. Local HTTP checks verified readiness,
unauthenticated usage/metrics rejection, and rejection of an unrecognized Host.
The existing source workspaces continued serving; they were never restored over.
Source backup/monitoring timers were not installed on the recovery host.

The drill rebuilt the then-published **v0.6.0/schema-4** source archive, verified
against SHA-256
`b75f821daa77577e1f3f071d04c2510c46a25115e517541f3b480a9e6c275f3f`.
The successful restore attempt took **175.458 seconds** after the initial image
build. Backup age was about **95 minutes**. These measurements exclude the full
provisioning/debugging interval and are not a customer RTO/RPO commitment.
The first probe used an incorrect Host header; it was fixed without weakening
the application's host validation.

The private S3 receipt was downloaded and compared with the SSM result before
cleanup. The disposable stack and private bootstrap versions are removed after
verification; the original backups and billing export are preserved.
This proves private recovery, not DNS cutover, automatic failover, or a new
interactive SSO/MFA acceptance test.

## Billing and alerts

A private encrypted/versioned Legacy CUR CSV/gzip export was provisioned in the
selected account. Two real Nova Micro calls were captured with provider-reported
usage and USD 0.000005390 in saved API estimates. Prompts/responses were not
stored in the usage outbox.

At this checkpoint, AWS had written its bucket verification object but no
monthly manifest. **Real billing delivery and reconciliation remain pending.**
The actual report, complete account/model/region scope, and independent controls
must be checked before recording acceptance. A provider estimate is not an invoice.

The existing alarm-to-queue path has machine-delivery evidence. **Human email
acceptance remains pending** until the selected recipient confirms the
subscription and acknowledges a test notification.

## Reproducible software checks

- Locked Python environment and unchanged dependency versions; only the project
  version advances to 0.7.0.
- Full backend suite against temporary PostgreSQL, plus SQLite behavior checks.
- Browser journeys for the teaching example, full recorded calibration,
  file preview, threshold changes, download, scrolling and sign-out clearing.
- CloudFormation schema validation in `us-east-1`, cfn-guard checks, reviewed
  service change sets, and actual export/recovery execution.
- Public-page build and browser checks retain the static-only network boundary,
  narration, moving circles, pause/resume and reduced-motion behavior.
- Source/archive privacy checks and public download verification accompany release.

The release workflow retains exact CI, scan, archive and public-download receipts.
Customer workloads, broader export formats/volumes, native coding subscriptions,
human-review costs and production routing activation remain outside this evidence.
