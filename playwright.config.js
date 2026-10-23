import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const port = process.env.WORKBENCH_TEST_PORT || '18769';
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests/browser',
  timeout: 45000,
  workers: 1,
  use: {baseURL, headless: true, viewport: {width: 1440, height: 1050}},
  webServer: {
    command: `uv run --locked uvicorn workbench.app:app --host 127.0.0.1 --port ${port}`,
    url: baseURL,
    reuseExistingServer: false,
    env: {WORKBENCH_STATE_DIR: mkdtempSync(join(tmpdir(), 'workbench-browser-'))}
  }
});
