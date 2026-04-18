#!/usr/bin/env node
/**
 * Google Maps Website Extractor — multi-email-catcher
 *
 * Usage:
 *   node scripts/google-maps-website.js "COMPANY NAME CITY"
 *
 * Output:
 *   URL on stdout (or "NON_TROUVE")
 */

const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
chromium.use(StealthPlugin());

const query = process.argv[2];
if (!query) {
  console.error('No query provided');
  process.exit(1);
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const CHROMIUM_PATH = process.env.CHROMIUM_PATH || null;
  const launchOptions = { headless: true };
  if (CHROMIUM_PATH) launchOptions.executablePath = CHROMIUM_PATH;

  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 720 },
    locale: 'fr-FR',
  });
  const page = await context.newPage();

  try {
    await page.goto(
      `https://www.google.com/maps/search/${encodeURIComponent(query)}`,
      { waitUntil: 'domcontentloaded', timeout: 20000 }
    );

    // Accept cookies if shown
    const consentSelectors = [
      'button:has-text("Tout accepter")',
      'button:has-text("Accept all")',
      'button:has-text("Aceptar todo")',
      'button:has-text("Alle akzeptieren")',
      'form[action*="consent"] button',
    ];
    for (const sel of consentSelectors) {
      try {
        const btn = page.locator(sel);
        if (await btn.count() > 0) {
          await btn.first().click({ timeout: 2000 });
          await sleep(2000);
          break;
        }
      } catch (_) {}
    }

    await sleep(4000);

    const websiteUrl = await page.evaluate(() => {
      const links = document.querySelectorAll('a[href]');
      for (const a of links) {
        const label = (a.getAttribute('aria-label') || '').toLowerCase();
        const text  = (a.innerText || '').toLowerCase().trim();
        const dataItem = (a.getAttribute('data-item-id') || '').toLowerCase();
        const href  = a.href || '';

        const isWebsite =
          dataItem === 'authority' ||
          label.includes('site web') || label.includes('website') || label.includes('sitio web') ||
          label.includes('visitar el sitio') || label.includes('visit the website') ||
          label.includes('site internet') || label.includes('webseite') ||
          text.includes('site web') || text.includes('sitio web') || text.includes('website') ||
          text === 'site' || text === 'web';

        if (!isWebsite) continue;
        if (href.includes('google.com') || href.includes('google.fr')) continue;

        if (href.includes('url?q=')) {
          try { return new URL(href).searchParams.get('q'); } catch (_) {}
        }
        if (href.startsWith('http')) return href;
      }

      // Fallback: data-item-id="authority"
      const auth = document.querySelector('a[data-item-id="authority"]');
      if (auth && auth.href) {
        if (auth.href.includes('url?q=')) {
          try { return new URL(auth.href).searchParams.get('q'); } catch (_) {}
        }
        if (!auth.href.includes('google.com')) return auth.href;
      }
      return null;
    });

    console.log(websiteUrl || 'NON_TROUVE');
  } catch (err) {
    process.stderr.write('Error: ' + err.message + '\n');
    console.log('NON_TROUVE');
  } finally {
    await browser.close();
  }
})();
