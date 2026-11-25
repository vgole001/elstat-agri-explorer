# Greece agri sector

ELSTAT regional agricultural tables → one long CSV (`data/agri.csv`) → static map dashboard.

**Live site:** https://vgole001.github.io/elstat-agri-explorer/ (hosted on GitHub Pages from the `main` branch; push to `main` to update it)

## Quick start (PowerShell)

Always run from the **project root** (the folder that contains `parser\`, `raw_data\`, `dashboard\`),
not from inside `parser\` or `dashboard\`.

**First time only** – create the environment and install the packages:

```powershell
cd C:\Users\v_gkoles\Desktop\Projects\greece-agri-sector
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Every time** – after adding or changing Excel files in `raw_data\`:

```powershell
cd C:\Users\v_gkoles\Desktop\Projects\greece-agri-sector
.venv\Scripts\Activate.ps1          # skip if the prompt already starts with (.venv)

python -m parser run                # Excel files -> data\agri.csv + data\agri.json
python -m analysis                  # anomaly scan -> data\anomalies.csv / .md / .json
python -m http.server 8000          # start the local web server (leave this window open)
```

Then open **http://localhost:8000/dashboard/** in the browser. Stop the server with `Ctrl+C`.

**Check a single file** (what the parser detects):

```powershell
python -m parser inspect raw_data\crops\cereals_for_grain\2024\cereals_for_grain.xlsx              # columns + regions
python -m parser inspect raw_data\crops\cereals_for_grain\2024\cereals_for_grain.xlsx --no-regions # columns only
python -m parser inspect raw_data\crops\cereals_for_grain\2024\cereals_for_grain.xlsx --item durum # area, production, yield per region
python -m parser run --only cereals_for_grain                                                      # parse one dataset only
python -m parser run --only crops                                                                  # parse one sector only
python -m parser run --skip-failed                                                                 # write what parses, list failed files
```

| Problem | Fix |
|---|---|
| `No module named parser` | you are not in the project root: `cd` to it first |
| `.venv\Scripts\python : The module '.venv' could not be loaded` | prefix with `.\` or activate the venv and just type `python` |
| `No module named pandas` / `openpyxl` / `xlrd` | the venv is not active, or run `pip install -r requirements.txt` |
| Page says "Could not load data" | run `python -m parser run`, and start the server from the project root |
| Port 8000 in use | `python -m http.server 8080` and open `http://localhost:8080/dashboard/` |

## Anomaly scan (offline)

```
python -m parser run       # first, so data/agri.json is current
python -m analysis         # -> data/anomalies.csv (full list) + data/anomalies.md (readable report)
```

Scans every dataset, crop, region and year and lists what needs checking, whatever the cause:

| kind | meaning | usually |
|---|---|---|
| name_gap | crop name only in some years | ELSTAT renamed it: map it in `parser/items.py` |
| spike | x3 jump or dip for one year, then back | data / entry error |
| yield_out_of_range | production ÷ area far from usual (and from the place's own history) | unit error or typo |
| share_shift | a place's share of Greece's total leaves its usual range (other years), and the place moved differently from the rest of Greece | real local change, or error |
| hard_change | national total moves x1.5 or ÷1.5 in a year | national event, or error in a whole table |
| appeared / disappeared | from nothing / to nothing | new crop, or missing data |
| yield_change | yield moved ≥35 % differently from the rest of Greece, outside its usual ratio to Greece's yield | local event (e.g. flood), or error |

Places are compared with the **rest of Greece** (Greece minus the place), so a big region does not
hide its own change by pulling the national total with it.

Tiny amounts are ignored (below 1 % of Greece's total or 1,000 stremmas / 100 tons).
*high* = large in absolute terms (≥5 % of Greece and ≥10,000 stremmas / 2,000 tons) or a likely error.
When one regional unit explains its region's change, only the unit is listed; area and production
flags for the same event are merged. Thresholds are at the top of `analysis/anomalies.py`.

Crop names that ELSTAT changed between years are mapped in `parser/items.py`
(e.g. Maize "grown alone" → "without intercropping").

## Dashboard

A single static page (`dashboard/`: `index.html`, `app.js`, `style.css`) using Leaflet. No build step.

```
python -m parser run                 # also writes data/agri.json for the page
python -m http.server 8000           # from the project root
```

Open http://localhost:8000/dashboard/ (opening the file directly does not work: browsers block
loading data files from `file://`).

- Dropdowns: Dataset → Category → Item → (Use, for grape production) → Metric → Year → Show.
- Map: the 13 regions coloured by the selection; "Share of Greece (%)" by default, or raw values.
- Side panel: Greece by default; click a region (map or list) for its area, production, yield,
  share of Greece and its regional units. The trend chart appears once more than one year is loaded.
- Yield = production ÷ area (kg/stremma), calculated in the page only where both exist.
  Grape production split by use is summed into "All uses" for the yield.
- The selection is kept in the URL, so a link reopens the same view.
- With more than one year: a **share of Greece by year** table (regions, or a region's units) with
  cells flagged by the anomaly scan marked ⚠, and a **flags for this crop** list; click a flag to
  jump to it. Run `python -m analysis` to refresh the flags (`data/anomalies.json`).

Region shapes: `dashboard/data/regions.geojson`, built by `tools/build_geo.py` from Eurostat GISCO
NUTS2 2021 (© EuroGeographics). Eurostat's current codes (EL51…) are mapped to the project's GR codes.
Shapes for the 74 regional units are not available yet; units are listed in the side panel.

## Raw data

```
raw_data/<sector>/<dataset>/<year>/<file>.xlsx      e.g. raw_data/crops/vegetables/2024/vegetables.xlsx
```

- The folder names are the source of truth for the **sector** (`crops`, `livestock`), the **dataset** and the **year**.
- Each sector has its own base parser, registered in `parser/tables/__init__.py` (`SECTORS`).

### Livestock

One dataset folder per animal, e.g. `raw_data/livestock/bovine_animals/2025/bovine_animals.xls`
(next: `sheep`, `goats`, ...). `parser/livestock.py` expects the layout of the bovine table:

- two kinds of table, told apart by the title:
  - `Table 1: Holdings with Bovine animals by region broken down by size classes, year 2025`
    → metric `holdings`, category **Holdings by herd size**, items = size classes
  - `Table 7: Sheep by region broken down by main categories, year 2025`
    → metric `animals` (heads), category **Animals by type**, items = ewes, rams, …
  The year must match the year folder and the animal must match the dataset folder
  ("Sheep" → `sheep/`), so a file in the wrong folder is refused. ELSTAT header typos are fixed in
  `LABEL_FIXES` in `parser/livestock.py`.
- a `Region` header row, then a `Total` row (Greece) and the 13 regions in Greeklish
  (`Kentriki Makedonia`, …; spellings are in `ALIASES` in `parser/regions.py`). There are no regional units.
- columns = herd-size classes (`Total`, `1-4`, …, `50 and over`) → item. Classes must add up to
  `Total`, and regions must add up to Greece. Values are survey estimates and can have decimals.

A new measure in a title (e.g. number of animals) stops the parser. Add it to `MEASURES` in
`parser/livestock.py` and its unit to `UNITS` in `parser/base.py`, then to `UNITS`/`METRIC_LABEL`
in `dashboard/app.js`. If an animal's table is laid out differently, subclass `LivestockTable` and
register it in `OVERRIDES`.
- Excel files are never modified. Table differences are handled in the parser.

## Parser

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

.venv\Scripts\python -m parser run                      # all files -> data/agri.csv
.venv\Scripts\python -m parser run --only vegetables    # selected dataset (or sector) folders
.venv\Scripts\python -m parser inspect raw_data\crops\vegetables\2024\vegetables.xlsx
```

`run` stops with an error naming the file, year and each problem (unknown region name,
failed sum check, unreadable header, ...) and writes nothing until every file passes.
`inspect` shows what the parser detected in one file: anchor rows, columns, metrics.

| File | Role |
|---|---|
| `parser/base.py` | Generic crops parser (anchors, headers, metrics, checks, output) |
| `parser/livestock.py` | Livestock parser: one animal per dataset, size-class columns, regions only |
| `parser/regions.py` | Greece / 13 regions (NUTS2) / 74 regional units (ELSTAT codes), name aliases |
| `parser/items.py` | Crop names ELSTAT changed between years → one name |
| `parser/workbook.py` | Reads visible sheets of an `.xlsx` / `.xls` (hidden sheets are ignored) |
| `analysis/anomalies.py` | Offline anomaly scan (thresholds at the top) |
| `tools/build_geo.py` | Builds the region map file from Eurostat NUTS2 |
| `parser/tables/` | Per-dataset overrides, only where a table differs from the base case |

### Output columns

| Column | Example | Notes |
|---|---|---|
| sector | crops / livestock | from folder |
| year | 2024 | from folder |
| dataset | cereals_for_grain | from folder |
| table | 2a | from the title |
| category | Wheat | top English header |
| item | Durum | lower header levels (= category when there is only one) |
| detail | wine | extra split, e.g. grape production by use; empty otherwise |
| level | country / region / unit | |
| region | Evros | canonical English name |
| region_code | GR11-03 | `GR`, NUTS2 `GR11`, unit = NUTS2 + ELSTAT code. **Join on this.** |
| metric | area / production / holdings / animals | holdings, animals = livestock |
| value | 613485 | "–" (no data) rows are left out |
| unit | stremmas / tons / holdings / heads | 1 stremma = 0.1 ha |

### When a new file fails

1. `python -m parser inspect <file>` to see what was detected.
2. Unknown region spelling → add it to `ALIASES` in `parser/regions.py`.
3. Layout quirk → add a `BaseTable` subclass in `parser/tables/` overriding only that hook
   (`adjust_column`, `skip_column`, `item_checks`, `table_id`, ...) and register it in
   `parser/tables/__init__.py`.
