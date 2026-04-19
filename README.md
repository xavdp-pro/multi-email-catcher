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
The script will auto-create **`Site`**, **`Email`**, and **`URLs email`** if they don't exist.  
**`URLs email`** est insérée **juste après `Site`** (pour la voir sans défiler). Les en-têtes sont reconnus **sans tenir compte de la casse** (`Email` / `email`).  
Cette colonne contient **l’URL de la page où l’email a été extrait** (une seule URL en principe), ou une courte mention si l’email vient uniquement des extraits SERP sans page dédiée.

Les lignes **déjà avec une valeur dans `Email`** sont ignorées : la colonne `URLs email` n’est alors pas mise à jour pour ces lignes (efface temporairement `Email` si tu veux refaire un passage).

---

## Usage

### Run in terminal

```bash
source venv/bin/activate
python agent.py
```

The script automatically **skips rows where Email is already filled** (resume-safe).

### Run via Qt GUI (local desktop)

```bash
source venv/bin/activate
python gui.py
```

Panneau stats, limite de test, **▶ Lancer** / **■ Arrêter**, logs en direct.  
La config vient du `.env` (même répertoire que le projet).

Sur Linux sans session graphique sur le serveur, lance `gui.py` depuis ta machine avec affichage (ou `DISPLAY=:0` si bureau local sur la même machine) :

```bash
DISPLAY=:0 XAUTHORITY=/home/youruser/.Xauthority \
  ./venv/bin/python gui.py
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
