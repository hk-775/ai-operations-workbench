# Billing collection and coding evidence verification

Source changes after v0.5.0, verified on 2026-10-28. These checks do not describe
a new published release or a change to the existing AWS hosted deployments.

## Evidence and acceptance

- The configured AWS account's read-only discovery returned no Legacy CUR
  report definitions and no Data Exports. No customer billing files were supplied.
  Real billing acceptance and live scheduled S3 delivery therefore remain pending.
- At the user's request, a fictional bundle was created with Legacy CUR and
  projected CUR 2.0 CSVs, two matching usage events, five billing rows,
  independent authored controls, and a fixture verification receipt.
  Both formats normalize identically. Repeated loading preserves the same data.
- The acceptance checker rejects wrong snapshots, control totals, incomplete
  usage and corrupt comparison arithmetic. Fixture mode is explicitly labeled
  and cannot pass as real-data acceptance.
- SDK stubs and authored S3 objects exercise complete assembly retrieval,
  missing parts, changing manifests, expected bucket owner/ETag parameters,
  decompression bounds, wrong account, overwrite/cross-prefix rejection,
  replay, refresh, stale imports, durable failure state and team isolation.

## Coding demonstration

The final bundled result was produced by the Docker runner from the six authored
cases and three authored candidates. Every broken and reference baseline was
executed before candidate grading. The saved result includes actual container
test outcomes/duration, final patches, all attempts, dataset/recording/evaluator
hashes, and the resolved image ID. Model patches, token counts, model latency and
API estimates in this example are fictional.

The runtime uses the existing pinned Python 3.13 Alpine base image. An additional
real-container test verified timeout, output limits, non-root execution,
read-only source, and absence of forwarded API credentials. Candidate code ran
only in disposable containers with networking disabled.

The optional AxonLLM model recorder was tested with a fake provider, including
pre-dispatch budget rejection, persisted unknown in-flight costs, private
provider failures, withheld acceptance tests, and unexpected response-model
handling. **No paid model calls were made.**

Result checks cover accounting across failed tasks and repair attempts, final
patch identity, incomplete coverage, unknown costs, safe test-count types,
timing consistency, and Python/browser JSON number round-trips. Checksums
establish consistency, not independent authenticity of an imported execution.

## Application and packaging checks

- Full backend suite: **181 passed, 5 skipped**. Skips comprised the four existing
  SQLite-only concurrency variants and the separately run opt-in Docker test.
  PostgreSQL counterparts ran using a dedicated temporary database container.
- Following final evidence-format changes, the focused billing, coding and
  publication suite passed **37 tests**; the final coding checks then passed
  **8 tests**. The opt-in container boundary test passed separately.
- All **15 distinct authenticated browser journeys** passed, including the
  corrected coding download/re-upload journey, fictional ZIP download,
  collection health, viewer access, logout clearing and mobile layout.
- A visible browser using its actual viewport passed wheel and keyboard
  scrolling to the footer on **all nine panels**.
- Locked Python and Node dependency installs succeeded. Dependency lock files,
  database schema 4, production authentication rules and the existing hosted
  test exception were unchanged.
- The source packager explicitly includes the new coding and billing fixtures
  while preserving exclusion of private runtime data. A new CI job executes
  the real coding sandbox contract and demonstration.
- A fresh source archive passed its checksum, locked offline dependency install,
  billing bundle rebuild and saved coding-result validation. Gitleaks found no
  secrets in the extracted package.
- The deployable image was built and tested as its non-root application user
  with networking disabled. Coding example/preview and the six-file billing
  download passed. The Docker context explicitly allows the public fixtures;
  the existing authenticated container smoke check now verifies these endpoints.

The implementation uses the existing immutable billing snapshots and operator
maintenance state. It introduces no schema migration, provider-side export,
automatic routing change, or native coding-tool subscription connector.
