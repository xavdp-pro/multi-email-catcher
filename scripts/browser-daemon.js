#!/usr/bin/env node
/**
 * Browser Daemon — multi-email-catcher (persistent-browser branch)
 *
 * Keeps ONE Chromium instance open for the entire Python session.
 * Python communicates via stdin/stdout using newline-delimited JSON.
 *
 * Protocol (stdin → daemon):
 *   {"id":"1", "cmd":"bing",   "query":"..."}
 *   {"id":"2", "cmd":"google", "query":"..."}
 *   {"id":"3", "cmd":"maps",   "query":"..."}
 *   {"id":"4", "cmd":"html",   "url":"..."}
 *   {"id":"5", "cmd":"quit"}
 *
 * Protocol (daemon → stdout):
 *   {"id":"1", "ok":true,  "result": [{url,title,snippet}, ...]}
 *   {"id":"3", "ok":true,  "result": "https://..."}
 *   {"id":"4", "ok":true,  "result": "<html>..."}
 *   {"id":"x", "ok":false, "error":  "message"}
 *
 * Each command opens a fresh page, then closes it — browser stays open.
 */

const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const { chromium } = require('playwright-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
chromium.use(StealthPlugin());

const log = (...a) => process.stderr.write('[daemon] ' + a.join(' ') + '\n');
const sleep = (ms) => new Promise(r => setTimeout(r, ms + Math.random() * ms * 0.15));

// ── Launch browser ────────────────────────────────────────────────────────────
const CHROMIUM_PATH = process.env.CHROMIUM_PATH || null;
const LAUNCH_OPTS = { headless: true };
if (CHROMIUM_PATH) LAUNCH_OPTS.executablePath = CHROMIUM_PATH;

let browser = null;

async function getBrowser() {
  if (!browser || !browser.isConnected()) {
    log('Launching Chromium...');
    browser = await chromium.launch(LAUNCH_OPTS);
    log('Chromium ready.');
  }
  return browser;
}

// ── Context factories ─────────────────────────────────────────────────────────
async function newPage(extraContextOpts = {}) {
  const b = await getBrowser();
  const ctx = await b.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 720 },
    locale: 'fr-FR',
    extraHTTPHeaders: { 'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7' },
    ...extraContextOpts,
  });
  const page = await ctx.newPage();
  // Cleanup helper: closes page + context
  page._cleanup = async () => { try { await ctx.close(); } catch (_) {} };
  return page;
}

// ── Bing ──────────────────────────────────────────────────────────────────────
async function cmdBing(query) {
  const page = await newPage();
  try {
    const url = `https://www.bing.com/search?q=${encodeURIComponent(query)}&setlang=fr&cc=FR`;
    log('bing:', query);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('.b_algo', { timeout: 20000 }).catch(() => {});
    await sleep(1200);

    return await page.evaluate(() => {
      const out = [], seen = new Set();
      const SKIP = ['bing.com', 'microsoft.com'];
      const containers = document.querySelectorAll('.b_algo, li.b_algo, #b_results > li');
      for (const c of containers) {
        const h2a = c.querySelector('h2 a');
        if (!h2a) continue;
        let url = '';
        const rawHref = h2a.getAttribute('href') || '';
        const uParam = rawHref.match(/[?&]u=a1([A-Za-z0-9+/=_-]+)/);
        if (uParam) {
          try {
            const b64 = uParam[1].replace(/-/g, '+').replace(/_/g, '/');
            url = atob(b64 + '==='.slice((b64.length + 3) % 4));
          } catch (_) {}
        }
        if (!url || !url.startsWith('http')) {
          const cite = c.querySelector('cite');
          if (cite) {
            const raw = cite.innerText.trim().split(/\s*›/)[0].trim();
            url = raw.startsWith('http') ? raw : 'https://' + raw;
          }
        }
        if (!url || !url.startsWith('http') || seen.has(url)) continue;
        if (SKIP.some(d => url.includes(d))) continue;
        const title = (c.querySelector('h2') || c.querySelector('h3'))?.innerText?.trim() || '';
        const snippetEl = c.querySelector('.b_caption p, .b_mtxt, .b_snippet');
        const snippet = snippetEl ? snippetEl.innerText.trim().substring(0, 200) : '';
        seen.add(url);
        out.push({ url, title, snippet });
        if (out.length >= 10) break;
      }
      return out;
    });
  } finally {
    await page._cleanup();
  }
}

// ── Google ────────────────────────────────────────────────────────────────────
const CONSENT_SELECTORS = [
  'button[id*="accept"]', 'button[aria-label*="Accept"]',
  'button[aria-label*="Tout accepter"]', 'button[aria-label*="Accepter tout"]',
  '#L2AGLb', 'form:nth-child(2) button',
];

async function acceptGoogleConsent(page) {
  for (const sel of CONSENT_SELECTORS) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.isVisible({ timeout: 1500 })) {
        await sleep(300);
        await btn.click();
        await sleep(800);
        return;
      }
    } catch (_) {}
  }
}

async function cmdGoogle(query) {
  const page = await newPage();
  try {
    const url = `https://www.google.fr/search?q=${encodeURIComponent(query)}&hl=fr&gl=fr`;
    log('google:', query);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await acceptGoogleConsent(page);
    await page.waitForSelector('div#search, div#rso, #rcnt', { timeout: 15000 }).catch(() => {});
    await sleep(400);

    return await page.evaluate(() => {
      const out = [], seen = new Set();
      const SKIP = ['google.', 'gstatic.', 'googleapis.', 'youtube.com'];
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
        if (SKIP.some(d => url.includes(d))) continue;
        const title = el.querySelector('h3')?.innerText?.trim() || '';
        const snippet = el.querySelector('.VwiC3b, .s3v9rd, .st, span[class]')
          ?.innerText?.trim()?.substring(0, 200) || '';
        seen.add(url);
        out.push({ url, title, snippet });
        if (out.length >= 10) break;
      }
      return out;
    });
  } finally {
    await page._cleanup();
  }
}

// ── Google Maps ───────────────────────────────────────────────────────────────
async function cmdMaps(query) {
  const page = await newPage();
  try {
    log('maps:', query);
    await page.goto(
      `https://www.google.com/maps/search/${encodeURIComponent(query)}`,
      { waitUntil: 'domcontentloaded', timeout: 20000 }
    );

    // Accept cookies
    const mapConsent = [
      'button:has-text("Tout accepter")', 'button:has-text("Accept all")',
      'button:has-text("Aceptar todo")', 'button:has-text("Alle akzeptieren")',
      'form[action*="consent"] button',
    ];
    for (const sel of mapConsent) {
      try {
        const btn = page.locator(sel);
        if (await btn.count() > 0) {
          await btn.first().click({ timeout: 2000 });
          await sleep(1500);
          break;
        }
      } catch (_) {}
    }

    await sleep(3500);

    const websiteUrl = await page.evaluate(() => {
      const auth = document.querySelector('a[data-item-id="authority"]');
      if (auth && auth.href && !auth.href.includes('google.com')) {
        if (auth.href.includes('url?q=')) {
          try { return new URL(auth.href).searchParams.get('q'); } catch (_) {}
        }
        return auth.href;
      }
      for (const a of document.querySelectorAll('a[href]')) {
        const label = (a.getAttribute('aria-label') || '').toLowerCase();
        const text  = (a.innerText || '').toLowerCase().trim();
        const href  = a.href || '';
        const isWeb =
          label.includes('site web') || label.includes('website') || label.includes('sitio web') ||
          label.includes('site internet') || label.includes('webseite') ||
          text.includes('site web') || text.includes('website') || text === 'site' || text === 'web';
        if (!isWeb) continue;
        if (href.includes('google.com') || href.includes('google.fr')) continue;
        if (href.includes('url?q=')) {
          try { return new URL(href).searchParams.get('q'); } catch (_) {}
        }
        if (href.startsWith('http')) return href;
      }
      return null;
    });

    return websiteUrl || 'NON_TROUVE';
  } finally {
    await page._cleanup();
  }
}

// ── Rendered HTML ─────────────────────────────────────────────────────────────
async function cmdHtml(url) {
  const page = await newPage();
  try {
    log('html:', url);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(2000);
    return await page.content();
  } finally {
    await page._cleanup();
  }
}

// ── Main loop (stdin → stdout, newline-delimited JSON) ────────────────────────
process.stdin.setEncoding('utf8');
let buffer = '';

process.stdin.on('data', chunk => { buffer += chunk; processBuffer(); });
process.stdin.on('end', async () => { await shutdown(); });

function processBuffer() {
  let nl;
  while ((nl = buffer.indexOf('\n')) !== -1) {
    const line = buffer.slice(0, nl).trim();
    buffer = buffer.slice(nl + 1);
    if (line) handleCommand(line);
  }
}

async function handleCommand(raw) {
  let req;
  try { req = JSON.parse(raw); } catch (e) {
    send({ id: null, ok: false, error: 'Invalid JSON: ' + e.message });
    return;
  }

  const { id, cmd } = req;

  if (cmd === 'quit') {
    await shutdown();
    return;
  }

  try {
    let result;
    if      (cmd === 'bing')   result = await cmdBing(req.query);
    else if (cmd === 'google') result = await cmdGoogle(req.query);
    else if (cmd === 'maps')   result = await cmdMaps(req.query);
    else if (cmd === 'html')   result = await cmdHtml(req.url);
    else throw new Error('Unknown command: ' + cmd);

    send({ id, ok: true, result });
  } catch (err) {
    log('Error on cmd', cmd, ':', err.message);
    send({ id, ok: false, error: err.message });
  }
}

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

async function shutdown() {
  log('Shutting down...');
  try { if (browser) await browser.close(); } catch (_) {}
  process.exit(0);
}

// Pre-launch the browser so first request is fast
getBrowser().then(() => {
  log('Daemon ready. Waiting for commands on stdin...');
  send({ id: null, ok: true, result: 'ready' });
}).catch(err => {
  log('Failed to launch browser:', err.message);
  process.exit(1);
});
