#!/usr/bin/env python3
"""
Kitsch Sales Dashboard — Auto-Refresh Script
=============================================
Pulls live actuals from NetSuite via Token-Based Auth (TBA), updates the
DATA block in index.html, then deploys to Vercel.

Run manually:
    python scripts/refresh.py

Scheduled (every 2 hours via Cowork):
    Cron: 0 */2 * * *

Requirements:
    pip install requests

Config:
    Copy config.example.json → config/dashboard_config.json
    Fill in your Vercel token and NetSuite TBA credentials.
"""

import json
import re
import os
import sys
import hmac
import hashlib
import base64
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(REPO_ROOT, 'config', 'dashboard_config.json')
HTML_PATH   = os.path.join(REPO_ROOT, 'index.html')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"[ERROR] Config not found at {CONFIG_PATH}\n"
                 f"        Copy config.example.json → config/dashboard_config.json and fill in credentials.")
    with open(CONFIG_PATH) as f:
        return json.load(f)

# ── NetSuite TBA Auth ─────────────────────────────────────────────────────────
def netsuite_tba_header(cfg, method, url):
    """
    Build OAuth 1.0 Authorization header for NetSuite TBA.
    All NetSuite calls via this script are READ-ONLY (GET requests / saved search runs).
    """
    account_id      = cfg['netsuite_account_id']
    consumer_key    = cfg['netsuite_consumer_key']
    consumer_secret = cfg['netsuite_consumer_secret']
    token_id        = cfg['netsuite_token_id']
    token_secret    = cfg['netsuite_token_secret']

    nonce     = uuid.uuid4().hex
    timestamp = str(int(time.time()))

    base_params = {
        'oauth_consumer_key':     consumer_key,
        'oauth_nonce':            nonce,
        'oauth_signature_method': 'HMAC-SHA256',
        'oauth_timestamp':        timestamp,
        'oauth_token':            token_id,
        'oauth_version':          '1.0',
    }

    # Build signature base string
    param_str = '&'.join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(base_params.items())
    )
    base_str = '&'.join([
        method.upper(),
        urllib.parse.quote(url, safe=''),
        urllib.parse.quote(param_str, safe=''),
    ])

    # Sign
    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha256).digest()
    ).decode()

    auth_header = (
        f'OAuth realm="{account_id}",'
        + ','.join(f'{k}="{urllib.parse.quote(v, safe="")}"' for k, v in sorted(base_params.items()))
        + f',oauth_signature="{urllib.parse.quote(sig, safe="")}"'
    )
    return auth_header


def ns_get(cfg, path, params=None):
    """
    READ-ONLY GET request to NetSuite REST API.
    Raises on error.
    """
    account_id = cfg['netsuite_account_id'].replace('_', '-').lower()
    base_url = f"https://{account_id}.suitetalk.api.netsuite.com/services/rest{path}"
    if params:
        base_url += '?' + urllib.parse.urlencode(params)

    auth = netsuite_tba_header(cfg, 'GET', base_url.split('?')[0])
    req  = urllib.request.Request(base_url, headers={
        'Authorization': auth,
        'Content-Type':  'application/json',
        'Accept':        'application/json',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── Pull actuals from NetSuite saved search (customsearch1373) ────────────────
LEVEL5_MAP = {
    # Customer Category → Level 5 channel name used in dashboard
    # Add/adjust as needed to match your NetSuite Customer Masterfile
    'Kitsch DTC':               'Kitsch DTC',
    'Amazon':                   'Amazon',
    'Ulta':                     'Ulta Inc.',
    'Target':                   'Target',
    'Faire':                    'Faire',
    'CVS':                      'CVS Health',
    'Walgreens':                'Walgreens',
    'Walmart':                  'Walmart',
    'Whole Foods':              'Whole Foods/Sprouts',
    'Sprouts':                  'Whole Foods/Sprouts',
    "Kohl's":                   "Kohl's Inc.",
    'Meijer':                   'Meijer',
    'Boots':                    'Boots UK Ltd.',
    'HEB':                      'HEB',
    'Kroger':                   'KROGER',
    'Nordstrom Rack':           'Nordstrom Rack/Hautelook',
    'Hautelook':                'Nordstrom Rack/Hautelook',
    'Scheels':                  'Scheels',
    'Off-Price':                'Off-Price',
    'Business Development':     'Business Development',
    'Grocery':                  'Grocery',
    'Specialty':                'Specialty',
    'International':            'International',
}


def pull_actuals(cfg):
    """
    Run saved search customsearch1373 in 1000-row batches.
    Returns dict keyed by Level 5 channel name → invoiced amount (USD).
    READ-ONLY: only calls ns_get.
    """
    search_id = cfg['netsuite_search_id']  # 'customsearch1373'
    totals = {}
    offset = 0
    limit  = 1000

    print(f"[NetSuite] Pulling saved search {search_id} ...")
    while True:
        data = ns_get(cfg, f'/query/v1/savedquery/{search_id}/run', {
            'limit':  limit,
            'offset': offset,
        })
        rows = data.get('items', [])
        print(f"  Batch offset={offset}: {len(rows)} rows")

        for row in rows:
            cat  = row.get('custcol_customer_category') or row.get('category') or ''
            amt  = float(row.get('amount') or row.get('foreignamount') or 0)
            lvl5 = LEVEL5_MAP.get(cat, cat)
            totals[lvl5] = totals.get(lvl5, 0) + amt

        if not data.get('hasMore', False):
            break
        offset += limit

    return totals


def pull_ooc(cfg):
    """
    Run OOC report (388) to get on-order / committed amounts.
    Returns dict keyed by Level 5 channel → OOC amount.
    READ-ONLY.
    """
    report_id = cfg['netsuite_ooc_report_id']  # '388'
    print(f"[NetSuite] Pulling OOC report {report_id} ...")
    data = ns_get(cfg, f'/record/v1/report/{report_id}', {'subsidiaryId': '1'})

    ooc = {}
    rows = data.get('rows', data.get('items', []))
    for row in rows:
        cat  = row.get('custcol_customer_category') or row.get('category') or ''
        amt  = float(row.get('amount') or 0)
        lvl5 = LEVEL5_MAP.get(cat, cat)
        if lvl5 not in ('Kitsch DTC', 'Amazon'):   # OOC is wholesale only
            ooc[lvl5] = ooc.get(lvl5, 0) + amt

    return ooc


# ── Determine current reporting day (California time) ────────────────────────
def ca_today():
    from datetime import datetime
    import zoneinfo
    return datetime.now(zoneinfo.ZoneInfo('America/Los_Angeles'))


# ── Patch the DATA block in index.html ───────────────────────────────────────
CHANNEL_ORDER = [
    'Ulta Inc.', 'Target', 'Faire', 'CVS Health', 'Walgreens', 'Walmart',
    'Whole Foods/Sprouts', "Kohl's Inc.", 'Meijer', 'Boots UK Ltd.',
    'HEB', 'KROGER', 'Nordstrom Rack/Hautelook', 'Scheels', 'Off-Price',
    'Business Development', 'Grocery', 'Specialty', 'International', 'Other - Misc',
]

def build_data_block(actuals, ooc, forecasts, today, ly):
    month_idx   = today.month - 1   # 0-indexed
    as_of_day   = today.day

    dtc_actual  = int(actuals.get('Kitsch DTC', 0))
    amz_actual  = int(actuals.get('Amazon', 0))
    dtc_ooc     = 0
    amz_ooc     = 0

    ws_lines = []
    for ch in CHANNEL_ORDER:
        a = int(actuals.get(ch, 0))
        o = int(ooc.get(ch, 0))
        f = int(forecasts.get(ch, 0))
        ws_lines.append(
            f"    {{ name: '{ch}', actual: {a:>9}, ooc: {o:>8},  fc: {f:>9}  }},"
        )

    dtc_fc  = int(forecasts.get('Kitsch DTC', 0))
    amz_fc  = int(forecasts.get('Amazon', 0))
    ws_fc   = sum(int(forecasts.get(ch, 0)) for ch in CHANNEL_ORDER)

    dtc_ly = int(ly.get('dtc', 0))
    amz_ly = int(ly.get('amz', 0))
    ws_ly  = int(ly.get('ws', 0))

    days_in_month = (datetime(today.year, today.month % 12 + 1, 1) - __import__('datetime').timedelta(days=1)).day \
                    if today.month < 12 else 31

    lines = [
        'const DATA = {',
        f'  asOfDay:     {as_of_day},',
        f'  dataMonth:   {month_idx},',
        f'  dataYear:    {today.year},',
        '',
        f'  dtcActual:   {dtc_actual},',
        f'  dtcOOC:      {dtc_ooc},',
        f'  amzActual:   {amz_actual},',
        f'  amzOOC:      {amz_ooc},',
        '',
        '  wsChannels: [',
    ] + ws_lines + [
        '  ],',
        '',
        f'  dtcFC:     {dtc_fc},',
        f'  amzFC:     {amz_fc},',
        f'  wsFC:      {ws_fc},',
        '',
        f'  dtcLY:     {dtc_ly},',
        f'  amzLY:     {amz_ly},',
        f'  wsLY:      {ws_ly},',
        '};',
    ]
    return '\n'.join(lines)


def patch_html(html_path, new_data_block):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = r'const DATA = \{.*?\};'
    new_content = re.sub(pattern, new_data_block, content, flags=re.DOTALL)

    if new_content == content:
        print("[WARN] DATA block not replaced — pattern not matched. Check index.html format.")
        return False

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"[OK] index.html DATA block updated.")
    return True


# ── Deploy to Vercel ──────────────────────────────────────────────────────────
def deploy_to_vercel(cfg, html_path):
    token   = cfg['vercel_token']
    project = cfg['vercel_project']

    with open(html_path, 'rb') as f:
        html_bytes = f.read()

    payload = json.dumps({
        "name":    project,
        "files":   [{"file": "index.html", "data": html_bytes.decode('utf-8')}],
        "projectSettings": {"framework": None},
        "target":  "production",
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://api.vercel.com/v13/deployments',
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    url = result.get('url', result.get('alias', ['—'])[0] if result.get('alias') else '—')
    print(f"[Vercel] Deployed → https://{url}")
    return url


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    cfg     = load_config()
    today   = ca_today()

    print(f"[Refresh] {today.strftime('%Y-%m-%d %H:%M %Z')} (California time)")

    # 1. Pull NetSuite actuals (READ-ONLY)
    actuals = pull_actuals(cfg)
    ooc_map = pull_ooc(cfg)

    # 2. Load forecasts from config (these come from the Excel YTD tab)
    #    You can also store them as a separate forecasts.json if you prefer.
    forecasts = cfg.get('forecasts', {})

    # 3. Build LY lookup
    ly = {
        'dtc': cfg.get('ly_june_dtc', 0),
        'amz': cfg.get('ly_june_amz', 0),
        'ws':  cfg.get('ly_june_ws',  0),
    }

    # 4. Patch HTML
    new_block = build_data_block(actuals, ooc_map, forecasts, today, ly)
    if not patch_html(HTML_PATH, new_block):
        sys.exit(1)

    # 5. Deploy
    deploy_to_vercel(cfg, HTML_PATH)

    print("[Done]")


if __name__ == '__main__':
    main()
