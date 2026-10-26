# Hosted acceptance verification — October 26, 2026

Two isolated AWS workspaces passed hosted acceptance: one seeded demonstration
and one clean installation. Both use real Amazon Cognito sign-in with **MFA
disabled**, as explicitly requested for this test. The standard production
profile continues to require a verified MFA claim.

The installation uses a dedicated EC2 t3a.large, separate PostgreSQL databases
and application processes, CloudFront HTTPS with private VPC origins, encrypted
S3 backups, and CloudWatch alarms delivered through SNS to a private SQS queue.
Deployment addresses, resource identifiers, credentials, and detailed receipts
are kept in the private `.pilot/hosted/` directory.

## Observed results

| Check | Result |
|---|---|
| Infrastructure | CloudFormation update complete; both workspaces ready |
| Real identity provider | Both administrator accounts completed the Cognito browser flow; pool MFA setting is `OFF` |
| HTTPS and anonymous boundary | All 18 checks passed per workspace, including protected API/metrics access, disabled local login, PKCE, and secure binding cookies |
| Seeded workspace | 144 recorded call events, 72 tasks, one completed evaluation, and one saved review |
| Clean workspace | Zero calls, tasks, sources, recordings, evaluations, and reviews |
| Accounting | Demo captured API estimate exactly `$0.088074750`; clean estimate `$0.000000000` |
| Evaluation | Saved-output replay produced 20/24, 18/24, and 14/24 passes; the review correctly returned no eligible model |
| Session isolation | A signed-in demo context had no authenticated session on the clean origin |
| Browser acceptance | Real login and all seven views passed in each workspace, in headless and interactive runs; interactive checks used the actual window viewport |
| Logout | Both headless sessions became anonymous after sign-out |
| Scheduled backup | The actual systemd timer produced an encrypted S3 backup for each database; uploaded metadata and SHA-256 receipts were verified |
| Restore | Both downloaded backups restored into separate temporary databases; accounting, linked identity, evaluations, and reviews matched |
| Restore duration | Demo: 7.051 seconds; clean: 8.784 seconds |
| Worker outage | Stopping the demo worker made public readiness fail after the heartbeat expired |
| Alert delivery | The new outage alarm reached the private queue at 18:13:32 UTC |
| Recovery | Worker readiness recovered 8.34 seconds after restart; the recovery notification reached the queue at 18:16:32 UTC |
| Final alarm state | Both readiness alarms and both backup-age alarms were `OK` |
| Protected monitoring | Both authenticated `/metrics` requests returned 200 with healthy workers; backup and monitoring timers were active |

The restored backups were generated at 18:07:07 UTC for demo and 18:07:12 UTC
for clean. Restores did not replace the live databases; temporary restore
databases were removed. The alert receipts were matched to the outage start
time, excluding earlier startup alarms.

## Corrections established by the hosted test

- Bootstrap now verifies pinned Docker Compose and Buildx binaries using their
  published SHA-256 digests.
- Worker and maintenance container probes query their persisted timestamps
  directly. This avoids loading evaluation dependencies during each short
  health check while preserving the existing freshness limits.
- Scheduled operations use a dedicated Docker client configuration directory,
  allowing backups to run with the service's home-directory protection enabled.

The backend suite passed 76 tests with one PostgreSQL-only concurrency variant
skipped before the probe correction. The focused production and health-probe
checks after that correction passed 37 tests with one inapplicable SQLite
variant skipped. CloudFormation linting, the project infrastructure guard rules,
source secret scanning, and whitespace checks also passed.

The application source archive deployed during verification had SHA-256
`d3f8ea14d68e488c65fb19d249417073a65d73e2e39b0d67da3579bdf4e05c13`.
The host timer correction was applied afterward. Verification tools and this
report were finalized locally after deployment. This records acceptance of the
hosted candidate; it does not replace the published v0.2.0 release or report
GitHub CI results for the new changes.

## Scope and limits

No paid model calls, customer traffic, routing activation, or notifications to
people were part of this verification. API amounts are recorded published-rate
estimates, not AWS hosting charges or reconciled invoices. Alert delivery ended
at the owned test queue; a human on-call destination remains an operator choice.

The restore timings describe these small databases on this host. They do not
establish workload capacity, an availability guarantee, or recovery on a newly
built host. The deployment has one server, and private VPC/container hops use
HTTP after HTTPS terminates at CloudFront. This test does not validate production
MFA. See [the hosted test guide](HOSTED-TEST.md) for configuration, backup
retention, recovery requirements, and retained-resource behavior.
