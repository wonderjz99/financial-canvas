const { test, expect } = require('@playwright/test');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const url = pathToFileURL(path.resolve(__dirname, '../../.local/browser/v2.html')).href;

test('V2 single company: offline years, modes, sources and analysis', async ({ page }) => {
  const errors = [], network = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => { if (/^https?:/.test(request.url())) network.push(request.url()); });
  await page.goto(url);
  await expect(page).toHaveTitle(/NEW/);
  await expect(page.locator('h1')).toContainText('New Issuer');
  await expect(page.locator('[data-company],.companies')).toHaveCount(0);
  const payload = await page.evaluate(() => Object.keys(window.__FV_REPORTS__));
  expect(payload).toEqual(['NEW']);
  for (const year of [2022, 2023, 2024, 2025, 2026]) {
    await page.locator(`[data-year="${year}"]`).click();
    await expect(page.locator('.lead')).toContainText(String(year));
    for (const basis of ['amount', 'share']) {
      await page.locator(`[data-basis="${basis}"]`).click();
      await expect(page.locator(`[data-basis="${basis}"]`)).toHaveAttribute('aria-pressed', 'true');
      const geometry = await page.evaluate(() => ({width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth}));
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.width + 1);
    }
  }
  await page.locator('.delivery-sources summary').click();
  await expect(page.locator('.delivery-sources')).toContainText('371');
  await expect(page.locator('.delivery-sources a')).not.toHaveCount(0);
  await page.locator('.profit-chart [data-fact]').first().click();
  await expect(page.locator('.detail-period')).toContainText('USD');
  await expect(page.locator('.detail a[href^="https:"]')).not.toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.locator('.analysis-entries [data-analysis="profit"]').click();
  for (const id of ['profit', 'cash_conversion', 'working_capital', 'cash_uses', 'efficiency', 'quality']) {
    await page.locator(`.analysis-nav [data-analysis="${id}"]`).click();
    await expect(page.locator('.detail')).toHaveAttribute('data-detail-section', id);
    if (id === 'cash_uses') {
      await page.locator('[data-cash-use-view="equity"]').click();
      await expect(page.locator('.detail')).not.toContainText(/期[初末]归母权益/);
    }
    const overflow = await page.locator('.detail').evaluate(node => node.scrollWidth > node.clientWidth + 1);
    expect(overflow).toBe(false);
  }
  await page.keyboard.press('Escape');
  await page.locator('[data-year="2022"]').click();
  await page.locator('.play-button').click();
  await expect(page.locator('output')).not.toHaveText('FY2022');
  await page.locator('.play-button').click();
  expect(errors).toEqual([]);
  expect(network).toEqual([]);
});
