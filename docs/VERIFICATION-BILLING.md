# Billing reconciliation verification — October 28, 2026

Scope: 0.5.0 development source and schema 4. This is implementation evidence,
not a release announcement or a claim that hosted v0.4.0 was upgraded.

## Local checks

- A fresh Python 3.13 environment was installed using `uv sync --locked`.
- **148 Python tests passed; 4 SQLite-inapplicable concurrency tests skipped.**
  PostgreSQL checks used an isolated PostgreSQL 16 container, separate schemas,
  and generated temporary credentials.
- The focused billing suite passed **56 tests**, with two SQLite concurrency
  skips. Cases include Legacy CUR/CUR 2.0, Decimal precision, negative adjustments,
  unsupported/missing values, account/currency/month validation, atomic rejection,
  replacement revisions, stale previews, duplicate scope prevention, fixture
  isolation, roles, team isolation, CSRF, export, concurrent imports/mappings,
  and compatibility with unrelated audit transactions.
- **12 authenticated browser journeys passed**, including the complete billing
  upload/preview/import/map/refresh/history/export flow and all existing screens.
  Untrusted names rendered as text. Sign-out cleared private billing DOM content.
  Viewer access remained read-only. Desktop and mobile layouts were inspected.
- **13 existing demo/architecture/media journeys and 3 Pages checks passed.**
  Local macOS media checks used an external test configuration disabling audio
  output while retaining media playback assertions; CI configuration was unchanged.
- A separate visible-window check used the actual browser viewport and verified
  that all eight workspace screens reached their footer with keyboard scrolling.
- Gitleaks found no leaks in repository history or a clean source review tree.

## Migration and recovery

The schema-3 migration test preserves historical events and accounting facts
byte for byte while creating schema-4 billing storage. Tests also check retention
deletion, comparison-map cascades, and persistence of source account configuration.

A PostgreSQL custom-format backup containing the fictional bill, declared
mapping, and captured events was restored into a separate empty database.
The restored reconciliation export matched the original exactly except for its
new calculation time. Imported charges remained `0.0121475`, the captured-call
estimate `0.0001295`, and the selected-group difference `0.000018` USD.

## Evidence limits

All billing records and usage for the new billing tests were authored fixtures.
No customer exports, AWS billing API calls, paid model calls, new cloud resources,
or hosted database upgrades were part of this verification. The tests establish
the implemented format contract; they do not authenticate an AWS invoice or
demonstrate compatibility with every export configuration.

The public v0.4.0 archive remains unchanged. See [billing setup, interpretation,
retention, and upgrade instructions](BILLING.md) before deploying schema 4.
