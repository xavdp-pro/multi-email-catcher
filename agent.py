import os
import re
import csv
import sys
import json
import time
import random
import subprocess
import threading
import unicodedata
import requests
import gspread
from gspread.utils import rowcol_to_a1
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
from groq import Groq

from pure_checks import host_matches_any_suffix as _host_matches_any_suffix
from pure_checks import parse_json_object as _parse_json_object
from pure_checks import url_host_matches_suffix_set as _url_host_matches_suffix_set

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
# Extensions souvent captées par erreur dans une « adresse » extraite du HTML.
EMAIL_JUNK_EXTENSIONS = frozenset({".png", ".jpg", ".svg", ".gif", ".css", ".js"})
# Hôtes fictifs / placeholder (tester l’égalité exacte sur l’hôte, pas « in » sur tout l’email).
FAKE_OR_PLACEHOLDER_MAIL_HOSTS = frozenset({
    "example.com", "example.org", "example.net",
    "test.com", "invalid", "localhost",
})
# Adresses complètes souvent laissées dans les modèles (Wix, formulaires).
FAKE_OR_PLACEHOLDER_FULL_EMAILS = frozenset({
    "votreadresse@email.com",
    "your.email@example.com",
    "you@example.com",
    "name@example.com",
    "email@example.com",
})

ANNUAIRE_DOMAINS = {
    "pappers.fr", "societe.com", "infogreffe.fr", "verif.com",
    "manageo.fr", "societe.ninja", "entreprises.lefigaro.fr",
    "annuaire-entreprises.data.gouv.fr", "kompass.com", "corporama.com",
    "datainfogreffe.fr", "bizliste.com", "societeinfo.com", "dirigeant.eu",
    "fr.kompass.com", "europages.fr", "pagesjaunes.fr", "118000.fr",
    "118712.fr", "cylex.fr", "yelp.fr", "juripredis.com", "assoce.fr",
    "bce.fgov.be", "societe-historique.fr",
    "verif-societe.fr", "scorea.fr", "opencorporates.com", "northdata.com",
    "infonet.fr", "firmy.fr", "societe.com.br",
    # Annuaires « fiche entreprise » souvent pris par erreur pour le site officiel
    "infobel.com",
    "dnb.com",
    "allbiz.fr",
    "kompass.fr",
    "entreprises.lagazettefrance.fr",
    "rubypayeur.com",
    "hoodspot.fr",
    "rocketreach.co",
    "tenderinfo.org",
    "travaux-rge.com",
    "chauffage-et-clim.net",
    "procedurecollective.fr",
    "journal-economique.fr",
    "telephone.city",
    "prosmaison.fr",
    "usinenouvelle.com",
    "net1901.org",
    "sudouest.fr",
}

_SOCIAL_DOMAINS = {
    "facebook.com", "linkedin.com", "twitter.com", "youtube.com",
    "wikipedia.org", "ameli.fr", "wixsite.com", "assoce.fr",
    "instagram.com", "tiktok.com",
}

# Éditeurs / agrégateurs juridiques : emails de contact plateforme, pas de l’entreprise cible.
_LEGAL_PUBLISHER_EMAIL_SUFFIXES = frozenset({
    "lextenso.fr",
    "actu-juridique.fr",
    "infopro-digital.com",
})

# Hôte de l’email : si le domaine (ou un parent) est un annuaire / plateforme, on rejette
# même quand le sous-domaine contient le nom de l’entreprise (ex. dupont.pappers.fr).
_EMAIL_HOST_SUFFIX_BLOCK = frozenset(
    ANNUAIRE_DOMAINS
    | _SOCIAL_DOMAINS
    | _LEGAL_PUBLISHER_EMAIL_SUFFIXES
    | {
        "wix.com",
        "wixpress.com",
        "wixsite.com",
        "google.com",
        "gstatic.com",
        "googleapis.com",
        "youtube.com",
        "sentry.io",
        "sentry-next.wixpress.com",
        "doubleclick.net",
        "typeform.com",
        "hubspot.com",
        "mailchimp.com",
        "sendinblue.com",
        "brevo.com",
    }
)

# Pour tests « annuaire dans l’URL » : comparer le **netloc** par suffixe (évite `misociete.com` ⊃ `societe.com`).
_ANNUAIRE_HOST_SUFFIXES = frozenset(ANNUAIRE_DOMAINS)
_ANNUAIRE_OR_SOCIAL_SUFFIXES = frozenset(ANNUAIRE_DOMAINS | _SOCIAL_DOMAINS)

# ── Name normalisation ─────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _deobfuscate_email_markers(text: str) -> str:
    """
    Mentions légales / pages contact : « contact[at]domaine.com », « x [at] y [dot] fr », etc.
    """
    if not text:
        return text
    t = text
    for pat in (
        r"\[\s*at\s*\]",
        r"\(\s*at\s*\)",
        r"\{\s*at\s*\}",
        r"\[\s*@\s*\]",
        r"\(\s*@\s*\)",
    ):
        t = re.sub(pat, "@", t, flags=re.IGNORECASE)
    for pat in (r"\[\s*dot\s*\]", r"\(\s*dot\s*\)", r"\{\s*dot\s*\}"):
        t = re.sub(pat, ".", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=[\w.%+\-])\s+AT\s+(?=[\w.\-])", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=[\w.%+\-])\s+DOT\s+(?=[\w.\-])", ".", t, flags=re.IGNORECASE)
    return t

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


def _email_address_host(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].lower().strip().rstrip(".")


def _is_blocked_email_host(host: str) -> bool:
    """True si l’hôte est (ou est sous) un annuaire, réseau social ou plateforme connue."""
    return _host_matches_any_suffix(host, _EMAIL_HOST_SUFFIX_BLOCK)


def _official_site_email_baseline(site_url: str | None) -> str:
    if not site_url:
        return ""
    net = urlparse(site_url).netloc.lower().strip()
    return net.removeprefix("www.").strip().rstrip(".")


def _email_host_matches_site(email: str, site_url: str | None) -> bool:
    """contact@dupont.fr ou @sous-domaine.dupont.fr quand le site est https://www.dupont.fr/…"""
    base = _official_site_email_baseline(site_url)
    if not base:
        return False
    eh = _email_address_host(email)
    return eh == base or eh.endswith("." + base)


def _email_host_matches_brand_tokens(email: str, company_name: str | None) -> bool:
    """
    Indice secondaire : une partie du nom (≥4 caractères) apparaît dans l’hôte.
    Ne suffit pas à valider une adresse (un annuaire peut aussi contenir le nom en sous-domaine,
    mais ces hôtes sont déjà exclus par _is_blocked_email_host).
    """
    if not company_name:
        return False
    host = _normalize_for_match(_email_address_host(email))
    if not host:
        return False
    for w in _normalize_for_match(normalize_name(company_name)).split():
        if len(w) >= 4 and w in host:
            return True
    return False


def _email_site_alignment_tier(email: str, site_url: str | None, company_name: str | None) -> int:
    """0 = domaine du site ; 1 = marque probable dans l’hôte ; 2 = sans lien clair (ex. Gmail, agence)."""
    if _email_host_matches_site(email, site_url):
        return 0
    if company_name and _email_host_matches_brand_tokens(email, company_name):
        return 1
    return 2


def _rank_emails_for_output(emails: list[str], site_url: str | None, company_name: str | None) -> list[str]:
    unique = list(dict.fromkeys(emails))
    if not unique:
        return []
    unique.sort(key=lambda e: (_email_site_alignment_tier(e, site_url, company_name), e))
    return unique


def _primary_domain_label(netloc: str) -> str:
    h = netloc.lower().removeprefix("www.").split(":")[0].rstrip(".")
    return h.split(".")[0] if h else ""


def _tier1_email_plausible_for_site(email: str, site_url: str) -> bool:
    """
    Si le mail semble lié au nom (tier 1) mais pas au domaine du site (tier 0),
    exiger quand même un lien entre les deux domaines (évite homonymes type BRUNIER / Honeywell).
    """
    base = _official_site_email_baseline(site_url)
    eh = _email_address_host(email)
    if not base or not eh:
        return False
    bl = _primary_domain_label(base)
    el = _primary_domain_label(eh)
    if len(bl) < 4 or len(el) < 4:
        return True
    return bl in eh or el in base


def _filter_emails_for_serp_fallback(
    emails: list[str],
    site_url: str,
    company_name: str | None,
) -> list[str]:
    """Emails SERP utilisables après échec crawl : @domaine du site, ou marque + cohérence inter-domaines."""
    out: list[str] = []
    for e in emails:
        t = _email_site_alignment_tier(e, site_url, company_name)
        if t == 0:
            out.append(e)
        elif t == 1 and _tier1_email_plausible_for_site(e, site_url):
            out.append(e)
    return out


# ── LLM ───────────────────────────────────────────────────────────────────────
def llm(prompt: str) -> str:
    for model in [MODEL_PRIMARY, MODEL_FALLBACK, MODEL_FALLBACK2]:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            content = r.choices[0].message.content
            if content is None:
                return ""
            return content.strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                print(f"  ⚠️  Rate limit {model}, trying next model...")
                continue
            raise
    raise RuntimeError("All Groq models are rate-limited. Try again later.")


def _registrable_host(netloc: str) -> str:
    return netloc.lower().removeprefix("www.")


def _same_registrable_domain(home_url: str, candidate_url: str) -> bool:
    h = _registrable_host(urlparse(home_url).netloc)
    u = _registrable_host(urlparse(candidate_url).netloc)
    return bool(h) and h == u


def _is_disallowed_official_site_url(url: str | None) -> bool:
    """
    URLs qui ressemblent à un « site web » dans la SERP mais ne sont pas le site de l’entreprise
    (annonces légales agrégées, etc.).
    """
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not u.lower().startswith("http"):
        return False
    try:
        p = urlparse(u)
    except Exception:
        return False
    host = _registrable_host(p.netloc)
    path_l = (p.path or "").lower()
    if host == "annonces-legales.lefigaro.fr" or host.endswith(".annonces-legales.lefigaro.fr"):
        return True
    if "/annonces-legales/" in path_l:
        return True
    return False


def _search_both_engines(query: str) -> list:
    """Runs Bing and Google for the same query and merges unique results (order: Bing, then Google)."""
    out, seen = [], set()
    pause = random.uniform(1.5, 3.5)
    print(f"  -> Bing+Google: {query}  (pause {pause:.1f}s)")
    time.sleep(pause)
    for engine in ("bing", "google"):
        try:
            chunk = _run_search_engine(engine, query)
        except Exception as e:
            print(f"  ⚠️  {engine} error: {e}")
            chunk = []
        for r in chunk or []:
            u = r.get("url") or ""
            if u.startswith("http") and u not in seen:
                seen.add(u)
                out.append(r)
    print(f"     → {len(out)} merged SERP rows")
    return out


def _emails_from_serp_snippets(
    results: list,
    *,
    site_url: str | None = None,
    company_name: str | None = None,
) -> list[str]:
    blob = " ".join(
        f"{r.get('title', '')} {r.get('snippet', '')}" for r in (results or [])
    )
    blob_dof = _deobfuscate_email_markers(blob)
    found = EMAIL_RE.findall(blob) + EMAIL_RE.findall(blob_dof)
    return _clean_emails(found, site_url=site_url, company_name=company_name)


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
    generic = {
        "sud", "nord", "ouest", "est",
        "france", "francais", "francaise",
        "groupe", "services", "service", "solutions",
        "concept", "international", "global",
    }
    distinctive = [w for w in words if len(w) >= 4 and w not in generic]
    if not words or (len(words) == 1 and len(words[0]) <= 5):
        return None

    for r in results:
        url   = r.get("url", "")
        title = _normalize_for_match(r.get("title", ""))
        domain = _normalize_for_match(urlparse(url).netloc)
        if not url.startswith("http"):
            continue
        if _is_disallowed_official_site_url(url):
            continue
        if _url_host_matches_suffix_set(url, _ANNUAIRE_OR_SOCIAL_SUFFIXES):
            continue
        matched = sum(1 for w in words if w in title or w in domain)
        if matched < max(1, len(words) // 2):
            continue
        if len(words) >= 3 and distinctive:
            # Pour les noms composites, éviter qu’un média/portail gagne juste sur des mots génériques.
            if not any(w in title or w in domain for w in distinctive):
                continue
        return url
    return None


# ── LLM SERP analysis (Groq) ──────────────────────────────────────────────────
def llm_analyze_serp_results(name: str, siren: str, search_results: list) -> tuple[str | None, list[str]]:
    """
    Parse Bing/Google SERP rows (title, snippet, URL) with the LLM:
    pick the official site when possible, and surface emails visible in snippets.
    """
    if not search_results:
        return None, []
    filtered = [
        r for r in search_results
        if not _url_host_matches_suffix_set(r.get("url", ""), _ANNUAIRE_HOST_SUFFIXES)
        and not _is_disallowed_official_site_url(r.get("url", ""))
    ]
    if not filtered:
        return None, []
    rows = "\n".join(
        f"- URL: {r.get('url', '')}\n  TITLE: {r.get('title', '')}\n  SNIPPET: {r.get('snippet', '')}"
        for r in filtered[:12]
    )
    prompt = (
        f"Company: {name} (SIREN: {siren}).\n"
        f"Below are organic search result lines (each may contain title, snippet, target URL).\n\n{rows}\n\n"
        "Task:\n"
        "1) If one URL is clearly this company's OFFICIAL public website (not a directory, social network, "
        "or data broker), return it as official_website. Otherwise null.\n"
        "2) List every plausible company contact email that appears in the SNIPPET or TITLE text "
        "(not guessed). Omit addresses @ domains of directories (Pappers, Societe.com, Kompass, PagesJaunes, etc.). "
        "Use [].\n"
        'Reply with ONLY valid JSON: {"official_website": string or null, "emails_found": string[]}'
    )
    emails_out: list[str] = []
    official: str | None = None
    try:
        raw = llm(prompt)
        data = _parse_json_object(raw) or {}
        ow = data.get("official_website") or data.get("official_url")
        if isinstance(ow, str) and ow.startswith("http"):
            official = ow.strip().rstrip(".,;")
            if _is_disallowed_official_site_url(official):
                official = None
        for e in data.get("emails_found") or data.get("emails") or []:
            if isinstance(e, str):
                m = EMAIL_RE.search(e)
                if m:
                    emails_out.append(m.group(0))
        if not official:
            m = re.search(r"https?://[^\s'\"<>]+", raw)
            if m and not _url_host_matches_suffix_set(m.group(0), _ANNUAIRE_HOST_SUFFIXES):
                cand = m.group(0).rstrip(".,;")
                if not _is_disallowed_official_site_url(cand):
                    official = cand
        emails_out = _clean_emails(emails_out, site_url=official, company_name=name)
        return official, emails_out
    except Exception as e:
        print(f"  ⚠️  LLM error (SERP analyze): {e}")
        return None, []


# ── Google Maps ───────────────────────────────────────────────────────────────
def lookup_google_maps(query: str):
    url = DAEMON.maps(query)
    if url and url.startswith("http"):
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/") or url
    return None


def _merge_serp_emails_csv(
    emails: list[str],
    *,
    site_url: str | None = None,
    company_name: str | None = None,
) -> str | None:
    cleaned = _clean_emails(emails, site_url=site_url, company_name=company_name)
    return ", ".join(cleaned) if cleaned else None


# ── Find official site ────────────────────────────────────────────────────────
def find_official_site(name: str, siren: str) -> tuple[str | None, str | None]:
    """
    Strategy cascade:
      S0 → French government API (SIREN)
      S1 → Google Maps (most reliable, no LLM)
      S2 → Bing/Google + heuristic (URL) + Groq SERP parse (URL + emails in lines)
      S3 → idem
      S4 → Bing/Google + postal address

    Returns (site_url_or_None, emails_seen_in_SERP_or_None).
    """
    clean = normalize_name(name)
    serp_emails: list[str] = []

    def absorb_emails(em: list[str]):
        serp_emails.extend(e for e in em if e)

    # S-1: explicit « mail » queries on Bing AND Google, then Groq on merged SERP
    print("  -> Requêtes mail (Bing + Google) + analyse Groq des SERP…")
    for mq in (f'"{clean}" mail', f'"{name}" mail'):
        mail_res = _search_both_engines(mq)
        absorb_emails(_emails_from_serp_snippets(mail_res, company_name=name))
        if mail_res:
            _, em_llm = llm_analyze_serp_results(name, siren, mail_res)
            absorb_emails(em_llm)

    # S0: Government API
    print("  -> French government API (SIREN)...")
    api_site, adresse = lookup_siren_api(siren)
    if (
        api_site
        and not _url_host_matches_suffix_set(api_site, _ANNUAIRE_HOST_SUFFIXES)
        and not _is_disallowed_official_site_url(api_site)
    ):
        print(f"  ✅ Site from government API: {api_site}")
        return api_site, _merge_serp_emails_csv(serp_emails, site_url=api_site, company_name=name)

    # S1: Google Maps
    maps_query = f"{clean} {adresse}" if adresse else clean
    print(f"  -> Google Maps: {maps_query}")
    maps_site = lookup_google_maps(maps_query)
    if maps_site:
        if _is_disallowed_official_site_url(maps_site):
            print("  ⚠️  Google Maps: URL ignorée (annonces légales / page non entreprise).")
        else:
            print(f"  ✅ Site from Google Maps: {maps_site}")
            return maps_site, _merge_serp_emails_csv(serp_emails, site_url=maps_site, company_name=name)

    # S2 + S3: Bing/Google search (+ Groq parse on each SERP)
    queries = [
        f"{clean} site officiel",
        f'"{clean}" {siren}',
    ]
    for i, q in enumerate(queries, 1):
        results = _search_with_fallback(q, f"#{i} ")
        if not results:
            continue
        absorb_emails(_emails_from_serp_snippets(results, company_name=name))
        print(f"     -> Groq analyse la SERP ({len(results)} lignes)…")
        site_llm, em_llm = llm_analyze_serp_results(name, siren, results)
        absorb_emails(em_llm)
        site = _pick_first_result_heuristic(name, results)
        site_ok = site if site and not _is_disallowed_official_site_url(site) else None
        llm_ok = site_llm if site_llm and not _is_disallowed_official_site_url(site_llm) else None
        chosen = site_ok or llm_ok
        if chosen:
            if site_ok:
                print(f"     ✅ URL (heuristique): {site_ok}")
            else:
                print(f"     ✅ URL (Groq / SERP): {llm_ok}")
            return chosen, _merge_serp_emails_csv(serp_emails, site_url=chosen, company_name=name)

    # S4: Bing/Google + postal address
    if adresse:
        print(f"  -> Search by postal address: {adresse}")
        results = _search_with_fallback(f'{clean} "{adresse}" site', "addr ")
        if results:
            absorb_emails(_emails_from_serp_snippets(results, company_name=name))
            print(f"     -> Groq analyse la SERP (adresse)…")
            site_llm, em_llm = llm_analyze_serp_results(name, siren, results)
            absorb_emails(em_llm)
            site = _pick_first_result_heuristic(name, results)
            site_ok = site if site and not _is_disallowed_official_site_url(site) else None
            llm_ok = site_llm if site_llm and not _is_disallowed_official_site_url(site_llm) else None
            chosen = site_ok or llm_ok
            if chosen:
                if site_ok:
                    print(f"     ✅ URL (heuristique): {site_ok}")
                else:
                    print(f"     ✅ URL (Groq / SERP): {llm_ok}")
                return chosen, _merge_serp_emails_csv(serp_emails, site_url=chosen, company_name=name)

    return None, _merge_serp_emails_csv(serp_emails, company_name=name)


# ── HTML / email helpers ──────────────────────────────────────────────────────
def fetch_rendered_html(url: str, timeout: int = 25) -> str:
    return DAEMON.html(url, timeout=timeout)


def _clean_emails(
    found: list,
    *,
    site_url: str | None = None,
    company_name: str | None = None,
) -> list:
    out, seen = [], set()
    for raw in found:
        e = raw.strip().strip(".").strip(",").lower()
        if not e or "@" not in e or e in seen:
            continue
        if e in FAKE_OR_PLACEHOLDER_FULL_EMAILS:
            continue
        if any(ext in e for ext in EMAIL_JUNK_EXTENSIONS):
            continue
        host = _email_address_host(e)
        if not host or host in FAKE_OR_PLACEHOLDER_MAIL_HOSTS:
            continue
        if _is_blocked_email_host(host):
            continue
        seen.add(e)
        out.append(e)
    return _rank_emails_for_output(out, site_url, company_name)


def extract_emails(
    html: str,
    page_text: str,
    *,
    site_url: str | None = None,
    company_name: str | None = None,
) -> str | None:
    """Extract emails via mailto tags, HTML regex, and text regex — no LLM."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for tag in soup.find_all("a", href=True):
        if tag["href"].lower().startswith("mailto:"):
            found.append(tag["href"][7:].split("?")[0])
    html_dof = _deobfuscate_email_markers(html)
    text_dof = _deobfuscate_email_markers(page_text)
    for blob in (html, page_text, html_dof, text_dof):
        found.extend(EMAIL_RE.findall(blob))
    cleaned = _clean_emails(found, site_url=site_url, company_name=company_name)
    return ", ".join(cleaned) if cleaned else None


def collect_homepage_links(site_url: str, soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Collects internal links; keeps short anchors when the URL hints at contact / legal / team pages."""
    hints = (
        "contact", "nous-contacter", "contactez", "about", "mention", "legal", "legale",
        "equipe", "team", "recrut", "cgu", "cgv", "impressum", "devis", "presse",
        "qui-sommes", "write", "a-propos",
    )
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        raw = a.get("href", "").strip()
        if not raw or raw.lower().startswith(("javascript:", "#")):
            continue
        href = urljoin(site_url, raw)
        if not href.startswith("http"):
            continue
        if not _same_registrable_domain(site_url, href):
            continue
        if href in seen:
            continue
        text = (a.get_text("", strip=True) or "").strip() or "(sans titre)"
        hlow = href.lower()
        if len(text) >= 3 and text != "(sans titre)":
            seen.add(href)
            out.append((text, href))
        elif any(k in hlow for k in hints):
            seen.add(href)
            out.append((text, href))
    return out[:120]


FALLBACK_PATHS = [
    "/mentions-legales", "/mentions", "/legal", "/legales",
    "/cgv", "/conditions-generales-vente", "/cgu",
    "/a-propos", "/about", "/qui-sommes-nous", "/equipe",
    "/footer", "/",
]


def try_fallback_pages(
    site_url: str,
    links: list,
    company_name: str | None = None,
):
    """Scan mentions légales, CGV, about pages for emails."""
    base = f"{urlparse(site_url).scheme}://{urlparse(site_url).netloc}"
    keywords = ["mention", "legal", "cgv", "cgu", "condition", "propos",
                "about", "qui-somme", "equipe", "team"]
    candidates, seen = [], set()
    for _, href in links:
        h = href.lower()
        if not _same_registrable_domain(site_url, href):
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
        emails = extract_emails(html, text, site_url=site_url, company_name=company_name)
        if emails:
            parts = [x.strip() for x in emails.split(",") if x.strip()]
            tiers = [_email_site_alignment_tier(e, site_url, company_name) for e in parts]
            if 0 in tiers:
                return url, emails
            accepted = _filter_emails_for_serp_fallback(parts, site_url, company_name)
            if accepted:
                return url, ", ".join(_rank_emails_for_output(accepted, site_url, company_name))
    return None, None


def _iter_serp_urls_skip_directories(results: list, *, max_pages: int = 8):
    """Parcourt les résultats SERP et ne renvoie que des URLs à crawler (hors annuaires / sociaux)."""
    seen: set[str] = set()
    yielded = 0
    for r in results or []:
        if yielded >= max_pages:
            break
        url = (r.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        if _is_disallowed_official_site_url(url):
            continue
        if _url_host_matches_suffix_set(url, _ANNUAIRE_OR_SOCIAL_SUFFIXES):
            continue
        if url in seen:
            continue
        seen.add(url)
        yielded += 1
        yield url


def try_google_email_search(
    name: str,
    siren: str,
    official_site_url: str | None = None,
):
    """Last resort: Bing + Google for mail-oriented queries, regex + Groq on SERP lines."""
    print("     -> Dernier recours: Bing+Google (mail) + Groq sur les SERP…")
    clean = normalize_name(name)
    for q in (
        f'"{name}" email contact',
        f'"{clean}" mail',
        f"{name} {siren} email",
        f"{clean} {siren} mail",
    ):
        results = _search_both_engines(q)
        if not results:
            continue
        quick = _emails_from_serp_snippets(
            results, site_url=official_site_url, company_name=name,
        )
        if quick:
            if official_site_url:
                quick = _filter_emails_for_serp_fallback(quick, official_site_url, name)
            if quick:
                return q, ", ".join(quick)
        _, em_llm = llm_analyze_serp_results(name, siren, results)
        if em_llm:
            cleaned = _clean_emails(em_llm, site_url=official_site_url, company_name=name)
            if official_site_url:
                cleaned = _filter_emails_for_serp_fallback(cleaned, official_site_url, name)
            if cleaned:
                return q, ", ".join(cleaned)
        for url in _iter_serp_urls_skip_directories(results, max_pages=8):
            html = fetch_rendered_html(url, timeout=15)
            if not html:
                continue
            text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
            site_for = official_site_url or url
            e = extract_emails(
                html, text,
                site_url=site_for,
                company_name=name,
            )
            if e:
                parts = [x.strip() for x in e.split(",") if x.strip()]
                tiers = [_email_site_alignment_tier(x, site_for, name) for x in parts]
                if 0 in tiers:
                    return url, e
                accepted = _filter_emails_for_serp_fallback(parts, site_for, name)
                if accepted:
                    return url, ", ".join(_rank_emails_for_output(accepted, site_for, name))
    return None, None


def llm_list_email_candidate_urls(site_url: str, company_name: str, links: list[tuple[str, str]]) -> list[str]:
    """
    Groq reads the homepage link list and returns several on-site URLs likely to contain an email
    (contact, legal notice, team, etc.).
    """
    if not links:
        return []
    lines = "\n".join(f"{text[:90]} -> {href}" for text, href in links[:100])
    prompt = (
        f"Company: {company_name}. Official homepage: {site_url}\n\n"
        f"Navigation links (anchor -> URL):\n{lines}\n\n"
        "Pick 1 to 6 page URLs on THE SAME WEBSITE ONLY (same registrable domain as the homepage) "
        "where a professional contact or legal email is most likely to appear. "
        "Examples: contact, nous-contacter, contact-us, mentions légales, legal, équipe, recruitment, presse, CGV.\n"
        'Reply ONLY with JSON: {"urls": ["https://..."]} from most to least likely. Use [] if unsure.'
    )
    try:
        raw = llm(prompt)
        data = _parse_json_object(raw) or {}
        urls = data.get("urls") or data.get("pages") or []
        good: list[str] = []
        for u in urls:
            if not isinstance(u, str) or not u.startswith("http"):
                continue
            if not _same_registrable_domain(site_url, u):
                continue
            if _url_host_matches_suffix_set(u, _ANNUAIRE_OR_SOCIAL_SUFFIXES):
                continue
            good.append(u.rstrip("/ "))
        seen: set[str] = set()
        uniq: list[str] = []
        for u in good:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq[:6]
    except Exception as e:
        print(f"  ⚠️  LLM error (candidate URLs): {e}")
        return []


# ── Main pipeline ─────────────────────────────────────────────────────────────
def process_company(name: str, siren: str) -> dict:
    print(f"\n{'='*60}")
    print(f"Processing: {name}  (SIREN: {siren})")

    site_url, serp_email_csv = find_official_site(name, siren)
    if not site_url:
        if serp_email_csv:
            print("  ✅ Email trouvé dans les SERP (site officiel introuvable).")
            return {
                "name": name,
                "site": "NOT_FOUND",
                "contact": "SERP",
                "emails": serp_email_csv,
                "urls_email": "(SERP — extraits Bing/Google ; aucune page « site »)",
            }
        print("  ❌ Official site not found.")
        return {
            "name": name,
            "site": "NOT_FOUND",
            "contact": "NOT_FOUND",
            "emails": "NOT_FOUND",
            "urls_email": "",
        }
    print(f"  ✅ Official site: {site_url}")

    try:
        print("  -> Loading homepage...")
        html = fetch_rendered_html(site_url)
        soup = BeautifulSoup(html, "html.parser")

        links = collect_homepage_links(site_url, soup)

        print("  -> Groq liste les pages du site à visiter (contact, légal, …)…")
        extra_pages = llm_list_email_candidate_urls(site_url, name, links)
        to_visit: list[str] = []
        seen_u: set[str] = set()
        for u in [site_url] + extra_pages:
            if u and u not in seen_u:
                seen_u.add(u)
                to_visit.append(u)
        to_visit = to_visit[:6]

        for idx, page_url in enumerate(to_visit):
            print(f"  -> Page {idx + 1}/{len(to_visit)}: {page_url}")
            phtml = fetch_rendered_html(page_url)
            if not phtml:
                continue
            ptext = BeautifulSoup(phtml, "html.parser").get_text(separator=" ", strip=True)
            emails = extract_emails(phtml, ptext, site_url=site_url, company_name=name)
            if emails:
                parts = [x.strip() for x in emails.split(",") if x.strip()]
                tiers = [_email_site_alignment_tier(e, site_url, name) for e in parts]
                if 0 in tiers:
                    out_emails = emails
                else:
                    accepted = _filter_emails_for_serp_fallback(parts, site_url, name)
                    if not accepted:
                        continue
                    out_emails = ", ".join(_rank_emails_for_output(accepted, site_url, name))
                print(f"  📧 Emails trouvés: {out_emails}")
                return {
                    "name": name,
                    "site": site_url,
                    "contact": page_url,
                    "emails": out_emails,
                    "urls_email": page_url,
                }

        print("  ❌ Pas d'email sur les pages candidates. Fallbacks…")
        fb_url, fb_emails = try_fallback_pages(site_url, links, company_name=name)
        if fb_emails:
            print(f"  📧 Emails found (fallback): {fb_emails}")
            return {
                "name": name,
                "site": site_url,
                "contact": fb_url,
                "emails": fb_emails,
                "urls_email": fb_url or "",
            }

        if serp_email_csv:
            serp_parts = [x.strip() for x in serp_email_csv.split(",") if x.strip()]
            serp_aligned = _filter_emails_for_serp_fallback(serp_parts, site_url, name)
            if serp_aligned:
                serp_out = ", ".join(serp_aligned)
                print(f"  📧 Emails (SERP, alignés avec le site): {serp_out}")
                return {
                    "name": name,
                    "site": site_url,
                    "contact": "SERP",
                    "emails": serp_out,
                    "urls_email": "(SERP — extraits lors de la recherche du site ; pas d’URL de page unique)",
                }
            print("  ⚠️  SERP: emails trouvés mais aucun domaine cohérent avec le site — ignorés.")

        g_url, g_emails = try_google_email_search(name, siren, official_site_url=site_url)
        if g_emails:
            print(f"  📧 Emails found (search): {g_emails}")
            gu = (g_url or "").strip()
            src = gu if gu.lower().startswith("http") else f"(SERP — extraits) {gu}"
            return {
                "name": name,
                "site": site_url,
                "contact": g_url or "SEARCH",
                "emails": g_emails,
                "urls_email": src,
            }

        print("  ❌ No email found after all fallbacks.")
        last_contact = to_visit[0] if to_visit else site_url
        return {
            "name": name,
            "site": site_url,
            "contact": last_contact,
            "emails": "NOT_FOUND",
            "urls_email": "",
        }

    except Exception as e:
        print(f"  ❌ Scraping error: {e}")
        return {
            "name": name,
            "site": site_url,
            "contact": "ERROR",
            "emails": "ERROR",
            "urls_email": "",
        }


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
    """Return 1-based column index of *header*, creating it if absent.

    Comparaison d’en-tête **insensible à la casse** (ex. « email » = « Email »).
    The sheet grid is automatically widened when a new column is appended,
    otherwise gspread raises `APIError: Range ... exceeds grid limits`.
    """
    headers = ws.row_values(1)
    h_low = header.strip().lower()
    for i, h in enumerate(headers):
        if str(h).strip().lower() == h_low:
            return i + 1
    new_col = len(headers) + 1
    if new_col > ws.col_count:
        ws.add_cols(new_col - ws.col_count)
    ws.update_cell(1, new_col, header)
    return new_col


def _insert_blank_column_after_site(ws, site_col_1based: int) -> int:
    """Insère une colonne vide juste après la colonne Site (1-based). Retourne l’index 1-based de la nouvelle colonne."""
    start_0 = site_col_1based  # 0-based : colonne suivant immédiatement Site
    body = {
        "requests": [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": start_0,
                        "endIndex": start_0 + 1,
                    },
                    "inheritFromBefore": True,
                }
            }
        ]
    }
    ws.spreadsheet.batch_update(body)
    return site_col_1based + 1


def _ensure_urls_email_column(ws) -> int:
    """
    Garantit la colonne « URLs email » : si absente, l’insère **juste après « Site »**
    pour qu’elle soit visible sans défiler jusqu’en fin de grille.
    """
    headers = ws.row_values(1)
    lows = [str(h).strip().lower() for h in headers]
    key = "urls email"
    if key in lows:
        c = lows.index(key) + 1
        print(f"  📋 Colonne « URLs email » : {rowcol_to_a1(1, c)} (déjà présente)")
        return c
    if "site" in lows:
        site_c = lows.index("site") + 1
        new_c = _insert_blank_column_after_site(ws, site_c)
        ws.update_cell(1, new_c, "URLs email")
        print(
            f"  📋 Colonne « URLs email » créée après « Site » : {rowcol_to_a1(1, new_c)} "
            f"(URL où l’email a été trouvé, à chaque ligne traitée)"
        )
        return new_c
    c = _find_or_create_col(ws, "URLs email")
    print(
        f"  📋 Colonne « URLs email » : {rowcol_to_a1(1, c)} "
        f"(pas de colonne « Site » en ligne 1 — ajoute « Site » pour placer « URLs email » à côté)"
    )
    return c


if __name__ == "__main__":
    if not (os.getenv("GROQ_API_KEY") or "").strip():
        print("❌ GROQ_API_KEY manquant ou vide dans .env")
        sys.exit(1)

    ws = _connect_sheet()

    # Colonnes d’abord (insertion « URLs email » peut décaler les index → recalcul ensuite)
    email_col = _find_or_create_col(ws, "Email")
    site_col = _find_or_create_col(ws, "Site")
    urls_email_col = _ensure_urls_email_column(ws)
    email_col = _find_or_create_col(ws, "Email")
    site_col = _find_or_create_col(ws, "Site")

    all_rows = ws.get_all_records()  # list of dicts (row 1 = headers)
    total = len(all_rows)
    print(f"📊 {total} lignes chargées depuis Google Sheets.")

    # Start the persistent browser daemon
    DAEMON.start()

    try:
        max_companies = int(os.getenv("MAX_COMPANIES", "0") or 0)
    except ValueError:
        max_companies = 0
    if max_companies > 0:
        print(f"🔒 Limite : {max_companies} entreprise(s) à traiter maximum.")

    skipped = 0
    processed = 0
    try:
        for idx, row in enumerate(all_rows, start=2):   # row 2 = first data row
            name  = str(
                row.get("Société")
                or row.get("Societe")
                or row.get("Dénomination")
                or row.get("Denomination")
                or ""
            ).strip()
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
            ws.update_cell(idx, site_col, result.get("site", "NOT_FOUND"))
            ucell = result.get("urls_email") or ""
            ws.update_cell(idx, urls_email_col, ucell)

            processed += 1
            uref = rowcol_to_a1(idx, urls_email_col)
            if ucell:
                print(
                    f"  ✅ Sheet ligne {idx} — {uref} « URLs email » "
                    f"({ucell.count(chr(10)) + 1} ligne(s) dans la cellule)"
                )
            print(f"  ✅ Sheet mis à jour (ligne {idx})  [{processed}/{max_companies or '∞'}]")

            if max_companies and processed >= max_companies:
                print(f"\n🔒 Limite atteinte ({max_companies}). Arrêt.")
                break

    finally:
        DAEMON.stop()

    print(f"\n✅ Terminé. {processed} entreprises traitées, {skipped} déjà renseignées.")
