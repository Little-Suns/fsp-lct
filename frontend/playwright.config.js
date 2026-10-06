// E2E фронта: Playwright поднимает бэкенд сам (e2e/server.sh — база fsp_e2e, пересев, DEMO=1),
// тесты идут последовательно в одном воркере: сценарии меняют общее состояние базы.
const { defineConfig, devices } = require('@playwright/test');

const PORT = process.env.E2E_PORT || '8010';
process.env.E2E_PORT = PORT;

module.exports = defineConfig({
  testDir: './e2e',
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  globalSetup: './e2e/global-setup.js',
  globalTeardown: './e2e/global-teardown.js',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'ru-RU',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'sh e2e/server.sh',
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
