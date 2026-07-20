# GC Stats — Sortable Team Stats Website

Turns a [GameChanger](https://gc.com/) team-stats CSV export into a single,
self-contained `index.html` you can open in any browser or host anywhere.

The generated page has:

- **Batting / Pitching / Fielding** tabs
- **Sortable columns** — click any header (click again to reverse)
- **Sensible default sort per tab** — Batting by AVG, Pitching by IP,
  Fielding by FPCT (highest first)
- **Glossary tooltips** — hover a column header for its definition
- **Name filter** and a pinned, highlighted **Totals** row
- **Player-name sanitization** — defaults to initials + jersey number so real
  names are never published (see below)
- **Team logo** in the header and as the browser-tab icon (optional)
- Light/dark theme and horizontal scroll for the wide stat tables

Everything (data, glossary, and code) is embedded in the one HTML file, so
there are no external dependencies to host.

## Requirements

- Python 3 (standard library only — nothing to `pip install`)

## Workflow

1. **Export** your team's stats from GameChanger as a CSV.
2. **Drop** the CSV into the `stats/` directory.
3. **Generate** the site:

   ```bash
   python3 generate_site.py
   ```

   With no arguments it uses the newest `.csv` in `stats/` and writes
   `index.html`. It prints what it read and wrote, e.g.:

   ```
   Read:  stats/SWABL Royals Spring 2026 Stats.csv
   Names: initials-number
   Logo:  royals.png (embedded)
   Wrote: index.html  (16 players; Batting 51 stats, Pitching 94 stats, Fielding 26 stats; 145 glossary terms)
   ```

   (The `Logo:` line only appears when a logo image is found — see below.)

4. **View / share** `index.html` (see below).

### Options

```bash
python3 generate_site.py                        # newest CSV in ./stats -> index.html
python3 generate_site.py path/to/export.csv     # use a specific CSV
python3 generate_site.py export.csv -o out.html # choose the output filename
python3 generate_site.py --logo path/to/img.png # embed a specific logo
python3 generate_site.py --names full            # show real names (local use)
```

The page title is taken from the CSV filename (a trailing " Stats" is dropped),
so `SWABL Royals Spring 2026 Stats.csv` becomes "SWABL Royals Spring 2026".

### Player names / privacy

The raw GameChanger export contains players' real names. To avoid publishing
them, the generator sanitizes names by default and the raw CSVs are gitignored
(`stats/*.csv`), so only the sanitized `index.html` ends up in the repo.

Choose the display style with `--names`:

| `--names`         | Shows                    | Example       | Notes                                   |
| ----------------- | ------------------------ | ------------- | --------------------------------------- |
| `initials-number` | jersey # + initials      | `7`  `JD`     | **Default.** # column breaks ties.      |
| `initials`        | initials only            | `JD`          | Can collide (e.g. two `JD`).            |
| `first-last`      | first name + last initial| `Jane D.`     | Unique here, but more identifying.      |
| `number`          | jersey number only       | `7`           | Most anonymous.                         |
| `full`            | real first & last name   | `Doe` `Jane`  | Local use only — do **not** publish.    |

For a private local copy with real names, run `--names full -o private.html`
(that file is not gitignored by name, so keep it out of the repo).

### Logo

If a `royals.png` (or `logo.png` / `logo.svg` / `logo.jpg`) is present in the
project folder, it is embedded into the page header and used as the browser-tab
icon. Point at a specific file with `--logo path/to/image`. The image is
inlined as a data URI, so the generated `index.html` stays a single
self-contained file. Omit the logo and the header simply renders without one.

## Viewing it locally / on your network

`index.html` opens directly in a browser (double-click it). To share it with
others on your local network, serve the directory:

```bash
python3 -m http.server 8000 --bind 0.0.0.0
```

Then browse to:

- `http://localhost:8000/` on the same machine
- `http://<your-lan-ip>:8000/` from other devices on the network
  (find your address with `hostname -I`)

If teammates on the network can't connect, check that the host firewall allows
the port.

## Hosting it for the team

Because it's a single static file with no dependencies, it works on any static
host — for example:

- A shared/internal web server (copy `index.html` into the web root)
- GitHub Pages, Netlify, Cloudflare Pages, S3, etc.

## Updating for a new export

Re-exports overwrite nothing automatically — just repeat the workflow: drop the
new CSV in `stats/` and re-run `python3 generate_site.py`. The script derives
the Batting/Pitching/Fielding section boundaries from the export's own headers,
so it keeps working even if GameChanger adds or removes individual stats.

## Files

| Path                | Purpose                                             |
| ------------------- | --------------------------------------------------- |
| `generate_site.py`  | Generator script (CSV → HTML)                       |
| `stats/*.csv`       | GameChanger exports (input; gitignored — kept local)|
| `royals.png`        | Team logo, embedded into the page (optional input)  |
| `index.html`        | Generated website (output; sanitized names)         |
