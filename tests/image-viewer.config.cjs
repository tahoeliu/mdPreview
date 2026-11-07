const path = require('node:path');
const root = path.resolve(__dirname, '..');
const { defineConfig, devices } = require(path.join(root, 'node_modules/@playwright/test'));
module.exports = defineConfig({
  testDir: root,
  testMatch: ['tests/e2e/app.spec.js', 'tests/image-viewer.spec.js'],
  timeout: 60000, workers: 1, fullyParallel: false,
  outputDir: path.join(root, 'WorkSpace/outputs/image-viewer-run-' + require('node:crypto').randomUUID()),
  reporter: [['list'], ['json', { outputFile: path.join(root, 'WorkSpace/outputs/image-viewer-results.json') }]],
  use: { baseURL: 'http://127.0.0.1:29381', screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }, { name: 'webkit', use: { ...devices['Desktop Safari'] } }],
  webServer: { command: process.execPath + ' "' + path.join(root, 'scripts/test-server.cjs') + '"', cwd: root, url: 'http://127.0.0.1:29381', reuseExistingServer: false }
});
