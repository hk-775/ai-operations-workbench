# Workbench 0.3.0 local verification

Checks performed on **October 27, 2026**, on an Apple Silicon development host.
These results describe the release candidate and bundled example; they do not
establish customer capacity, general model quality, or availability guarantees.

| Check | Result |
|---|---|
| Locked installation | Fresh Python 3.13 and Node 22 environments; dependency versions unchanged |
| Backend, including PostgreSQL | 81 passed; two inapplicable SQLite variants skipped |
| Extracted source archive | Fresh locked installation; 81 backend checks passed, two skipped |
| Local application and media | 13 browser checks passed |
| Authenticated PostgreSQL pilot | 10 browser checks passed |
| Exact public build | Three browser checks passed under the repository path prefix |
| Public media | Actual MP4/MP3 playback, seeking, captions, chapter navigation, and downloads |
| Narrated architecture | Real audio, pause/resume/restart, moving solid circles, keyboard selection, and reduced motion |
| Public network boundary | Browser policy blocked attempted API and WebSocket connections |
| Artifact privacy | Contaminated-checkout tests excluded private files and rejected modified media |
| Visual review | Desktop and mobile screenshots inspected; no page-level horizontal overflow |
| Secret scanning | Git history, extracted source archive, and static public output passed Gitleaks |

Local media tests used the real bundled files with the isolated test browser's
audio output disabled to avoid a host audio-device stall. They did not replace
the media decoder or simulate playback time. Linux CI uses the normal headless
Chromium configuration.

The public site contains the canonical demo and architecture, adjacent media,
editable/static diagrams, publication metadata, and the license. It contains no
application backend or login bypass. Existing authenticated tests continue to
exercise roles, sessions, source boundaries, and protected Operations access.

The packaged recording is unchanged: 144 saved calls, `$0.088074750` in captured
API estimates, and 20/24, 18/24, and 14/24 case passes. The default review still
returns **No model qualifies**. Verification makes no paid model calls.

The source archive's attached `SHA256SUMS` identifies the exact published bytes.
The repository's CI and Pages workflows provide separate records of clean Linux
builds, container/restore checks, vulnerability scans, and static publication.
The earlier [hosted acceptance report](VERIFICATION-HOSTED-2026-10-26.md) retains
its original date and scope; a release update does not turn that test into a
high-availability or production-MFA claim.
