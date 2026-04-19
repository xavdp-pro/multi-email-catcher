#!/usr/bin/env node
/**
 * Rendered HTML Fetcher — multi-email-catcher
 *
 * Loads a URL with a headless Chromium (Playwright Stealth), waits 2s for JS to execute,
 * then outputs the full rendered HTML on stdout.
 *
 * Usage:
 *   node scripts/get-rendered-html.js "https://example.com"
 */

const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
chromium.use(StealthPlugin());

const url = process.argv[2];
if (!url) {
  console.error('No URL provided');
  process.exit(1);
}

(async () => {
  const CHROMIUM_PATH = process.env.CHROMIUM_PATH || null;
  const launchOptions = { headless: true };
  if (CHROMIUM_PATH) launchOptions.executablePath = CHROMIUM_PATH;

  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 720 },
  });
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // Wait for JS frameworks (React, Vue, Angular) to render
    await new Promise((r) => setTimeout(r, 2000));
    const html = await page.content();
    console.log(html);
  } catch (err) {
    process.stderr.write('Error loading page: ' + err.message + '\n');
  } finally {
    await browser.close();
  }
})();
