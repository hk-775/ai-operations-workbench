import {defineConfig} from '@playwright/test';
import {randomBytes} from 'node:crypto';

const port = process.env.WORKBENCH_PILOT_TEST_PORT || '18770';
const baseURL = `http://127.0.0.1:${port}`;
process.env.WORKBENCH_BROWSER_PASSWORD ||= randomBytes(24).toString('base64url');

export default defineConfig({
  testDir:'./tests/pilot-browser',
  timeout:45000,
  workers:1,
  use:{baseURL, headless:true, viewport:{width:1440,height:1050}},
  webServer:{
    command:'uv run --locked python tests/pilot_server.py',
    url:baseURL,
    reuseExistingServer:false,
    env:{WORKBENCH_PILOT_TEST_PORT:port, WORKBENCH_BROWSER_PASSWORD:process.env.WORKBENCH_BROWSER_PASSWORD}
  }
});
