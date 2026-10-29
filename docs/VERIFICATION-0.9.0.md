# Workbench 0.9.0 verification

The review fixes have regression coverage for connector binding and repair,
ambiguous delivery, concurrent ingestion, schema-4 upgrades, backdated/tied call
arrivals, separate exact monetary bases, malformed model output, fixture gates,
case inspection, and complete evidence exports.

The October 29 clean release checkout passed **242 backend tests** against
SQLite and PostgreSQL and **34 browser checks**: 18 authenticated workspace,
13 local demo/architecture, and three public Pages checks. Six backend skips
cover database-specific variants and the separately enabled Docker check.
The implementation checkpoint also verified that real network-disabled Docker
execution retains malformed attempts and their costs while continuing the run.

Clean locked Python and Node installations passed. The 281-file allowlisted
source archive passed its own secret scan and installed into another fresh
Python environment. The actual published v0.8.0 archive was downloaded and
checksum-verified for the upgrade test.

That old archive created a schema-4 database with the bundled 144-call recording.
The v0.9.0 archive correctly refused the old schema until explicit migration,
then migrated it twice. Every historical row, payload, fingerprint, pricebook,
accounting value and usage total remained identical; legacy ingestion sequences
started at zero. This is an isolated archive test using the public example,
not a customer or hosted deployment claim.

Public browser checks passed for the v0.9.0 download link, architecture
interaction, narration, animation, pause and reduced-motion behavior.
History and working-tree secret scans passed.

The CI pipeline runs Python 3.12/3.13, PostgreSQL integration, browser journeys,
container bootstrap/restore, worker recovery, dependency/image audits and
history-aware secret scanning. Exact run results are attached to the release
commit's GitHub checks. The final archive is separately scanned and its public
download is verified against `SHA256SUMS`.

## Evidence boundaries

Authored connector fixtures verify contracts, validation, replay and privacy
filtering. They are not live Codex, Claude Code or Cursor account acceptance.
Real-account checks require operator-provided supported captures or explicitly
authorized vendor access; receipts and raw inputs remain private.

Source publication does not establish customer billing completeness, human
alert receipt, customer load/recovery targets or production routing outcomes.
Installation-specific addresses, identity configuration, usage inputs,
credentials, screenshots and acceptance receipts are excluded from Git and the
archive. No paid model calls run in CI or browser verification.

The application still requires authentication. The public Pages build serves
static media and architecture only and blocks application/model connections.
Existing editable AWS diagrams describe the same optional topology; this
release changes no infrastructure.
