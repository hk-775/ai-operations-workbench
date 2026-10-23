# Security

## Supported release

Security fixes are considered for the latest `0.1.x` release and `main`.
The project includes a local demonstration and an opt-in, self-hosted team pilot.
There is no support SLA or claim of enterprise security certification.

## Report privately

Use [GitHub private vulnerability reporting](https://github.com/hk-775/ai-operations-workbench/security/advisories/new).
Include the affected version, a minimal reproduction with fictional data, and
the impact. Do not open a public issue containing an exploit, credential, or
private recording. If reporting is unavailable, request a private contact
channel through the maintainer's GitHub profile without disclosing the details.

## Deployment boundary

In default **demo mode**, run on `127.0.0.1`. The demo has no login, tenant isolation, encrypted ledger,
or remote ingestion service. Do not expose it publicly or load sensitive
customer records into it. The bundled tickets are fictional.

Imports are untrusted. Validation checks their internal structure, requests,
and arithmetic; it does not authenticate provider provenance or reconcile an
invoice. Rendered text is escaped, cross-origin requests are rejected, and
imports are size-limited.

Replay launches a local evaluation subprocess and makes no model calls.
Credential-like environment variables are removed from the worker environment;
this is not a general process or network sandbox. Live collection uses the
separate CLI and an explicit estimated budget, not a provider billing cap.

In **pilot mode**, team endpoints require revocable, hashed sessions and role
checks. State-changing browser requests require CSRF tokens. Ingestion tokens
are hashed, expire after 30 days, bind to one team/source, and cannot read browser
data. Disabling a user revokes sessions. Passwords use Argon2; login throttling is
database-backed. Pilot mode does not mount the demo's unauthenticated API.

The supplied pilot Compose stack binds only to loopback and runs app/worker
containers without root, with read-only filesystems and no provider credentials.
Remote access requires a managed HTTPS proxy and an explicit public origin;
cookies become Secure under HTTPS. Workbench does not provide SSO/MFA, application
encryption at rest, automated retention, or a general evaluator sandbox. The
pilot's account/team scoping is tested but is not a multi-tenant SaaS guarantee.

PostgreSQL records, outboxes, and backups can contain sensitive metadata and
uploaded model content. Keep them on protected volumes. Default usage capture
excludes prompts/responses. Source authentication does not prove provider usage
provenance or complete retry coverage. Unknown costs remain explicit.

Do not attach `.state/`, `.pilot/`, `.env`, outboxes, worker logs, or private recordings to an issue.
See [the architecture](docs/ARCHITECTURE.md) for the implemented boundaries.
See [pilot operations](docs/PILOT.md) for bootstrap, token rotation, backup,
restore, and upgrade procedures.
