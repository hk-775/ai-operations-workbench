# Narrated Workbench demo

The four-minute walkthrough follows a subscription-support task from API usage
to evaluated answers and a justified routing review. It captures the actual
authenticated team UI in an isolated PostgreSQL workspace, then shows the
interactive product and AWS architectures.

## Watch or listen

The [public player](https://hk-775.github.io/ai-operations-workbench/) and
[narrated architecture](https://hk-775.github.io/ai-operations-workbench/architecture.html)
require no installation or sign-in. They serve these same canonical frontend files
and bundled media; they have no API connection or interactive evaluation backend.

Open **Narrated demo** from either dashboard footer, or visit
`/static/demo.html` on your running Workbench application. You can also open
[`web/demo.html`](../web/demo.html) directly from the downloaded repository;
keep its adjacent scripts, styles, and `media/` directory together.

- [1080p video, with spoken narration and visible captions](../web/media/workbench-demo.mp4)
- [Standalone MP3 narration](../web/media/workbench-demo.mp3)
- [English captions: SRT](../web/media/workbench-demo.srt) · [WebVTT](../web/media/workbench-demo.vtt)
- [Full transcript](demo/TRANSCRIPT.md)
- [Storyboard](demo/storyboard.json) · [Media manifest and hashes](demo/manifest.json)
- [Audio provenance](demo/audio-provenance.json)
- [Narrated interactive architecture](../web/architecture.html)

The player has twelve chapter buttons. Starting audio pauses video, and starting
video pauses audio. Nothing autoplays. The video includes visible captions for
sharing on platforms that discard subtitle tracks; an optional English caption
track and downloadable captions are also included. Enable that optional track
only if useful, since it repeats the visible captions.

The architecture offers independent narrated flows, play/pause, restart,
narration on/off, manual steps, and solid-circle motion controls. Reduced-motion
preferences stop the circles without preventing narration. It needs no AWS
connection, model API key, company login, or speech service to play.

## What the demonstration establishes

The bundled recording contains **24 fictional support tickets × 3 models =
72 task runs and 144 saved calls**. Its API estimate is **$0.088074750**, not a
reconciled invoice. Hardware and electricity remain unmeasured. Replay makes
no new model calls. The evaluation returns **20/24, 18/24, and 14/24** ticket
passes; the strict routing review returns **No model qualifies**. The recording
does not establish today's model quality, performance on other workloads,
complete enterprise billing, or realized savings.

The source scene explains the application connector without creating or
displaying a token. No password, provider key, hosted account ID, customer
document, or hosted sign-in appears in the capture. Only temporary local
workspace identifiers and the generic test username are visible. Workbench
does not activate a production route.

The architecture portion describes the implemented single-host AWS hosted test,
including its explicit password-only sign-in exception. It is illustrative;
it neither sends live requests nor claims high availability, production MFA,
human on-call delivery, or recovery on a rebuilt host.

## Rebuild the media

Prerequisites: the locked Python and Node dependencies, Playwright Chromium,
FFmpeg with H.264/AAC/MP3 support, and a disposable PostgreSQL database. Rendering
new narration additionally requires the AWS CLI and an existing authorized
Amazon Polly session. Credentials remain in the CLI's runtime environment.

```sh
uv sync --locked
npm ci
npx playwright install chromium
```

Edit `docs/demo/storyboard.json` first. The shipped clips can be played without
any synthesis. If the narration is unchanged, skip synthesis: the shipped clips
and `docs/demo/speech-marks.json` support recording and encoding without an AWS
session. To intentionally regenerate narration:

```sh
uv run --locked python scripts/build_demo_audio.py --synthesize
```

The script limits authoring to 25,000 submitted characters, including sentence
timing requests and retries recorded in its local usage ledger. Rendering may
incur Polly charges. The stock voice is Joanna, neural, with slightly slower
speech and pronunciation hints for project names. No person's voice is cloned.
Input hashes cache unchanged clips. Requests, timing files, receipts, and raw
audio stay in ignored `artifacts/demo-build/`. Committed provenance contains
only voice settings, text/audio hashes, and durations.

Put a **disposable database URL** in a private file and point the recorder to it.
The test host creates and removes its own schema, generates an ephemeral login,
and uses a new browser context. Do not pass company credentials on the command
line or point this at a company database.

```sh
export WORKBENCH_TEST_DATABASE_URL_FILE=/path/to/private/disposable-database-url
node scripts/record_demo.mjs --check
node scripts/record_demo.mjs
uv run --locked python scripts/encode_demo.py
```

The check run verifies all scene interactions before recording. The full run
loads the saved example explicitly through the UI, runs the real replay worker,
and saves the strict review. Temporary authoring styles add a chapter heading
and captions and frame the page for video; product data and security headers
remain unchanged. All browser requests are restricted to the isolated loopback
server. No hosted instance is recorded or modified.

Encoding detects and removes a temporary corner marker to align each scene's
first caption with its narration. It trims navigation/setup footage, applies
sentence timings, produces 1920×1080 H.264/AAC video and MP3 audio, and exports captions,
chapters, poster, transcript, and hashes. The public manifest records the
application base commit and recording hash. A fresh recording run is a new
capture: timestamps and temporary identifiers may differ.

Run `npm test` for media, tour, and original local UI checks; run the existing
pilot browser suite against the disposable database for authenticated UI checks.
Review the generated screenshots and video before sharing. Source packaging
includes the final media and authoring inputs; private intermediate files stay
out of releases. Creating this media does not update an existing GitHub release
or redeploy a hosted installation.

## Publish the static player

`uv run --locked python scripts/build_pages.py` copies only the canonical player,
architecture, verified media, editable diagrams, and license into
`artifacts/pages/ai-operations-workbench`. It excludes the application, login UI,
configuration, recordings, and runtime state. The public HTML enforces
`connect-src 'none'`; media playback uses only adjacent static assets.

The Pages workflow clean-installs dependencies, builds this directory, runs its
browser suite, and publishes it from `main`. To verify the live deployment:

```sh
WORKBENCH_PAGES_URL=https://hk-775.github.io/ai-operations-workbench/ \
  npx playwright test --config=playwright.pages.config.js
```

The normal Workbench API and company sign-in retain their existing boundaries.
No synthetic user, login bypass, or browser-side evaluation mock is added.
