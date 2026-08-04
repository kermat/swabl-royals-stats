#!/usr/bin/env python3
"""Generate a sortable stats website from a GameChanger CSV export.

The GameChanger team-stats export is one very wide row per player, split into
three column groups (Batting, Pitching, Fielding), followed by a Totals row and
a Glossary row. This script parses that structure and writes a single,
self-contained ``index.html`` (data, glossary, and code all embedded) that can
be opened directly in a browser or dropped onto any static host.

Usage:
    python3 generate_site.py                       # auto-find CSV in ./stats
    python3 generate_site.py path/to/export.csv    # explicit input
    python3 generate_site.py export.csv -o out.html # explicit output

Re-run it any time you pull a fresh export from GameChanger.
"""

import argparse
import base64
import csv
import datetime
import glob
import json
import os
import sys

# Candidate logo filenames, tried in order, looked for next to the output.
LOGO_CANDIDATES = ["royals.png", "logo.png", "logo.svg", "logo.jpg", "logo.jpeg"]
LOGO_MIME = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Raw identity columns that lead every section in the export (Number, Last, First).
ID_INDICES = [0, 1, 2]

# Name-sanitization schemes. Each maps to the identity columns shown in the
# output. "initials-number" is the default: initials plus the jersey-number
# column disambiguates same-initial players. "full" keeps real names.
NAME_SCHEMES = ["initials-number", "initials", "first-last", "number", "full"]
DEFAULT_NAME_SCHEME = "initials-number"


def identity_columns(scheme):
    """Header names for the identity columns produced by a scheme."""
    return {
        "full": ["Number", "Last", "First"],
        "number": ["Number"],
        "initials": ["Player"],
        "initials-number": ["Number", "Player"],
        "first-last": ["Number", "Player"],
    }[scheme]


def identity_values(scheme, number, last, first):
    """Sanitized identity cell values for one player row under a scheme."""
    is_totals = number.strip() == "Totals"
    fi = first.strip()[:1].upper()
    li = last.strip()[:1].upper()
    if scheme == "full":
        return [number, last, first]
    if scheme == "number":
        return [number]
    if scheme == "initials":
        return ["Totals" if is_totals else (fi + li)]
    if scheme == "initials-number":
        return [number, "" if is_totals else (fi + li)]
    if scheme == "first-last":
        label = first if not last.strip() else f"{first} {li}."
        return [number, "" if is_totals else label]
    raise ValueError(f"unknown name scheme: {scheme}")


def find_logo(explicit=None):
    """Return a path to a logo image, or None. Prefers an explicit path."""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for name in LOGO_CANDIDATES:
        if os.path.exists(name):
            return name
    return None


def logo_data_uri(path):
    """Base64-encode an image file into a data: URI for inline embedding."""
    ext = os.path.splitext(path)[1].lower()
    mime = LOGO_MIME.get(ext, "application/octet-stream")
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def find_default_csv():
    """Return the CSV in ./stats, preferring the most recently modified one."""
    candidates = sorted(
        glob.glob(os.path.join("stats", "*.csv")),
        key=os.path.getmtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def parse_csv(path, scheme=DEFAULT_NAME_SCHEME):
    """Parse the GameChanger export into a payload dict for the template."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))

    if len(rows) < 3:
        sys.exit(f"error: {path} does not look like a GameChanger export")

    section_row = rows[0]  # sparse row with 'Batting'/'Pitching'/'Fielding' labels
    header_row = rows[1]   # full column headers

    # Locate each section's starting column from the sparse label row, then
    # derive [start, end) spans so we don't hard-code column counts (they change
    # as GameChanger adds/removes stats).
    order = ["Batting", "Pitching", "Fielding"]
    starts = {}
    for i, label in enumerate(section_row):
        name = label.strip()
        if name in order:
            starts[name] = i
    missing = [s for s in order if s not in starts]
    if missing:
        sys.exit(f"error: could not find section header(s): {', '.join(missing)}")

    bounds = {}
    present = [s for s in order if s in starts]
    for idx, name in enumerate(present):
        start = starts[name]
        end = starts[present[idx + 1]] if idx + 1 < len(present) else len(header_row)
        bounds[name] = (start, end)

    # Glossary: the final row holds "TERM=definition" cells.
    glossary = {}
    for cell in rows[-1]:
        if "=" in cell:
            key, val = cell.split("=", 1)
            glossary[key.strip()] = val.strip()

    # Player + Totals rows: everything after the header that has a Number cell,
    # excluding the glossary row itself.
    data_rows = []
    for r in rows[2:]:
        if not r or not r[0].strip():
            continue
        if r[0].strip() == "Glossary":
            continue
        data_rows.append(r)

    id_headers = identity_columns(scheme)

    def build_section(name):
        start, end = bounds[name]
        stat_headers = [header_row[i] for i in range(start, end)]
        columns = id_headers + stat_headers
        out_rows = []
        for r in data_rows:
            number = r[0] if len(r) > 0 else ""
            last = r[1] if len(r) > 1 else ""
            first = r[2] if len(r) > 2 else ""
            ids = identity_values(scheme, number, last, first)
            stats = [(r[i] if i < len(r) else "") for i in range(start, end)]
            out_rows.append(ids + stats)
        return {"columns": columns, "rows": out_rows}

    # Title from the filename, e.g. "SWABL Royals Spring 2026 Stats.csv".
    base = os.path.splitext(os.path.basename(path))[0]
    for suffix in (" Stats", " stats"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    return {
        "title": base.strip(),
        "glossary": glossary,
        "idCount": len(id_headers),
        "sections": {name: build_section(name) for name in present},
    }


# ---------------------------------------------------------------------------
# HTML template. __DATA__ is replaced with the JSON payload. Braces are left
# untouched (no f-strings) so the CSS/JS survive verbatim.
# ---------------------------------------------------------------------------
TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ Stats</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --panel-2: #1d222b;
    --line: #2a303c;
    --text: #e7ebf0;
    --muted: #93a0b4;
    --accent: #2f7cf6;
    --accent-soft: #12386e;
    --royal: #1e3a8a;
    --gold: #d4a017;
    --totals: #202634;
    --hover: #202634;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f4f6fa;
      --panel: #ffffff;
      --panel-2: #eef1f6;
      --line: #dde3ec;
      --text: #16202e;
      --muted: #5b6878;
      --accent: #1f6fe0;
      --accent-soft: #dceafc;
      --totals: #eef2f9;
      --hover: #f1f5fb;
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  header.hero {
    padding: 22px 20px 16px;
    background: linear-gradient(135deg, var(--royal), #0b1b45);
    color: #fff;
    border-bottom: 3px solid var(--gold);
  }
  .hero-inner { display: flex; align-items: center; gap: 18px; }
  .hero-logo {
    height: 72px; width: auto; flex: 0 0 auto;
    filter: drop-shadow(0 2px 6px rgba(0,0,0,.45));
  }
  .hero-text { min-width: 0; }
  header.hero h1 { margin: 0; font-size: 22px; letter-spacing: .3px; }
  header.hero p { margin: 4px 0 0; color: #c9d6f5; font-size: 13px; }
  .updated {
    margin-top: 8px; display: inline-block;
    background: rgba(255,255,255,.12); color: #fff;
    border: 1px solid rgba(212,160,23,.55);
    padding: 3px 10px; border-radius: 999px;
    font-size: 12px; font-weight: 600;
  }
  .updated:empty { display: none; }
  @media (max-width: 520px) {
    .hero-logo { height: 52px; }
    header.hero h1 { font-size: 19px; }
  }
  .wrap { padding: 16px 16px 60px; max-width: 100%; }
  .controls {
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    margin-bottom: 14px;
  }
  .tabs { display: flex; gap: 6px; flex-wrap: wrap; }
  .tab {
    background: var(--panel); color: var(--muted);
    border: 1px solid var(--line); border-radius: 8px;
    padding: 8px 16px; cursor: pointer; font-weight: 600; font-size: 13px;
  }
  .tab:hover { color: var(--text); }
  .tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .search {
    margin-left: auto; background: var(--panel); color: var(--text);
    border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px;
    font-size: 13px; min-width: 180px;
  }
  .search::placeholder { color: var(--muted); }
  .table-scroll {
    overflow-x: auto; border: 1px solid var(--line); border-radius: 10px;
    background: var(--panel);
    -webkit-overflow-scrolling: touch;
  }
  table { border-collapse: separate; border-spacing: 0; width: 100%; }
  th, td { white-space: nowrap; text-align: right; padding: 8px 10px; font-variant-numeric: tabular-nums; }
  thead th {
    position: sticky; top: 0; z-index: 3;
    background: var(--panel-2); color: var(--muted);
    border-bottom: 2px solid var(--line);
    cursor: pointer; user-select: none; font-size: 12px; font-weight: 700;
  }
  thead th:hover { color: var(--text); }
  thead th .arrow { color: var(--accent); font-size: 11px; margin-left: 2px; }
  tbody td { border-bottom: 1px solid var(--line); color: var(--text); }
  tbody tr:hover td { background: var(--hover); }
  /* identity columns: left-align + sticky */
  th.id, td.id { text-align: left; }
  th.stick, td.stick {
    position: sticky; z-index: 2; background: var(--panel);
  }
  thead th.stick { z-index: 4; background: var(--panel-2); }
  tbody tr:hover td.stick { background: var(--hover); }
  .c0 { left: 0; }
  .c1 { left: var(--w0); }
  th.stick, td.stick { border-right: 1px solid var(--line); }
  tr.totals td { background: var(--totals); font-weight: 700; border-top: 2px solid var(--gold); }
  tr.totals td.stick { background: var(--totals); }
  td.name { font-weight: 600; }
  .num { color: var(--muted); }
  .hint { color: var(--muted); font-size: 12px; margin: 10px 2px 0; }
  .sorted { color: var(--text) !important; }
  footer { color: var(--muted); font-size: 12px; padding: 20px; text-align: center; }
  /* tooltip */
  #tip {
    position: fixed; z-index: 50; max-width: 280px;
    background: #0b0e13; color: #e7ebf0; border: 1px solid var(--line);
    padding: 8px 10px; border-radius: 8px; font-size: 12px; line-height: 1.35;
    pointer-events: none; opacity: 0; transition: opacity .1s; box-shadow: 0 6px 24px rgba(0,0,0,.4);
  }
  #tip b { color: var(--gold); }
</style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    __LOGO_IMG__
    <div class="hero-text">
      <h1 id="pageTitle"></h1>
      <p>Team stats — sortable. Click any column header to sort. Hover a header for its definition.</p>
      <div class="updated" id="updated"></div>
    </div>
  </div>
</header>
<div class="wrap">
  <div class="controls">
    <div class="tabs" id="tabs"></div>
    <input class="search" id="search" type="search" placeholder="Filter by name…" autocomplete="off">
  </div>
  <div class="table-scroll">
    <table id="tbl"><thead></thead><tbody></tbody></table>
  </div>
  <p class="hint" id="hint"></p>
</div>
<div id="tip"></div>
<footer>Generated from GameChanger export • Blank / “-” / “N/A” values sort to the bottom.</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const GLOSS = DATA.glossary;
document.getElementById('pageTitle').textContent = DATA.title + ' — Team Stats';
document.getElementById('updated').textContent = DATA.updated ? 'Updated ' + DATA.updated : '';

// Reuse the embedded logo as the browser-tab favicon (no duplicated data).
(function(){
  const img = document.querySelector('.hero-logo');
  if (!img) return;
  const link = document.createElement('link');
  link.rel = 'icon';
  link.href = img.src;
  document.head.appendChild(link);
})();

const ID_COUNT = DATA.idCount; // number of identity columns (varies by name scheme)
// Column each tab sorts by (descending) on load / when selected.
const DEFAULT_SORT = { Batting: 'AVG', Pitching: 'IP', Fielding: 'FPCT' };
let current = Object.keys(DATA.sections)[0];
let sortCol = null, sortDir = -1; // -1 desc, 1 asc
let filter = '';

function applyDefaultSort(){
  const cols = DATA.sections[current].columns;
  const want = DEFAULT_SORT[current];
  const i = want ? cols.indexOf(want) : -1;
  sortCol = i >= 0 ? i : null;
  sortDir = -1; // highest first
}

function parseNum(v){
  if (v == null) return null;
  const s = String(v).trim();
  if (s === '' || s === '-' || s === 'N/A' || s === '--') return null;
  // e.g. ".286", "100.0", "8-10" -> take leading number
  const m = s.match(/^-?\.?\d[\d.]*/);
  if (!m) return null;
  const n = parseFloat(m[0]);
  return isNaN(n) ? null : n;
}
function isTotalsRow(r){ return String(r[0]).trim().toLowerCase() === 'totals'; }

function buildTabs(){
  const el = document.getElementById('tabs'); el.innerHTML = '';
  Object.keys(DATA.sections).forEach(name => {
    const b = document.createElement('button');
    b.className = 'tab' + (name === current ? ' active' : '');
    b.textContent = name;
    b.onclick = () => { current = name; applyDefaultSort(); render(); buildTabs(); };
    el.appendChild(b);
  });
}

function render(){
  const sec = DATA.sections[current];
  const cols = sec.columns;
  // first identity column that isn't the jersey number -> the "name" column
  const nameCol = cols.findIndex((c,i) => i < ID_COUNT && c !== 'Number');
  const thead = document.querySelector('#tbl thead');
  const tbody = document.querySelector('#tbl tbody');

  // header
  const trh = document.createElement('tr');
  cols.forEach((c, ci) => {
    const th = document.createElement('th');
    const idCol = ci < ID_COUNT;
    th.className = (idCol ? 'id ' : '') + (ci < 2 ? 'stick c'+ci : '');
    th.dataset.ci = ci;
    let label = (c === 'Number') ? '#' : c;
    th.innerHTML = label + (sortCol === ci ? ' <span class="arrow">'+(sortDir<0?'▼':'▲')+'</span>' : '');
    if (sortCol === ci) th.classList.add('sorted');
    th.onclick = () => {
      if (sortCol === ci) sortDir = -sortDir;
      else { sortCol = ci; sortDir = idCol ? 1 : -1; }
      render();
    };
    // tooltip
    const g = GLOSS[c];
    th.addEventListener('mousemove', e => showTip(e, c, g));
    th.addEventListener('mouseleave', hideTip);
    trh.appendChild(th);
  });
  thead.innerHTML = ''; thead.appendChild(trh);

  // rows: separate players from totals
  let players = sec.rows.filter(r => !isTotalsRow(r));
  const totals = sec.rows.filter(isTotalsRow);

  if (filter){
    const f = filter.toLowerCase();
    players = players.filter(r =>
      r.slice(0, ID_COUNT).join(' ').toLowerCase().includes(f));
  }

  if (sortCol != null){
    const ci = sortCol;
    const idCol = ci < ID_COUNT;
    players.sort((a,b) => {
      if (idCol && cols[ci] !== 'Number'){
        const av=(a[ci]||'').toLowerCase(), bv=(b[ci]||'').toLowerCase();
        return av<bv?-1*sortDir:av>bv?1*sortDir:0;
      }
      const an = parseNum(a[ci]), bn = parseNum(b[ci]);
      if (an == null && bn == null) return 0;
      if (an == null) return 1;   // nulls always bottom
      if (bn == null) return -1;
      return (an - bn) * sortDir;
    });
  }

  tbody.innerHTML = '';
  const addRow = (r, isTot) => {
    const tr = document.createElement('tr');
    if (isTot) tr.className = 'totals';
    r.forEach((v, ci) => {
      const td = document.createElement('td');
      const idCol = ci < ID_COUNT;
      const isNum = cols[ci] === 'Number';
      td.className = (idCol ? 'id ' : '') + (ci < 2 ? 'stick c'+ci : '') + (ci===nameCol?' name':'') + (isNum?' num':'');
      td.textContent = (v === '' ? '' : v);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  };
  players.forEach(r => addRow(r, false));
  totals.forEach(r => addRow(r, true));

  // set sticky offsets after render
  requestAnimationFrame(setStickyOffsets);

  document.getElementById('hint').textContent =
    players.length + ' players' + (filter ? ' (filtered)' : '') + ' • ' + (cols.length - ID_COUNT) + ' stats in ' + current;
}

function setStickyOffsets(){
  const firstRow = document.querySelector('#tbl tbody tr') || document.querySelector('#tbl thead tr');
  if (!firstRow) return;
  const cells = firstRow.querySelectorAll('.c0');
  if (cells.length){
    const w0 = cells[0].getBoundingClientRect().width;
    document.documentElement.style.setProperty('--w0', w0 + 'px');
  }
}

// tooltip
const tip = document.getElementById('tip');
function showTip(e, term, def){
  if (!def && !term) { hideTip(); return; }
  tip.innerHTML = '<b>'+term+'</b>' + (def ? ' — '+def : '');
  tip.style.opacity = '1';
  let x = e.clientX + 14, y = e.clientY + 16;
  if (x + 290 > window.innerWidth) x = window.innerWidth - 300;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
function hideTip(){ tip.style.opacity = '0'; }

document.getElementById('search').addEventListener('input', e => { filter = e.target.value; render(); });
window.addEventListener('resize', setStickyOffsets);

applyDefaultSort();
buildTabs();
render();
</script>
</body>
</html>'''


def render_html(payload, logo_uri=None):
    data_json = json.dumps(payload, ensure_ascii=False)
    # Guard against a stray "</script>" inside data closing our script tag early.
    data_json = data_json.replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data_json)
    html = html.replace("__TITLE__", payload["title"] or "Team")
    if logo_uri:
        logo_img = f'<img class="hero-logo" src="{logo_uri}" alt="{payload["title"]} logo">'
    else:
        logo_img = ""
    html = html.replace("__LOGO_IMG__", logo_img)
    return html


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="GameChanger CSV export (default: newest in ./stats)")
    ap.add_argument("-o", "--output", default="index.html", help="output HTML file (default: index.html)")
    ap.add_argument("--logo", help=f"logo image to embed (default: first of {', '.join(LOGO_CANDIDATES)} if present)")
    ap.add_argument("--names", choices=NAME_SCHEMES, default=DEFAULT_NAME_SCHEME,
                    help="how to display player names (default: %(default)s). "
                         "initials-number=initials + jersey # column; "
                         "initials=initials only; first-last=first name + last initial; "
                         "number=jersey # only; full=real names")
    args = ap.parse_args()

    csv_path = args.csv or find_default_csv()
    if not csv_path:
        sys.exit("error: no CSV given and none found in ./stats")
    if not os.path.exists(csv_path):
        sys.exit(f"error: file not found: {csv_path}")

    payload = parse_csv(csv_path, scheme=args.names)
    now = datetime.datetime.now()
    payload["updated"] = f"{now:%B} {now.day}, {now.year}"
    logo_path = find_logo(args.logo)
    logo_uri = logo_data_uri(logo_path) if logo_path else None
    html = render_html(payload, logo_uri)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(html)

    id_count = payload["idCount"]
    counts = ", ".join(
        f"{name} {len(sec['columns']) - id_count} stats" for name, sec in payload["sections"].items()
    )
    n_players = sum(1 for r in next(iter(payload["sections"].values()))["rows"]
                    if str(r[0]).strip().lower() != "totals")
    print(f"Read:  {csv_path}")
    print(f"Names: {args.names}")
    if logo_path:
        print(f"Logo:  {logo_path} (embedded)")
    print(f"Wrote: {args.output}  ({n_players} players; {counts}; {len(payload['glossary'])} glossary terms)")


if __name__ == "__main__":
    main()
