# Security

## Supported release

Security fixes are considered for the latest `0.1.x` release and `main`.
This is an experimental local demonstration, with no support SLA.

## Report privately

Use [GitHub private vulnerability reporting](https://github.com/hk-775/ai-operations-workbench/security/advisories/new).
Include the affected version, a minimal reproduction with fictional data, and
the impact. Do not open a public issue containing an exploit, credential, or
private recording. If reporting is unavailable, request a private contact
channel through the maintainer's GitHub profile without disclosing the details.

## Deployment boundary

Run on `127.0.0.1`. The app has no login, tenant isolation, encrypted ledger,
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

Do not attach `.state/`, `.env`, worker logs, or private recordings to an issue.
See [the architecture](docs/ARCHITECTURE.md) for the implemented boundaries.
