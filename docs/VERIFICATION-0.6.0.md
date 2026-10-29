# v0.6.0 verification — 2026-10-29 UTC

This is reference evidence for the released operator tools, not a customer
production certification. The source archive retains schema 4 and the pinned
AxonLLM, Ostiari and Ledger revisions. The lockfile change is the project version
only; third-party dependency versions are unchanged.

## Concurrent traffic and recovery

The actual application image was tested through HTTP using four concurrent
clients and separate disposable PostgreSQL/app/worker stacks. See the
[machine-readable receipt](evidence/v0.6.0/reference.json) and
[reproduction instructions](REFERENCE-ACCEPTANCE.md).

| Check | Observed result |
|---|---|
| Synthetic events / tasks | 25,000 / 12,500 |
| Ingest requests | 500 batches, including exact duplicate delivery |
| Added / duplicate events | 25,000 / 25,000 |
| Ingest duration / batch p95 | 15.186 s / 203.053 ms |
| Concurrent read phase | 300.232 s, with 100 ms pacing per client |
| Usage-page requests / HTTP errors | 4,811 / 0 |
| Usage-page p95 | 209.058 ms |
| Fixture exclusion | Preserved |
| Abandoned worker lease | Recovered on attempt 2 |
| Completion audits / stale-owner writes | One completion / rejected |
| Restored table counts and content hashes | All 24 matched |
| Restored HTTP usage / evaluation / billing | Passed |
| Separate-container restore drill duration | 8.087 s |

Application limits were 1.5 CPUs and 768 MB; database limits were one CPU and
512 MB. Resolved image IDs are in the receipt. This is a paced closed-loop
reference workload on one Docker host, not representative customer traffic,
a contracted RTO or a capacity/SLO guarantee. The five-minute read phase does
not certify long-term memory stability.

The short 1,000-event development run also passed. CI runs the same recovery
harness with 1,000 events and a 15-second read phase; those short checks must not
be substituted for the longer run above.

## Coding and billing preparation

All **18 distinct calibration tasks** were executed in network-disabled,
read-only Docker sandboxes. Their reference implementations passed **76/76**
checks; the broken implementations failed **41** checks, with at least one
failure per task. The [baseline receipt](evidence/v0.6.0/coding-baselines.json)
records task counts, outcomes, measured execution duration and image identity.
These are authored patches, not measured model-generated solutions.

The default packet contains **162 planned task runs**: three candidate slots,
three repetitions and 18 tasks. Schedule reproducibility, task uniqueness,
balanced candidate order, withheld prompt references, and rejection of ineffective
baselines are tested. Candidate models, approved budget and prices remain unset.
The expanded packet is not importable by the existing six-task recorder/viewer.

The private billing generator was run successfully. It reported missing billing
files/scope/independent controls, collection configuration and billing-owner
attestations. Tests verify private permissions, preservation of existing evidence,
missing-input handling and rejection of paths outside the packet.
No customer export or actual scheduled S3 delivery was supplied or validated.

## Application, browser and publication checks

- Fresh `uv sync --locked --python 3.13` succeeded. Local backend suite:
  **120 passed, 77 skipped**; skipped PostgreSQL and Docker checks have separate
  integration jobs, and the actual Docker recovery/baseline runs are recorded above.
- The canonical Pages build and all **three public browser journeys passed**:
  video/audio playback, chapter seeking, captions, downloads, moving solid
  circles, pause/resume, reduced motion, keyboard control, mobile overflow and
  browser policy blocking application/API and WebSocket connections.
- Desktop/mobile screenshots were captured and reviewed. The palette and
  existing narration/video remain unchanged; the download link names v0.6.0.
- Git history and allowlisted archive secret scans passed, as did whitespace
  checks. The extracted archive installed with `uv sync --locked`; its selected
  billing/coding/preparation suite passed **53 tests**, with **31 integration
  checks skipped** outside their dedicated jobs. Publication additionally
  requires successful GitHub CI and downloaded-asset checksum verification.

The release gate uses the existing Python 3.12/3.13, browser, coding sandbox,
pilot/container/restore/security, dependency audit and secret-scan jobs, with
the new reference and calibration checks added. Consult the linked release
commit's GitHub Actions results for CI evidence; local skips are not CI passes.

## Remaining acceptance

No model API calls or AWS calls were made by the new preparation/reference tools.
External API cost is **zero** for these checks; hardware and electricity cost
remain **unmeasured**. Existing saved support recordings retain their recorded
historical API estimates.

Still required: real complete billing exports and matching capture, observed
scheduled S3 delivery, exact live model choices/credentials/spending authorization,
a representative private coding holdout and collection adapter, recovery on a
new AWS/customer host, customer identity/TLS/retention/load objectives, and a
human-acknowledged alert drill. The existing hosted password-only test exception
is preserved and does not establish production MFA acceptance.
