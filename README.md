# multi-email-catcher

Automatically find the **official website** and **contact email** of French companies.  
Data is read from a **Google Sheet** and results are written back directly into the sheet.

## How it works

```
Google Sheet (Dénomination + Siren columns)
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
  Google Sheet ← columns "Site" + "Email" filled
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
- A Google Cloud service account JSON file (for Sheets access)

---

## Installation

```bash
# 1. Clone
git clone https://github.com/xavdp-pro/multi-email-catcher.git
cd multi-email-catcher
git checkout gsheets-source

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
# Edit .env (see below)
```

---

## Configuration (.env)

```env
# Groq API key (free at https://console.groq.com)
GROQ_API_KEY=gsk_...

# Google Sheet ID (from the URL: /d/SHEET_ID/edit)
SHEET_ID=1aYG...M5nk

# Tab name in the sheet
SHEET_ONGLET=BODACC

# Path to your Google Cloud service account JSON key
GOOGLE_SERVICE_ACCOUNT_FILE=gbsproject-xxx.json
```

### Google Sheets access

1. Create a service account in [Google Cloud Console](https://console.cloud.google.com)
2. Download the JSON key and place it next to `.env`
3. Share your Google Sheet with the service account email (Editor role)  
   (email found in the JSON under `client_email`)

The sheet must have at minimum these columns: **`Dénomination`** and **`Siren`**.  
The script will auto-create **`Site`** and **`Email`** columns if they don't exist.

---

## Usage

### Run in terminal

```bash
source venv/bin/activate
python agent.py
```

The script automatically **skips rows where Email is already filled** (resume-safe).

### Run via web GUI (recommended)

Launch the web interface — accessible from any browser on the local network:

```bash
python webgui.py
```

Then open: **http://\<server-ip\>:5050**

The GUI shows a **▶ Lancer** button on the left and **real-time logs** on the right.  
Config is read from `.env` — no need to fill anything in the interface.

### Launch GUI on a Linux desktop (if the server has a display)

```bash
DISPLAY=:0 XAUTHORITY=/home/zaza/.Xauthority \
  /path/to/venv/bin/python3 gui.py
```

---

## Individual scripts

```bash
# Bing search (returns JSON)
node scripts/bing-search.js "SCIERIE BEAL site officiel"

# Google search (returns JSON)
node scripts/google-search.js "SCIERIE BEAL site officiel"

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

**Cost:** €0 (Groq free tier, Playwright local, Gov API no key)

---

## License

MIT


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
