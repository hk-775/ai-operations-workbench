# Workbench 0.2.0 — self-hosted team operations

This release packages Workbench for one company to run in its own environment.
Company infrastructure, identity settings, and secrets are supplied at installation.

- Deploy a seeded recorded demo and an isolated clean workspace with one command.
- Use company OIDC, PKCE, verified MFA claims, explicit roles, and revocable sessions.
- Inspect usage beyond the old 10,000-event limit with SQL totals and task/call pages.
- Filter by UTC window, project, and source without changing historical prices.
- Monitor workers, evaluation queues, failures, cost coverage, and maintenance.
- Configure private Prometheus scraping, alert rules, HTTPS, and scheduled retention.
- Upgrade schema 1→2 with a transactional backfill and verify a restored database.

The saved support workload remains unchanged: 144 calls, 24 authored cases,
20/24, 18/24, and 14/24 passes, and no eligible model at the default criteria.
Replay, seeding, and automated verification make no paid model calls.

Start with [installation and operations](PRODUCTION.md). Existing local pilot users
should back up before running the migration and deploy a matching app/worker image.
Production startup checks the schema explicitly. The default local demonstration
retains its loopback-only behavior.

See [dated verification results](VERIFICATION-0.2.0.md) for the functional,
browser, load, restore, and runtime-image checks.

This release does not add native Codex/Cursor/Claude Code billing ingestion,
invoice reconciliation, arbitrary workload evaluation, multi-company SaaS accounts,
or automatic routing deployment. Customer-specific SSO/TLS, alert delivery, storage
encryption, and restore acceptance remain installation checks.
