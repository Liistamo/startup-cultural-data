# startup-cultural-data

Art & Cultural Places — LAU/EPCI + Overture Maps → Leaflet Map

**Maintained by:** magnus.liistamo@humangeo.su.se

This repository contains the **Python pipeline** that generates the GeoJSON used by the WordPress theme in **startup-wp-theme**.  
All steps below are written so you can reproduce everything without external docs.

---

## Purpose
This project builds a map of art and cultural places in European cities for:
- https://horizon-startup.eu/ website
- STARTUP (Sustainable Transitions — Horizon Europe project)
- Visual prototypes and reports

---

**TL;DR (Too Long; Didn’t Read)**  
1) Create venv & install deps:
```bash
python3 -m venv venv && source venv/bin/activate && python3 -m pip install -r requirements.txt
```
2) Build boundaries → places → clean GeoJSON:
```bash
python3 01_fetch_lau_boundaries.py
python3 02_build_cultural_places.py
python3 03_csv_to_geojson.py
```
3) Preview locally (optional):
```bash
python3 -m http.server  # open http://localhost:8000/index.html
```
4) **Copy outputs to the WP theme** → follow **MANUAL_SYNC.md**.  
5) In WordPress the map template auto-picks the newest files.

---

## Workflow

### 0) Setup virtual environment (first time only)
```bash
cd path/to/startup-cultural-data
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt

# Next time:
source venv/bin/activate
```

### 1) Fetch official city/metropolitan boundaries
```bash
python3 01_fetch_lau_boundaries.py
```
What it does:
- Downloads or reuses Eurostat GISCO LAU 2024 (municipal boundaries, EPSG:4326).
- Adds Eurométropole de Strasbourg from Etalab EPCI (SIREN 246700488).
- Builds the Ruhr union (Dortmund, Bochum, Gelsenkirchen) from German LAU.
- Writes per-city/metro boundary files to: `geojson/boundaries/`
- Caches sources in: `geojson/lau/`

Optional: EPCI source via environment variable (if no local EPCI file is present)
```bash
export EPCI_FR_2024_URL="https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2024/geojson/epci-50m.geojson"
python3 01_fetch_lau_boundaries.py
```

### 2) Export art & cultural places from Overture Maps → GeoJSON
```bash
python3 02_build_cultural_places.py
```
What it does:
- Runs DuckDB (via Python subprocess).
- Loads Overture Maps Places parquet files from S3.
- Spatially filters places within the selected city/metropolitan boundaries.
- Exports one consolidated GeoJSON of points (for Leaflet) and CSV summaries.

Outputs (written to `geojson/`):
- `cultural_places_YYYY-MM-DD_HH-MM-SS.geojson`
- `city_counts_YYYY-MM-DD_HH-MM-SS.csv`
- `city_category_counts_YYYY-MM-DD_HH-MM-SS.csv`

### 3) Convert curated CSV/TSV to a clean Leaflet-ready GeoJSON (local datasets)
```bash
python3 03_csv_to_geojson.py
```
Input:
- Reads every `*.csv` and `*.tsv` from `./cleaned_data/`.

Core rules:
- `delete == 2` → row is excluded.
- Robust coordinate parsing:
  * Accepts lat/lon in separate columns or as a single `"lat, lon"` value.
  * Supports decimal comma and decimal point.
  * Accepts Unicode minus signs (e.g., U+2212).
- URL normalization:
  * If website has no scheme, `https://` is prefixed.
  * Accepts aliases: `web`, `url`, `link` → `website`.
- Category normalization:
  * Incoming category is normalized to snake_case and compared against a whitelist.
  * If found in whitelist → that exact snake_case is used.
  * If missing → `"Startup"`.
  * Otherwise → `"Startup <original>"` (keeps the original human label).
- Colors:
  * Fixed colors for common categories; deterministic fallback palette for unknowns.

Boundary filter:
- If one or more GeoJSON files exist in `geojson/boundaries/`, points are exported only if **inside** at least one boundary polygon.
- Supports Polygon and MultiPolygon and treats interior rings (holes) correctly.
- Points outside the boundary are skipped and logged with `reason = "outside boundary"`.

Outside-boundary whitelist:
- Some places are deliberately allowed **outside** the boundary by name.
- Case-insensitive and accent-safe matching.
- Edit the set inside `03_csv_to_geojson.py` (`OUTSIDE_NAME_WHITELIST_RAW`), e.g.:
  ```python
  OUTSIDE_NAME_WHITELIST_RAW = {
      "Dychová hudba Trenčianska dvanástka",
      # add more names here…
  }
  ```

Logging of skipped rows:
- Rows missing valid coordinates or rejected by the boundary filter are logged to:
  `geojson/skipped_rows_missing_coords_YYYY-MM-DD_HH-MM-SS.csv`
- Columns include source file, row number, name, raw lat/lon fields, a detected `"lat, lon"` example (if any), and a human-readable reason.

Output:
- Clean, Leaflet-ready FeatureCollection:
  `geojson/clean_cultural_places_YYYY-MM-DD_HH-MM-SS.geojson`

### 4) View the map locally (optional preview)
Start a simple HTTP server from the **project root**:
```bash
python3 -m http.server
```
Open in a browser:
```
http://localhost:8000/index.html
```
Optional: use a different port (e.g. 5000):
```bash
python3 -m http.server 5000
```

---

## Caching & refresh (what gets cached and when to clear it)

**Where caches live**
- `geojson/lau/` — cached source layers:
  - `LAU_RG_01M_2024_4326.geojson` (Eurostat/GISCO LAU)
  - `EPCI_FR_2024.geojson` (optional local cache of French EPCI)
- `geojson/boundaries/` — **outputs** (per-city/merged boundary GeoJSONs). These are inputs to later steps and are **not** cache; they are meant to be committed.

**When caches are reused**
- `01_fetch_lau_boundaries.py` will **reuse** `geojson/lau/LAU_RG_01M_2024_4326.geojson` if it exists (faster, reproducible).
- For EPCI (Strasbourg), the script prefers a local file in `geojson/lau/`. If missing, it uses `EPCI_FR_2024_URL` (if set) or the built-in public fallback.

**How to force a fresh download/rebuild**
```bash
# 1) Force fresh LAU/EPCI sources (next run will re-download/read):
rm -f geojson/lau/LAU_RG_01M_2024_4326.geojson
rm -f geojson/lau/EPCI_FR_2024.geojson

# 2) Rebuild boundaries (new timestamped files in geojson/boundaries/):
python3 01_fetch_lau_boundaries.py
```

**Pinning the EPCI source explicitly**
```bash
export EPCI_FR_2024_URL="https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2024/geojson/epci-50m.geojson"
python3 01_fetch_lau_boundaries.py
```

> Tip: If you want maximum reproducibility across machines, **commit** the contents of `geojson/lau/` so everyone reads the exact same inputs. If you prefer smaller repos, keep them uncommitted and rely on the URL + version notes below.

---

## “Latest file wins” (how the theme finds data)

- Both the standalone `index.html` and the WordPress template select the **newest** file by filename/timestamp:
  - Points: `geojson/clean_cultural_places_YYYY-MM-DD_HH-MM-SS.geojson`
  - Boundaries: `geojson/boundaries/<city>_boundary_YYYY-MM-DD_HH-MM-SS.geojson`
- To update the site, you only need to add new files with a **later** timestamp; you don’t have to delete older files.
- In WordPress, the template scans `assets/geojson/` and `assets/geojson/boundaries/` and picks the newest automatically.

---

## Determinism & versions

- **CRS**: All geometries are processed/stored in **EPSG:4326** (WGS84). The scripts enforce this.
- **Timestamps**: Output filenames use local time (`YYYY-MM-DD_HH-MM-SS`). If you want identical names across machines, use a single machine for builds or change to UTC in your environment (optional).
- **Dependencies**: Keep `requirements.txt` pinned. If DuckDB behavior changes across versions, note the DuckDB version you used in the README (and consider committing the DuckDB binary if you want strict reproducibility).

---

## Clearing & regenerating outputs (safe sequence)

If you need a clean rebuild without losing curated inputs:

```bash
# Keep curated CSV/TSV in cleaned_data/, remove generated artifacts:
rm -f geojson/clean_cultural_places_*.geojson
rm -f geojson/skipped_rows_missing_coords_*.csv
rm -f geojson/boundaries/*_boundary_*.geojson
rm -f geojson/boundaries/city_boundaries_*.geojson

# (Optional) also clear cached sources for a fully fresh run:
rm -f geojson/lau/LAU_RG_01M_2024_4326.geojson
rm -f geojson/lau/EPCI_FR_2024.geojson

# Re-run:
python3 01_fetch_lau_boundaries.py
python3 02_build_cultural_places.py
python3 03_csv_to_geojson.py
```

---

## Common gotchas (quick checks)

- **No data on map**  
  Ensure there is at least one `clean_cultural_places_*.geojson` in `geojson/` (or in the WP theme’s `assets/geojson/`), and that the file is valid JSON.

- **Points disappear after enabling boundary filter**  
  Check that `geojson/boundaries/` exists and contains city polygons that match your data’s city names; points outside all polygons will be logged to `geojson/skipped_rows_missing_coords_*.csv` with `reason="outside boundary"`.

- **Website links show “No website”**  
  The client expects either a valid URL or the string `No website`. The CSV parser auto-prefixes `https://` if missing.

- **Large files**  
  Consider Git LFS for big `.geojson` files if repo size becomes an issue.

---

## Project structure (reference)
Make sure your structure is:

```
project-root/
  index.html
  geojson/
    clean_cultural_places_YYYY-MM-DD_HH-MM-SS.geojson
    boundaries/
      <city>_boundary_YYYY-MM-DD_HH-MM-SS.geojson
  images/
    startup-logo-square.png  # optional; otherwise only the text link is shown
```

### Current cities / regions
Defined in `01_fetch_lau_boundaries.py`:
- Stockholm
- Madrid
- Sevilla
- Rome (Roma in LAU)
- Gdańsk
- Eurométropole de Strasbourg (from EPCI)
- Trenčín
- Ruhr area (union of Dortmund, Bochum, Gelsenkirchen)

### Folder structure (detailed)
```
cultural_data/
  01_fetch_lau_boundaries.py      # Fetch & build boundaries (Eurostat/Etalab)
  02_build_cultural_places.py     # Export filtered cultural places (Overture)
  03_csv_to_geojson.py            # Convert curated CSV/TSV → clean GeoJSON (local data)
  cleaned_data/                   # Curated CSV/TSV inputs
  duckdb                          # DuckDB binary
  geojson/
    lau/                          # Cache: Eurostat LAU + Etalab EPCI sources
    boundaries/                   # Per-city & merged boundary GeoJSONs
    clean_cultural_places_*.geojson
    skipped_rows_missing_coords_*.csv
  images/                         # Static images (e.g., startup-logo-square.png)
  index.html                      # Leaflet map UI (filters, export)
  venv/                           # Python virtual environment
  README.md                       # this file
```

### DuckDB setup
1) Download DuckDB binary: https://duckdb.org/releases/
2) (Optional) Run DuckDB manually:
   ```bash
   cd /path/to/cultural_data
   ./duckdb --progress
   ```

---

## Manual sync to WordPress theme
To copy the generated outputs into the WordPress theme (**startup-wp-theme**), see the separate guide: **MANUAL_SYNC.md**.

---

## TL;DR
- Fetch boundaries:       `python3 01_fetch_lau_boundaries.py`
- Export cultural places: `python3 02_build_cultural_places.py`
- Convert local CSV/TSV:  `python3 03_csv_to_geojson.py`
- Preview locally:        `python3 -m http.server`
- **Copy outputs to theme:** follow **MANUAL_SYNC.md** (separate file)
- In WordPress, the template picks the newest files automatically.
