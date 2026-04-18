import os
import re
import csv
import sys
import json
import time
import random
import threading
import unicodedata
import requests
import gspread
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from groq import Groq

load_dotenv(".env")

# ── Persistent browser daemon ─────────────────────────────────────────────────
class BrowserDaemon:
    """
    Spawns `scripts/browser-daemon.js` once and keeps it alive.
    All Playwright operations go through this single Chromium process,
    eliminating the ~3s browser startup cost per request.
    """

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self._counter = 0

    def start(self):
        if self._proc and self._proc.poll() is None:
            return
        print("  🚀 Starting browser daemon...")
        self._proc = subprocess.Popen(
            ["node", "scripts/browser-daemon.js"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env={**os.environ, "NO_PROXY": "true"},
        )
        # Start stderr forwarder thread
        threading.Thread(target=self._forward_stderr, daemon=True).start()
        # Wait for "ready" signal
        ready_line = self._proc.stdout.readline()
        try:
            msg = json.loads(ready_line)
            if msg.get("result") == "ready":
                print("  ✅ Browser daemon ready.")
        except Exception:
            pass

    def _forward_stderr(self):
        for line in self._proc.stderr:
            print(" ", line.rstrip(), flush=True)

    def call(self, cmd: dict, timeout: int = 45) -> dict:
        """Send a command and wait for its response."""
        with self._lock:
            self._counter += 1
            req_id = str(self._counter)
            cmd["id"] = req_id
            line = json.dumps(cmd) + "\n"
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

            deadline = time.time() + timeout
            while time.time() < deadline:
                out = self._proc.stdout.readline()
                if not out:
                    raise RuntimeError("Browser daemon stdout closed unexpectedly")
                try:
                    msg = json.loads(out)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == req_id:
                    return msg
            raise TimeoutError(f"Browser daemon timeout for command: {cmd}")

    def bing(self, query: str) -> list:
        try:
            r = self.call({"cmd": "bing", "query": query})
            return r["result"] if r.get("ok") else []
        except Exception as e:
            print(f"  ⚠️  Bing daemon error: {e}")
            return []

    def google(self, query: str) -> list:
        try:
            r = self.call({"cmd": "google", "query": query})
            return r["result"] if r.get("ok") else []
        except Exception as e:
            print(f"  ⚠️  Google daemon error: {e}")
            return []

    def maps(self, query: str) -> str | None:
        try:
            r = self.call({"cmd": "maps", "query": query}, timeout=35)
            url = r.get("result") if r.get("ok") else None
            return url if url and url != "NON_TROUVE" else None
        except Exception as e:
            print(f"  ⚠️  Maps daemon error: {e}")
            return None

    def html(self, url: str, timeout: int = 25) -> str:
        try:
            r = self.call({"cmd": "html", "url": url}, timeout=timeout)
            return r["result"] if r.get("ok") else ""
        except Exception as e:
            print(f"  ⚠️  HTML daemon error: {e}")
            return ""

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(json.dumps({"id": "quit", "cmd": "quit"}) + "\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()


DAEMON = BrowserDaemon()

# ── LLM config ────────────────────────────────────────────────────────────────
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL_PRIMARY  = "llama-3.3-70b-versatile"       # 100K tokens/day (free)
MODEL_FALLBACK = "meta-llama/llama-4-scout-17b-16e-instruct"  # 500K tokens/day (free)
MODEL_FALLBACK2 = "llama-3.1-8b-instant"         # 500K tokens/day (free)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Blacklists ─────────────────────────────────────────────────────────────────
EMAIL_BLACKLIST = {
    "sentry.io", "example.com", "yourdomain", "domain.com",
    ".png", ".jpg", ".svg", ".gif", ".css", ".js",
    "wix.com", "google.com", "facebook.com", "twitter.com", "linkedin.com",
    "sentry-next.wixpress.com",
    "pappers.fr", "societe.com", "infogreffe.fr", "verif.com",
    "manageo.fr", "societe.ninja", "entreprises.lefigaro.fr",
    "annuaire-entreprises.data.gouv.fr", "kompass.com",
    "corporama.com", "datainfogreffe.fr", "bizliste.com",
}

ANNUAIRE_DOMAINS = {
    "pappers.fr", "societe.com", "infogreffe.fr", "verif.com",
    "manageo.fr", "societe.ninja", "entreprises.lefigaro.fr",
    "annuaire-entreprises.data.gouv.fr", "kompass.com", "corporama.com",
    "datainfogreffe.fr", "bizliste.com", "societeinfo.com", "dirigeant.eu",
    "fr.kompass.com", "europages.fr", "pagesjaunes.fr", "118000.fr",
    "118712.fr", "cylex.fr", "yelp.fr", "juripredis.com", "assoce.fr",
    "bce.fgov.be", "societe-historique.fr",
}

_SOCIAL_DOMAINS = {
    "facebook.com", "linkedin.com", "twitter.com", "youtube.com",
    "wikipedia.org", "ameli.fr", "wixsite.com", "assoce.fr",
    "instagram.com", "tiktok.com",
}

# ── Name normalisation ─────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

LEGAL_FORMS = re.compile(
    r"\b(SAS|SARL|SASU|EURL|SNC|SC|SCI|SEP|GIE|GIP|SCOP|SELARL|SELA|SLP"
    r"|S\.A\.S\.?|S\.A\.R\.L\.?|S\.N\.C\.?|S\.C\.I\.?"
    r"|SAS\s+à\s+associé\s+unique|société\s+nouvelle"
    r"|association|groupement)\b",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """Strip legal suffixes/prefixes for cleaner search queries."""
    cleaned = name
    temp = re.sub(r"\bSA\b", "", cleaned, flags=re.IGNORECASE).strip()
    if len(temp) >= 3:
        cleaned = temp
    cleaned = LEGAL_FORMS.sub(" ", cleaned)
    cleaned = re.sub(r"(?<=[A-Za-z0-9])\.(?=[A-Za-z0-9])", " ", cleaned)
    cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if len(cleaned) >= 2 else name.strip()


def _normalize_for_match(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode("ascii")


# ── LLM ───────────────────────────────────────────────────────────────────────
def llm(prompt: str) -> str:
    for model in [MODEL_PRIMARY, MODEL_FALLBACK, MODEL_FALLBACK2]:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                print(f"  ⚠️  Rate limit {model}, trying next model...")
                continue
            raise
    raise RuntimeError("All Groq models are rate-limited. Try again later.")


# ── API gouvernementale française ─────────────────────────────────────────────
def lookup_siren_api(siren: str):
    """
    French government API (no key needed).
    Returns (site_url_or_None, adresse_postale_or_empty_string).
    """
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siren}&page=1&per_page=1"
        r = requests.get(url, headers=HEADERS, timeout=10)
        results = r.json().get("results", [])
        if not results:
            return None, ""
        ent = results[0]
        site = ent.get("site_web") or ent.get("url") or None
        if not site:
            # Scan all string fields for a URL (rarely present but worth checking)
            for v in ent.values():
                if isinstance(v, str) and v.startswith("http") and "." in v:
                    site = v
                    break
        siege = ent.get("siege", {})
        adresse = " ".join(filter(None, [
            siege.get("adresse"), siege.get("code_postal"), siege.get("commune")
        ]))
        return site, adresse
    except Exception:
        return None, ""


# ── Search helpers ─────────────────────────────────────────────────────────────
def _run_search_engine(engine: str, query: str, timeout: int = 45) -> list:
    if engine == "bing":
        return DAEMON.bing(query)
    return DAEMON.google(query)


def _search_results_relevant(query: str, results: list) -> bool:
    """Returns False when results look like anti-bot garbage (unrelated to query)."""
    if not results:
        return True
    skip = {"site", "officiel", "contact", "email", "adresse", "rue", "boulevard",
            "avenue", "chemin", "place", "les", "des", "sur", "pour", "par",
            "avec", "dans", "qui", "que", "est", "une", "aux"}
    keywords = [w.lower().strip('"') for w in query.split()
                if len(w.strip('"')) >= 3 and w.lower().strip('"') not in skip]
    if not keywords:
        return True
    for r in results:
        text = (r.get("title", "") + " " + r.get("snippet", "") + " " + r.get("url", "")).lower()
        if any(kw in text for kw in keywords):
            return True
    return False


def _search_with_fallback(query: str, label: str = "") -> list:
    """Tries Bing first, falls back to Google if results are irrelevant."""
    pause = random.uniform(2, 5)
    print(f"  -> {label}Bing: {query}  (pause {pause:.1f}s)")
    time.sleep(pause)

    results = _run_search_engine("bing", query)
    if results and _search_results_relevant(query, results):
        print(f"     → {len(results)} Bing results")
        return results

    if results:
        print(f"     ⚠️  Bing results off-topic, falling back to Google...")
    else:
        print(f"     → 0 Bing results, falling back to Google...")

    pause2 = random.uniform(2, 4)
    print(f"  -> {label}Google: {query}  (pause {pause2:.1f}s)")
    time.sleep(pause2)

    results_g = _run_search_engine("google", query)
    if results_g and _search_results_relevant(query, results_g):
        print(f"     → {len(results_g)} Google results")
        return results_g
    if results_g:
        print(f"     ⚠️  Google results also off-topic")

    return results_g if results_g else results


# ── Heuristic (no LLM) ────────────────────────────────────────────────────────
def _pick_first_result_heuristic(name: str, results: list):
    """
    Returns the first non-directory result whose domain/title contains
    the company name — WITHOUT calling the LLM.
    Skips short/generic names (≤ 5 chars, single word) to avoid false positives.
    """
    clean_norm = _normalize_for_match(normalize_name(name))
    words = [w for w in clean_norm.split() if len(w) >= 3]
    if not words or (len(words) == 1 and len(words[0]) <= 5):
        return None

    excluded = ANNUAIRE_DOMAINS | _SOCIAL_DOMAINS
    for r in results:
        url   = r.get("url", "")
        title = _normalize_for_match(r.get("title", ""))
        domain = _normalize_for_match(urlparse(url).netloc)
        if not url.startswith("http"):
            continue
        if any(d in url for d in excluded):
            continue
        matched = sum(1 for w in words if w in title or w in domain)
        if matched >= max(1, len(words) // 2):
            return url
    return None


# ── LLM site picker ───────────────────────────────────────────────────────────
def llm_pick_official_site(name: str, siren: str, search_results: list):
    if not search_results:
        return None
    filtered = [r for r in search_results
                if not any(d in r.get("url", "") for d in ANNUAIRE_DOMAINS)]
    if not filtered:
        return None
    snippets = "\n".join(
        f"- {r['url']} | {r['title']} | {r.get('snippet', '')}" for r in filtered
    )
    prompt = (
        f"Company: {name} (SIREN: {siren}).\n"
        f"Search results:\n{snippets}\n\n"
        "Find the OFFICIAL website URL. Exclude directories and aggregators. "
        "Reply with just the http URL. If not found reply 'NOT_FOUND'."
    )
    try:
        res = llm(prompt)
        m = re.search(r"https?://[^\s'\"<>]+", res)
        return m.group(0) if m else None
    except Exception as e:
        print(f"  ⚠️  LLM error (pick site): {e}")
        return None


# ── Google Maps ───────────────────────────────────────────────────────────────
def lookup_google_maps(query: str):
    url = DAEMON.maps(query)
    if url and url.startswith("http"):
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") or url
    return None


# ── Find official site ────────────────────────────────────────────────────────
def find_official_site(name: str, siren: str):
    """
    Strategy cascade:
      S0 → French government API (SIREN)
      S1 → Google Maps (most reliable, no LLM)
      S2 → Bing/Google + heuristic (no LLM)
      S3 → Bing/Google + LLM fallback
      S4 → Bing/Google + postal address
    """
    clean = normalize_name(name)

    # S0: Government API
    print("  -> French government API (SIREN)...")
    api_site, adresse = lookup_siren_api(siren)
    if api_site and not any(d in api_site for d in ANNUAIRE_DOMAINS):
        print(f"  ✅ Site from government API: {api_site}")
        return api_site

    # S1: Google Maps
    maps_query = f"{clean} {adresse}" if adresse else clean
    print(f"  -> Google Maps: {maps_query}")
    maps_site = lookup_google_maps(maps_query)
    if maps_site:
        print(f"  ✅ Site from Google Maps: {maps_site}")
        return maps_site

    # S2 + S3: Bing/Google search
    queries = [
        f"{clean} site officiel",
        f'"{clean}" {siren}',
    ]
    for i, q in enumerate(queries, 1):
        results = _search_with_fallback(q, f"#{i} ")
        if not results:
            continue
        site = _pick_first_result_heuristic(name, results)
        if site:
            print(f"     ✅ Direct heuristic (no LLM): {site}")
            return site
        site = llm_pick_official_site(name, siren, results)
        if site:
            return site

    # S4: Bing/Google + postal address
    if adresse:
        print(f"  -> Search by postal address: {adresse}")
        results = _search_with_fallback(f'{clean} "{adresse}" site', "addr ")
        if results:
            site = _pick_first_result_heuristic(name, results)
            if site:
                print(f"     ✅ Direct heuristic (no LLM): {site}")
                return site
            site = llm_pick_official_site(name, siren, results)
            if site:
                return site

    return None


# ── HTML / email helpers ──────────────────────────────────────────────────────
def fetch_rendered_html(url: str, timeout: int = 25) -> str:
    return DAEMON.html(url, timeout=timeout)


def _clean_emails(found: list) -> list:
    out, seen = [], set()
    for e in found:
        e = e.strip().strip(".").strip(",").lower()
        if not e or e in seen:
            continue
        if any(b in e for b in EMAIL_BLACKLIST):
            continue
        seen.add(e)
        out.append(e)
    return out


def extract_emails(html: str, page_text: str) -> str | None:
    """Extract emails via mailto tags, HTML regex, and text regex — no LLM."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for tag in soup.find_all("a", href=True):
        if tag["href"].lower().startswith("mailto:"):
            found.append(tag["href"][7:].split("?")[0])
    found.extend(EMAIL_RE.findall(html))
    found.extend(EMAIL_RE.findall(page_text))
    cleaned = _clean_emails(found)
    return ", ".join(cleaned) if cleaned else None


FALLBACK_PATHS = [
    "/mentions-legales", "/mentions", "/legal", "/legales",
    "/cgv", "/conditions-generales-vente", "/cgu",
    "/a-propos", "/about", "/qui-sommes-nous", "/equipe",
    "/footer", "/",
]


def try_fallback_pages(site_url: str, links: list):
    """Scan mentions légales, CGV, about pages for emails."""
    base = f"{urlparse(site_url).scheme}://{urlparse(site_url).netloc}"
    keywords = ["mention", "legal", "cgv", "cgu", "condition", "propos",
                "about", "qui-somme", "equipe", "team"]
    candidates, seen = [], set()
    for _, href in links:
        h = href.lower()
        if urlparse(href).netloc not in ("", urlparse(base).netloc):
            continue
        if any(kw in h for kw in keywords) and href not in seen:
            seen.add(href)
            candidates.append(href)
    for path in FALLBACK_PATHS:
        url = base.rstrip("/") + path
        if url not in seen:
            seen.add(url)
            candidates.append(url)

    for url in candidates[:6]:
        print(f"     -> Fallback page: {url}")
        html = fetch_rendered_html(url, timeout=15)
        if not html:
            continue
        text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
        emails = extract_emails(html, text)
        if emails:
            return url, emails
    return None, None


def try_google_email_search(name: str, siren: str):
    """Last resort: search Google/Bing for the company's email address."""
    print("     -> Last resort: searching for email online...")
    for q in [f'"{name}" email contact', f'{name} {siren} email']:
        results = _search_with_fallback(q, "email ")
        if not results:
            continue
        all_text = " ".join(f"{r.get('title','')} {r.get('snippet','')}" for r in results)
        emails = _clean_emails(EMAIL_RE.findall(all_text))
        if emails:
            return q, ", ".join(emails)
        for r in results[:3]:
            url = r.get("url")
            if not url:
                continue
            html = fetch_rendered_html(url, timeout=15)
            if not html:
                continue
            text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
            e = extract_emails(html, text)
            if e:
                return url, e
    return None, None


# ── LLM contact link finder ───────────────────────────────────────────────────
def llm_find_contact_link(base_url: str, links: list):
    links_str = "\n".join(f"{text} -> {href}" for text, href in links[:100])
    prompt = (
        f"Here are the links from the homepage of {base_url}:\n{links_str}\n\n"
        "Which link leads to the CONTACT page? "
        "Reply ONLY with the full URL. If not found, reply 'NOT_FOUND'."
    )
    try:
        res = llm(prompt)
        m = re.search(r"https?://[^\s'\"<>]+", res)
        return m.group(0) if m else None
    except Exception as e:
        print(f"  ⚠️  LLM error (contact link): {e}")
        return None


# ── Main pipeline ─────────────────────────────────────────────────────────────
def process_company(name: str, siren: str) -> dict:
    print(f"\n{'='*60}")
    print(f"Processing: {name}  (SIREN: {siren})")

    site_url = find_official_site(name, siren)
    if not site_url:
        print("  ❌ Official site not found.")
        return {"name": name, "site": "NOT_FOUND", "contact": "NOT_FOUND", "emails": "NOT_FOUND"}
    print(f"  ✅ Official site: {site_url}")

    try:
        print("  -> Loading homepage...")
        html = fetch_rendered_html(site_url)
        soup = BeautifulSoup(html, "html.parser")

        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(site_url, a["href"])
            text = a.get_text(strip=True)
            if text and len(text) > 2:
                links.append((text, href))

        print("  -> Looking for contact page...")
        contact_url = llm_find_contact_link(site_url, links) or site_url
        if contact_url != site_url:
            print(f"  ✅ Contact page: {contact_url}")
        else:
            print("  ⚠️  No contact page found, scanning homepage...")

        print("  -> Loading contact page...")
        contact_html = fetch_rendered_html(contact_url)
        contact_text = BeautifulSoup(contact_html, "html.parser").get_text(separator=" ", strip=True)

        print("  -> Extracting emails...")
        emails = extract_emails(contact_html, contact_text)

        if emails:
            print(f"  📧 Emails found: {emails}")
            return {"name": name, "site": site_url, "contact": contact_url, "emails": emails}

        print("  ❌ No email on contact page. Trying fallback pages...")
        fb_url, fb_emails = try_fallback_pages(site_url, links)
        if fb_emails:
            print(f"  📧 Emails found (fallback): {fb_emails}")
            return {"name": name, "site": site_url, "contact": fb_url, "emails": fb_emails}

        g_url, g_emails = try_google_email_search(name, siren)
        if g_emails:
            print(f"  📧 Emails found (search): {g_emails}")
            return {"name": name, "site": site_url, "contact": g_url, "emails": g_emails}

        print("  ❌ No email found after all fallbacks.")
        return {"name": name, "site": site_url, "contact": contact_url, "emails": "NOT_FOUND"}

    except Exception as e:
        print(f"  ❌ Scraping error: {e}")
        return {"name": name, "site": site_url, "contact": "ERROR", "emails": "ERROR"}


# ── Entry point ───────────────────────────────────────────────────────────────

# ── Google Sheets helpers ─────────────────────────────────────────────────────
def _connect_sheet():
    """Authenticate and return the target worksheet."""
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
    sheet_id = os.getenv("SHEET_ID")
    onglet   = os.getenv("SHEET_ONGLET", "BODACC")
    if not sheet_id:
        print("❌ SHEET_ID manquant dans le .env")
        sys.exit(1)
    gc = gspread.service_account(filename=sa_file)
    sh = gc.open_by_key(sheet_id)
    return sh.worksheet(onglet)


def _find_or_create_col(ws, header: str) -> int:
    """Return 1-based column index of *header*, creating it if absent."""
    headers = ws.row_values(1)
    if header in headers:
        return headers.index(header) + 1
    new_col = len(headers) + 1
    ws.update_cell(1, new_col, header)
    return new_col


if __name__ == "__main__":
    ws = _connect_sheet()
    all_rows = ws.get_all_records()   # list of dicts (row 1 = headers)
    total = len(all_rows)
    print(f"📊 {total} lignes chargées depuis Google Sheets.")

    # Locate/create the Email column
    email_col = _find_or_create_col(ws, "Email")
    site_col  = _find_or_create_col(ws, "Site")

    # Start the persistent browser daemon
    DAEMON.start()

    skipped = 0
    try:
        for idx, row in enumerate(all_rows, start=2):   # row 2 = first data row
            name  = str(row.get("Dénomination") or row.get("Denomination") or "").strip()
            siren = str(row.get("Siren") or row.get("SIREN") or "").strip()

            if not name:
                continue

            # Resume: skip if email already filled
            existing_email = str(row.get("Email") or "").strip()
            if existing_email:
                skipped += 1
                continue

            result = process_company(name, siren)

            # Write back to the sheet
            ws.update_cell(idx, email_col, result.get("emails", "NOT_FOUND"))
            ws.update_cell(idx, site_col,  result.get("site",   "NOT_FOUND"))

            print(f"  ✅ Sheet mis à jour (ligne {idx})")

    finally:
        DAEMON.stop()

    print(f"\n✅ Terminé. {total - skipped} entreprises traitées, {skipped} déjà renseignées.")
