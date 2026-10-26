# Demo verification — 2026-10-26

The demo was captured from the actual authenticated local Workbench UI using an
isolated PostgreSQL schema and the bundled fictional support comparison.
The application base is recorded in `manifest.json`. This work adds media and
playback controls; it does not deploy a hosted stack or update an existing release.

| Area | Evidence |
|---|---|
| Product journey | Twelve scenes exercised explicit recording import, task inspection, the real offline evaluation worker, strict routing review, operations, and both architecture views |
| Saved comparison | 144 calls, 72 task runs, 24 fictional tickets, `$0.088074750` API estimate; ticket passes 20/24, 18/24, 14/24; strict review: no model qualifies |
| Backend | 80 checks passed across the backend and publication checks; two inapplicable SQLite variants skipped; PostgreSQL integration checks included |
| Browser | 23 checks passed across the original local UI, authenticated team UI, architecture, and media player |
| Playback | Real MP3 and MP4 playback, chapter seeking, captions, audio/video exclusivity, direct file access, static subdirectory hosting, and mobile layout |
| Architecture | Real bundled narration, pause/resume, restart, cancellation after view changes, stale callback protection, muted completion, missing-audio fallback, keyboard controls, and reduced motion |
| Media | 1920×1080 H.264/AAC, 30 fps, twelve chapters, standalone MP3, visible captions, SRT/WebVTT, transcript, and matching provenance hashes |
| Synchronization | Each scene is anchored to a temporary capture marker that is removed in encoding; exact frame counts keep chapter boundaries aligned with the audio |
| Visual review | Reviewed the product scenes, both diagrams, the opening caption, and desktop/mobile player screenshots; solid-circle movement remains visible in the encoded video |

Tests use separate disposable schemas and generated credentials. No hosted sign-in
was captured, no company workspace was modified, and no model inference was run.
Narration is a previously rendered stock Amazon Polly voice; normal playback and
re-recording with the shipped clips/timings need no speech-service connection.

Intermediate captures, private database settings, and test receipts remain under
ignored paths. Only the final media, authored inputs, transcript, and portable
provenance belong in the source distribution. See `../DEMO.md` for rebuild commands
and the limits of the demonstrated evidence.
