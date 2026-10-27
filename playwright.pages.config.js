import {defineConfig} from '@playwright/test';

const live = process.env.WORKBENCH_PAGES_URL;
const port = process.env.WORKBENCH_PAGES_TEST_PORT || '18771';
export default defineConfig({
  testDir: './tests/pages-browser',
  timeout: 45000,
  workers: 1,
  use: {
    baseURL: live || `http://127.0.0.1:${port}/ai-operations-workbench/`,
    headless: true,
    viewport: {width: 1440, height: 1000},
  },
  webServer: live ? undefined : {
    command: `uv run --locked python tests/pages_server.py --port ${port}`,
    url: `http://127.0.0.1:${port}/ai-operations-workbench/`,
    reuseExistingServer: false,
  },
});
