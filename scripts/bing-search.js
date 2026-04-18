#!/usr/bin/env node
/**
 * Bing Search Script — multi-email-catcher
 *
 * Usage:
 *   NO_PROXY=true node scripts/bing-search.js "COMPANY NAME site officiel"
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

const log = (...args) => process.stderr.write('[bing-search] ' + args.join(' ') + '\n');

const sleep = (ms) => new Promise(r => setTimeout(r, ms + Math.random() * ms * 0.2));

async function extractResults(page) {
  await page.waitForSelector('.b_algo', { timeout: 20000 }).catch(() => { });
  await sleep(1500);

  return await page.evaluate(() => {
    const out = [];
    const seen = new Set();
    const SKIP_DOMAINS = ['bing.com', 'microsoft.com'];

    let containers = document.querySelectorAll('.b_algo');
    if (!containers.length) containers = document.querySelectorAll('li.b_algo, #b_results > li');

    for (const container of containers) {
      const h2a = container.querySelector('h2 a');
      if (!h2a) continue;

      // Bing encodes URLs in "u=a1BASE64URL" parameter
      let url = '';
      const rawHref = h2a.getAttribute('href') || '';
      const uParam = rawHref.match(/[?&]u=a1([A-Za-z0-9+/=_-]+)/);
      if (uParam) {
        try {
          const b64 = uParam[1].replace(/-/g, '+').replace(/_/g, '/');
          const padded = b64 + '==='.slice((b64.length + 3) % 4);
          url = atob(padded);
        } catch (e) { }
      }
      if (!url || !url.startsWith('http')) {
        const cite = container.querySelector('cite');
        if (cite) {
          const raw = cite.innerText.trim().split(/\s*›/)[0].trim();
          url = raw.startsWith('http') ? raw : 'https://' + raw;
        }
      }
      if (!url || !url.startsWith('http') || seen.has(url)) continue;
      if (SKIP_DOMAINS.some(d => url.includes(d))) continue;

      const title = (container.querySelector('h2') || container.querySelector('h3'))?.innerText?.trim() || '';
      const snippetEl = container.querySelector('.b_caption p, .b_mtxt, .b_snippet');
      const snippet = snippetEl ? snippetEl.innerText.trim().substring(0, 200) : '';

      seen.add(url);
      out.push({ url, title, snippet });
      if (out.length >= 10) break;
    }
    return out;
  });
}

async function bingSearch(query) {
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
    const searchUrl = `https://www.bing.com/search?q=${encodeURIComponent(query)}&setlang=fr&cc=FR`;
    log('Navigating to:', searchUrl);
    await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

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
  console.error('Usage: node bing-search.js "search query"');
  process.exit(1);
}
bingSearch(query);
