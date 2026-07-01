import json, glob, os, openpyxl

TOOL_DIR   = r'C:\Users\Glenn\.claude\projects\C--Users-Glenn-OneDrive-Desktop-kitsch-sales-dashboard\8edd3cc0-fc54-46d1-938b-17f20c643cb7\tool-results'
MASTERFILE = r'C:\Users\Glenn\OneDrive\Desktop\kitsch-sales-dashboard\4 Customer Masterfile - April 2026.xlsx'

MASTERFILE_L5_REMAP = {
    'Boots UK':             'Boots UK Ltd.',
    'Marmaxx Group':        'Off-Price',
    'Other UK Key Accounts':'International',
    'LookFantastic':        'International',
    'Other':                'Other - Misc',
}

# Customers whose Col A name contains these substrings map to a specific channel,
# overriding the "Other - Misc" they inherit from Level 5 col H in the masterfile.
NAME_CHANNEL_OVERRIDE = [
    ('nordstrom rack',  'Nordstrom Rack/Hautelook'),
    ('hautelook',       'Nordstrom Rack/Hautelook'),
    ('scheels',         'Scheels'),
    ('kroger',          'KROGER'),
    ('heb grocery',     'HEB'),
    (' heb ',           'HEB'),
    ('meijer',          'Meijer'),
    ('the marmaxx',     'Off-Price'),
    ('tjx',             'Off-Price'),
    ('wmi (tjx',        'Off-Price'),
    ('boots uk',        'Boots UK Ltd.'),
    ('whole foods',     'Whole Foods/Sprouts'),
    ('sprouts',         'Whole Foods/Sprouts'),
]

def name_override(customer_name):
    lower = customer_name.lower()
    if lower == 'heb':
        return 'HEB'
    for fragment, channel in NAME_CHANNEL_OVERRIDE:
        if fragment in lower:
            return channel
    return None

ID_LOOKUP_FILE = os.path.join(os.path.dirname(__file__), 'customer_id_lookup.json')
id_lookup = {}
if os.path.exists(ID_LOOKUP_FILE):
    id_lookup = json.load(open(ID_LOOKUP_FILE, encoding='utf-8'))
    print(f'ID lookup: {len(id_lookup)} entries loaded')

masterfile = {}
wb = openpyxl.load_workbook(MASTERFILE, read_only=True, data_only=True)
ws = wb['Customer master']
DATA_START_ROW = 5   # 0-based: row 6 in Excel is where actual data begins
CUST_COL = 0         # Column A
L5_COL   = 7         # Column H = Level 5
for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
    if r_idx < DATA_START_ROW:
        continue
    if len(row) <= L5_COL:
        continue
    cust, l5 = row[CUST_COL], row[L5_COL]
    if cust and l5:
        cust = str(cust).strip()
        l5   = MASTERFILE_L5_REMAP.get(str(l5).strip(), str(l5).strip())
        masterfile[cust] = l5
wb.close()
print(f'Masterfile: {len(masterfile)} entries loaded')

CATEGORY_TO_L5 = {
    'Kitsch DTC':              'Kitsch DTC',
    'Amazon':                  'Amazon',
    'Ulta Inc.':               'Ulta Inc.',
    'Ulta':                    'Ulta Inc.',
    'Target':                  'Target',
    'Faire':                   'Faire',
    'CVS Health':              'CVS Health',
    'CVS':                     'CVS Health',
    'Walgreens':               'Walgreens',
    'Walgreens Corporation':   'Walgreens',
    'Walmart':                 'Walmart',
    'Walmart USA':             'Walmart',
    'Whole Foods/Sprouts':     'Whole Foods/Sprouts',
    'Whole Foods':             'Whole Foods/Sprouts',
    'Sprouts':                 'Whole Foods/Sprouts',
    "Kohl's Inc.":             "Kohl's Inc.",
    "Kohl's Inc":              "Kohl's Inc.",
    "Kohl's":                  "Kohl's Inc.",
    'Meijer':                  'Meijer',
    'Boots UK':                'Boots UK Ltd.',
    'Boots UK Ltd.':           'Boots UK Ltd.',
    'HEB':                     'HEB',
    'KROGER':                  'KROGER',
    'Kroger':                  'KROGER',
    'Nordstrom Rack/Hautelook':'Nordstrom Rack/Hautelook',
    'Nordstrom Rack':          'Nordstrom Rack/Hautelook',
    'Scheels':                 'Scheels',
    'Marmaxx Group':           'Off-Price',
    'Off-Price':               'Off-Price',
    'Business Development':    'Business Development',
    'Grocery':                 'Grocery',
    'Specialty':               'Specialty',
    'International':           'International',
    'Other UK Key Accounts':   'International',
    'LookFantastic':           'International',
}

def resolve(name, cat):
    name = str(name or '').strip()
    cat  = str(cat  or '').strip()
    if 'shopify' in name.lower() or cat == 'Kitsch DTC':
        return 'Kitsch DTC'
    # Resolve numeric NS internal ID → company name
    if name.isdigit() and name in id_lookup:
        name = id_lookup[name]
    # Masterfile lookup (Col A → Col H Level 5)
    l5 = masterfile.get(name)
    if l5 and l5 != 'Other - Misc':
        return l5
    # Name-based override for channels that have "Other" in Level 5
    override = name_override(name)
    if override:
        return override
    # Category fallback
    if cat in CATEGORY_TO_L5:
        return CATEGORY_TO_L5[cat]
    # If masterfile found "Other - Misc", honour it; else unknown
    return 'Other - Misc'

today_prefixes = ['1782869', '1782870', '1782871', '1782872', '1782873']
all_files = sorted(glob.glob(os.path.join(TOOL_DIR, 'mcp-9f962cba*ns_runSavedSearch*.txt')))
files = [f for f in all_files if any(p in f for p in today_prefixes)]
print(f'Processing {len(files)} files from today')

totals = {}
total_rows = 0
seen_hashes = set()

for fpath in files:
    content = open(fpath, encoding='utf-8').read()
    try:
        data = json.loads(content)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get('items', [])
        else:
            rows = []
    except Exception as e:
        print(f'  SKIP {os.path.basename(fpath)}: {e}')
        continue

    new_rows = 0
    for row in rows:
        h = str(row.get('Name','')) + '|' + str(row.get('Amount','')) + '|' + str(row.get('Item',''))
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        name = str(row.get('Name') or '').strip()
        cat  = str(row.get('Customer Category') or '').strip()
        amt  = float(row.get('Amount') or 0)
        l5   = resolve(name, cat)
        totals[l5] = totals.get(l5, 0) + amt
        total_rows += 1
        new_rows   += 1
    print(f'  {os.path.basename(fpath)}: {new_rows} new rows')

grand = sum(totals.values())
print(f'\nTotal unique rows: {total_rows:,}')
print(f'Grand total: ${grand:,.0f}')
print()
print('--- By Channel ---')
for ch, v in sorted(totals.items(), key=lambda x: -x[1]):
    print(f'  {ch:<35} ${v:>12,.0f}')

# Separate DTC/Amazon/WS
dtc = totals.get('Kitsch DTC', 0)
amz = totals.get('Amazon', 0)
ws_channels = ['Ulta Inc.','Target','Faire','CVS Health','Walgreens','Walmart',
               'Whole Foods/Sprouts',"Kohl's Inc.",'Meijer','Boots UK Ltd.',
               'HEB','KROGER','Nordstrom Rack/Hautelook','Scheels','Off-Price',
               'Business Development','Grocery','Specialty','International','Other - Misc']
ws_total = sum(totals.get(ch, 0) for ch in ws_channels)
print(f'\n--- Summary ---')
print(f'  DTC:       ${dtc:>12,.0f}')
print(f'  Amazon:    ${amz:>12,.0f}')
print(f'  Wholesale: ${ws_total:>12,.0f}')
print(f'  GRAND:     ${dtc+amz+ws_total:>12,.0f}')
