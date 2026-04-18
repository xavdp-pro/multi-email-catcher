# multi-email-catcher

Automatically find the **official website** and **contact email** of any French company from its name and SIREN number.

## How it works

```
Input CSV (name + SIREN)
         │
         ▼
┌────────────────────────────────────┐
│        find_official_site()        │
│                                    │
│  S0: French Gov API  (SIREN)       │
│  S1: Google Maps  (Playwright)     │
│  S2: Bing + heuristic  (no LLM)   │
│  S3: Bing/Google + LLM fallback   │
│  S4: Bing/Google + postal address  │
└──────────────┬─────────────────────┘
               │ official URL
               ▼
┌────────────────────────────────────┐
│        Email extraction            │
│                                    │
│  Render page (Playwright Stealth)  │
│  LLM → find contact page link      │
│  mailto + regex extraction         │
│  Fallback: legal/about pages       │
│  Fallback: Bing/Google search      │
└──────────────┬─────────────────────┘
               │
               ▼
        output/results.csv
```

### Strategy details

| Step | Method | LLM used? |
|------|--------|-----------|
| S0 | [recherche-entreprises.api.gouv.fr](https://recherche-entreprises.api.gouv.fr) — free, no key | No |
| S1 | Google Maps Business listing via Playwright Stealth | No |
| S2 | Bing search + name-matching heuristic on first result | No |
| S3 | Bing/Google search + Groq LLM picks the right URL | Yes |
| S4 | Bing/Google search with postal address | Yes (optional) |

**~70% of companies are resolved at S1 (Google Maps) without any LLM call.**

### LLM fallback chain (all free via Groq)

```
llama-3.3-70b-versatile   → 100K tokens/day
         ↓ 429 rate limit
llama-4-scout-17b-16e     → 500K tokens/day
         ↓ 429 rate limit
llama-3.1-8b-instant      → 500K tokens/day
```

---

## Requirements

- Python 3.10+
- Node.js 18+
- A free [Groq API key](https://console.groq.com)

---

## Installation

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/multi-email-catcher.git
cd multi-email-catcher

# 2. Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Node.js dependencies
npm install

# 4. Install Playwright browsers
npx playwright install chromium

# 5. Configure
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

---

## Usage

### Prepare your input file

Edit `input/companies.csv` — a TSV file (tab-separated) with two columns:

```
company_name	siren
SCIERIE BEAL	384527883
MONABEE	788614006
```

### Run

```bash
source venv/bin/activate
python agent.py
```

Results are saved to `output/results.csv`:

```
name,site,contact,emails
SCIERIE BEAL,https://www.scierie-beal.com/,...,contact@scierie-beal.com
MONABEE,https://monabee.fr,...,contact@monabee.fr
```

### Resume

If the script is interrupted, it automatically resumes from where it stopped (the output CSV is flushed after each company).

### Custom paths

```bash
INPUT_CSV=my_companies.csv OUTPUT_CSV=my_results.csv python agent.py
```

---

## Individual scripts

```bash
# Bing search (returns JSON)
NO_PROXY=true node scripts/bing-search.js "SCIERIE BEAL site officiel"

# Google search (returns JSON)
NO_PROXY=true node scripts/google-search.js "SCIERIE BEAL site officiel"

# Google Maps website extractor
node scripts/google-maps-website.js "SCIERIE BEAL DUNIERES 43220"

# Render a page and get HTML
node scripts/get-rendered-html.js "https://www.scierie-beal.com"
```

---

## Results on 33 French companies

| Status | Count |
|--------|-------|
| ✅ Site + email found | 25 |
| ✅ Site found, no email | 3 |
| ❌ NOT_FOUND (no web presence) | 3 |
| ⚠️ Wrong Maps result (ambiguous name) | 2 |

**Total time:** ~45 min (sequential Chromium launches, ~5–7 per company)  
**Cost:** €0 (Groq free tier, Playwright local, Gov API no key)

---

## License

MIT
