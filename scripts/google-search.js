#!/usr/bin/env node
/**
 * Google Search Script — multi-email-catcher
 *
 * Usage:
 *   NO_PROXY=true node scripts/google-search.js "COMPANY NAME site officiel"
 *
 * Output:
 *   JSON array on stdout  → [{url, title, snippet}, ...]
 *   Logs on stderr
 */

const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
chromium.use(StealthPlugin());

const log = (...args) => process.stderr.write('[google-search] ' + args.join(' ') + '\n');
const sleep = (ms) => new Promise(r => setTimeout(r, ms + Math.random() * ms * 0.2));

const CONSENT_SELECTORS = [
  'button[id*="accept"]',
  'button[aria-label*="Accept"]',
  'button[aria-label*="Tout accepter"]',
  'button[aria-label*="Accepter tout"]',
  '#L2AGLb',
  'form:nth-child(2) button',
];

async function acceptConsent(page) {
  for (const sel of CONSENT_SELECTORS) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.isVisible({ timeout: 2000 })) {
        await sleep(400);
        await btn.click();
        log('Cookie consent accepted');
        await sleep(1000);
        return;
      }
    } catch (_) {}
  }
}

async function extractResults(page) {
  await page.waitForSelector('div#search, div#rso, #rcnt', { timeout: 15000 }).catch(() => {});
  await sleep(500);

  return await page.evaluate(() => {
    const out = [];
    const seen = new Set();
    const SKIP_DOMAINS = ['google.', 'gstatic.', 'googleapis.', 'youtube.com'];

    // Multiple selector strategies for robustness
    const containers = [
      ...document.querySelectorAll('div#search div.g'),
      ...document.querySelectorAll('div#rso div.g'),
      ...document.querySelectorAll('div#search .tF2Cxc'),
    ];

    for (const el of containers) {
      const a = el.querySelector('a[href]');
      if (!a) continue;
      let url = a.href || '';
      if (!url.startsWith('http') || seen.has(url)) continue;
      if (SKIP_DOMAINS.some(d => url.includes(d))) continue;

      const title = el.querySelector('h3')?.innerText?.trim() || '';
      const snippet = el.querySelector('.VwiC3b, .s3v9rd, .st, span[class]')?.innerText?.trim()?.substring(0, 200) || '';

      seen.add(url);
      out.push({ url, title, snippet });
      if (out.length >= 10) break;
    }
    return out;
  });
}

async function googleSearch(query) {
  const CHROMIUM_PATH = process.env.CHROMIUM_PATH || null;
  const launchOptions = { headless: true };
  if (CHROMIUM_PATH) launchOptions.executablePath = CHROMIUM_PATH;

  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 720 },
    locale: 'fr-FR',
    extraHTTPHeaders: { 'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7' },
  });
  const page = await context.newPage();

  try {
    const searchUrl = `https://www.google.fr/search?q=${encodeURIComponent(query)}&hl=fr&gl=fr`;
    log('Navigating to:', searchUrl);
    await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

    await acceptConsent(page);

    const results = await extractResults(page);
    log(`Found ${results.length} results`);
    console.log(JSON.stringify(results, null, 2));
  } catch (err) {
    log('Error:', err.message);
    console.log('[]');
  } finally {
    await browser.close();
  }
}

const query = process.argv[2];
if (!query) {
  console.error('Usage: node google-search.js "search query"');
  process.exit(1);
}
googleSearch(query);
