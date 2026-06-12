# Kitsch Sales Command Center

Interactive sales-vs-forecast dashboard for Kitsch. Shows real-time MTD actuals vs forecast across DTC, Amazon, and Wholesale (Level 5 channels), with YoY comparison.

**Live URL:** Deployed on Vercel — update `config/dashboard_config.json` with your Vercel project URL after first deploy.

---

## Repository Structure

```
kitsch-sales-dashboard/
├── index.html               ← The dashboard (single self-contained file)
├── config.example.json      ← Config template — copy to config/dashboard_config.json
├── scripts/
│   └── refresh.py           ← Auto-refresh: pulls NetSuite → patches HTML → deploys to Vercel
├── .gitignore               ← Excludes config/dashboard_config.json (has credentials)
└── README.md
```

---

## Setup

### 1. Clone & configure

```bash
git clone https://github.com/YOUR_ORG/kitsch-sales-dashboard.git
cd kitsch-sales-dashboard
mkdir config
cp config.example.json config/dashboard_config.json
```

Edit `config/dashboard_config.json` and fill in:
- `vercel_token` — from vercel.com → Settings → Tokens
- `netsuite_account_id` — `4375687`
- NetSuite TBA credentials (see below)

### 2. NetSuite Token-Based Auth (TBA) credentials

These are required for the auto-refresh script to pull data without relying on an expiring OAuth session.

You need **4 values** — a NetSuite admin (Kitsch Accounting Manager role or higher) retrieves them:

| Credential | Where to find it in NetSuite |
|---|---|
| `netsuite_consumer_key` | Setup → Integration → Manage Integrations → click the Claude integration |
| `netsuite_consumer_secret` | Same page (shown only once on creation) |
| `netsuite_token_id` | Setup → Users/Roles → Access Tokens → find the Claude-read-only token |
| `netsuite_token_secret` | Same page (shown only once on creation) |

> **Important:** All NetSuite calls in `refresh.py` are strictly **read-only** GET requests. The script never writes, creates, or modifies any NetSuite record.

### 3. Install dependencies

```bash
pip install requests   # only stdlib used, but requests makes debugging easier
```

### 4. Run manually

```bash
python scripts/refresh.py
```

### 5. Schedule (every 2 hours)

The Cowork scheduled task `kitsch-dashboard-refresh` runs this script automatically every 2 hours (`0 */2 * * *`). No additional setup needed if Cowork is already configured.

---

## Data Sources

| Channel | Source | Updated by |
|---|---|---|
| DTC | Shopify / NetSuite proxy | `refresh.py` via NetSuite saved search |
| Amazon | Amazon Seller Central / NetSuite proxy | `refresh.py` via NetSuite saved search |
| Wholesale (actuals) | NetSuite `customsearch1373` — "Sales Summary by Customer and SKU" | `refresh.py` |
| Wholesale (OOC) | NetSuite Report `388` — "KJ - Sales Actuals vs Forecast OOC" | `refresh.py` |
| Forecasts | YTD tab, Forecast columns (AG–AR) | Manual update in `config/dashboard_config.json` |
| Last Year actuals | NS - 12 Kitsch Per SKU Analysis Report Dec 2025 (Key Customer tab) | Stored in config |

---

## Updating Forecasts

Forecasts don't change often. When they do, update `config/dashboard_config.json` → `"forecasts"` key:

```json
"forecasts": {
  "Kitsch DTC":  14552848,
  "Amazon":      13768064,
  "Ulta Inc.":   3281200,
  "Target":      4521640,
  ...
}
```

---

## Manually Updating the DATA Block

If the auto-refresh isn't running, you can paste data directly into the `const DATA = { ... }` block near the top of `index.html`. The comment block above it explains each field.

---

## Deploying to Vercel

The refresh script deploys automatically. To deploy manually:

```bash
python -c "
import json, urllib.request
cfg = json.load(open('config/dashboard_config.json'))
html = open('index.html', 'rb').read()
payload = json.dumps({'name': cfg['vercel_project'], 'files': [{'file': 'index.html', 'data': html.decode()}], 'target': 'production'}).encode()
req = urllib.request.Request('https://api.vercel.com/v13/deployments', data=payload, headers={'Authorization': f'Bearer {cfg[\"vercel_token\"]}', 'Content-Type': 'application/json'}, method='POST')
print(json.loads(urllib.request.urlopen(req).read()).get('url'))
"
```

---

## California Time

All norms, day counts, and "viewing day" calculations are based on **America/Los_Angeles** time to match NetSuite's reporting timezone. This means a user viewing the dashboard from Manila will see June 8 data when it is still June 8 in California.
