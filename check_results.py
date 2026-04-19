import os
import gspread
from dotenv import load_dotenv

load_dotenv('.env')
sa_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
gc = gspread.service_account(filename=sa_file)
ws = gc.open_by_key(os.getenv('SHEET_ID')).worksheet(os.getenv('SHEET_ONGLET', 'BODACC'))
all_rows = ws.get_all_records()

found = []
not_found = []

for idx, r in enumerate(all_rows, start=2):
    name = r.get('Société') or r.get('Societe') or r.get('Dénomination') or r.get('Denomination') or ''
    email = r.get('Email', '')
    site = r.get('Site', '')
    urls_email = r.get('URLs email', '')
    
    if not name:
        continue
        
    if email == 'NOT_FOUND' or (not email and site == 'NOT_FOUND'):
        not_found.append({"name": name, "site": site, "idx": idx})
    elif email and email != 'ERROR':
        found.append({"name": name, "email": email, "urls": urls_email, "site": site, "idx": idx})

print(f"\n--- EMAILS TROUVÉS ({len(found)} échantillons) ---")
for f in found[:10]:
    print(f"[{f['idx']}] {f['name']} -> {f['email']} | Site: {f['site']}")

print(f"\n--- EMAILS NON TROUVÉS ({len(not_found)} échantillons) ---")
for nf in not_found[:10]:
    print(f"[{nf['idx']}] {nf['name']} -> Site: {nf['site']}")

