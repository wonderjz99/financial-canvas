const { defineConfig } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const marker = path.resolve(__dirname, 'PUBLIC_RELEASE.json');
const isPublic = fs.existsSync(marker) && JSON.parse(fs.readFileSync(marker, 'utf8')).profile === 'financial-visualizer-v2-public';
const v2Only = process.env.FV_TEST_SCOPE === 'v2' || isPublic;

module.exports = defineConfig({
  testDir: './tests/browser',
  globalSetup: v2Only ? './tests/browser/v2-global-setup.cjs' : './tests/browser/global-setup.cjs',
  ...(v2Only ? { testMatch: '**/v2.spec.cjs' } : {}),
  timeout: 60000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 2,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    browserName: 'chromium',
    offline: true,
    reducedMotion: 'reduce',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.FV_BROWSER_CHANNEL ? { channel: process.env.FV_BROWSER_CHANNEL } : {},
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 950 } } },
    { name: 'mobile-390', use: { viewport: { width: 390, height: 844 } } },
    { name: 'mobile-320', use: { viewport: { width: 320, height: 844 } } },
  ],
});
