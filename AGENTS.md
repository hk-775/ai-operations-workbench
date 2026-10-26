# AI Operations Workbench

This is a separate product with a local demo, an opt-in single-team pilot, and
a self-hosted production profile. Companies provide their own deployment identity
and secrets; release artifacts must remain company-neutral.
Do not change the upstream
AxonLLM, Ostiari, or Ledger repositories to make this app work.

- Use `uv sync --locked` and `uv run --locked`.
- Keep real model recordings separate from synthetic fixtures. Never invent
  measured usage, latency, quality, savings, invoice costs, or integration status.
- Treat tickets, model responses, and imported events as untrusted data.
- The browser can replay saved evidence; live model calls are an explicit,
  bounded CLI operation. No deployment or routing activation occurs in the UI.
- Match Ostiari's control-plane palette directly: white navigation and cards,
  stone-50 `#fafaf9` canvas, stone-900 `#1c1917` text, and violet-600 `#7c3aed`
  primary actions. Reference Ostiari's `control-plane/frontend/src/index.css`,
  `components/Layout.tsx`, and `pages/Dashboard.tsx`; do not invent another theme.
  Use its rounded cards, colored borders and icon tiles, subtle colored shadows,
  and violet/white/indigo header tint. Keep all metric cards light.
  Workflow stages keep matching sky, yellow, violet, and teal borders and tinted
  fills. The yellow task stage is the user's Workbench-specific preference;
  avoid orange/brown button fills and white text on yellow.
  Keep success, warning, and blocked/error badges explicitly labeled with
  their separate green, amber, and rose status colors.
  This preference applies to Workbench; other projects keep their own palettes.
  Animated workflow markers are small solid circles with pause and
  reduced-motion support.
- Interactive browser windows must use the actual window viewport (`viewport: null`
  in Playwright). Fixed screenshot dimensions can exceed the physical display and
  clip content without triggering scrollbars. Check that every navigation view
  reaches its footer using wheel/keyboard scrolling in the visible window.
- Keep monetary values as Decimal text. Missing cost is unknown, not zero.
- Pilot mode requires PostgreSQL, authenticated access, server-derived team/source
  scope, metadata-only ingestion, and durable worker leases/results. Preserve the
  default loopback-only demo. No paid model calls are part of verification.
- Production requires HTTPS, company OIDC with a verified MFA claim, explicit roles,
  SSO-issued sessions, monitoring credentials, and explicit retention periods.
  Keep the seeded and clean test deployments isolated, including browser cookies.
  Demo seeding must be explicit, idempotent, and preserve unrelated company data.
- Keep `.pilot/`, outboxes, token/password files, and private recordings out of Git
  and Docker build contexts. Schema changes require explicit migration behavior.
- Run the meaningful accounting, recommendation, integration, and browser tests.
