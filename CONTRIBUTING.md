# Contributing

Start with an issue describing the problem and a small, reproducible example.
The [roadmap](docs/ROADMAP.md) separates the current support demonstration from
future connectors, coding workloads, and company-wide operations.

## Local development

```bash
git clone https://github.com/hk-775/ai-operations-workbench.git
cd ai-operations-workbench
uv sync --locked --python 3.13
uv run --locked pytest -q
```

For browser changes, install Node 22, then run:

```bash
npm ci
npx playwright install chromium
npm test
npx playwright test --config=playwright.pilot.config.js
```

Browser tests start their own server and temporary ledger. They replay the
bundled recording without provider credentials or new model calls.
Pilot checks use isolated test schemas when `WORKBENCH_TEST_DATABASE_URL_FILE`
points to a dedicated PostgreSQL test database. See [PILOT.md](docs/PILOT.md).
For container changes, run `uv run --locked python scripts/check_pilot_stack.py`
against the local pilot stack. It tests bootstrap, evaluation, and backup restore
in temporary databases; CI runs the same check.

Run the app with `uv run --locked uvicorn workbench.app:app --host 127.0.0.1 --port 8767`.
See [README.md](README.md) for the guided workflow.

## Evidence and behavior

- Keep model recordings immutable. A grader change needs a focused regression
  test and an explanation of any changed result.
- Keep synthetic fixtures labeled. Do not invent usage, invoices, performance,
  savings, or integration status.
- Preserve Decimal cost arithmetic, unknown costs, failed-case denominators,
  deduplication, and the rule that critical failures exclude a model.
- Keep replay offline. New live collection must remain a separate, explicit,
  bounded operation.
- Do not activate production routing through this local demonstration.
- Preserve pilot role/source boundaries, job fencing and restart persistence.
  Never treat fixtures as a measured routing recommendation.
- Use the shared stage colors and preserve keyboard access, mobile layouts,
  pause controls, and reduced-motion behavior.

Commit dependency changes together with the relevant lockfile. CI must install
with `uv sync --locked` and `npm ci`. Explain the change and its validation in
the pull request; do not include private recordings or generated local state.

Contributions are provided under the project's [MIT-0 license](LICENSE).
