import { defineConfig } from '@playwright/test'

// Only disposable synthetic fixtures are included in the public browser suite.
// Build apps/web before running this config. Never reuse the user's local server.
export default defineConfig({
  testDir: './apps/web/e2e',
  testMatch: '**/synthetic-notifications.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 0,
  outputDir: 'test-results/synthetic-browser',
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:18765',
    httpCredentials: { username: 'synthetic-browser-user', password: 'synthetic-browser-password' },
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python -m uvicorn browser_fixture:app --app-dir apps/api/tests --host 127.0.0.1 --port 18765',
    env: { CONTROL_CENTER_BROWSER_FIXTURE: '1' },
    url: 'http://127.0.0.1:18765/__fixture__/health',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
