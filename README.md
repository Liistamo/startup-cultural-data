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

## Documentation index
- **DATA-SOURCES-AND-METHODS.txt** – detailed sources, methods & full references (EU report appendix)  
- **LICENSE** – project license (Apache-2.0)  
- **LICENSE-DATA.txt** – license for generated datasets (CC BY 4.0)  
- **NOTICE** – third-party attribution notices  
- **MANUAL_SYNC.md** – how to copy generated data into the WordPress theme  
- **geojson/lau/README.txt** – notes about cached official source layers (LAU/EPCI)

---

## TL;DR
1. Create virtual environment & install dependencies:
   ```bash
   python3 -m venv venv && source venv/bin/activate && python3 -m pip install -r requirements.txt
   ```
2. Build data:
   ```bash
   python3 01_fetch_lau_boundaries.py
   python3 02_build_cultural_places.py
   python3 03_csv_to_geojson.py
   ```
3. Preview locally:
   ```bash
   python3 -m http.server  # open http://localhost:8000/index.html
   ```
4. Copy outputs to the WordPress theme → see **MANUAL_SYNC.md**.  
   The theme automatically picks the newest files.

---

## Workflow summary

### 1. Fetch official city/metropolitan boundaries
- Downloads Eurostat GISCO LAU 2024 (municipal boundaries, EPSG:4326)
- Adds Eurométropole de Strasbourg from Etalab EPCI (SIREN 246700488)
- Builds Ruhr area (Dortmund, Bochum, Gelsenkirchen)
- Outputs per-city boundary files → `geojson/boundaries/`

### 2. Export art & cultural places from Overture Maps
- Runs DuckDB (Spatial + HTTPFS extensions)
- Loads Overture *Places* Parquet data
- Filters by boundary and exports consolidated GeoJSON and CSV summaries

### 3. Convert curated CSV/TSV → clean Leaflet-ready GeoJSON
- Reads all local curated datasets from `cleaned_data/`
- Cleans coordinates, normalizes categories, applies boundary filters
- Logs skipped rows
- Outputs `geojson/clean_cultural_places_YYYY-MM-DD_HH-MM-SS.geojson`

### 4. Preview map locally
```bash
python3 -m http.server
```
Open: [http://localhost:8000/index.html](http://localhost:8000/index.html)

---

## Caching & reproducibility
- Cached official layers in `geojson/lau/`  
- Output boundaries in `geojson/boundaries/`  
- Scripts reuse cached sources if present  
- All geometries stored in EPSG:4326  
- Output filenames timestamped (`YYYY-MM-DD_HH-MM-SS`)

---

## “Latest file wins”
Both the standalone index and the WordPress theme select the newest files automatically:
```
geojson/clean_cultural_places_*.geojson
geojson/boundaries/*_boundary_*.geojson
```

---

## Common gotchas
- **No data on map:** ensure a `clean_cultural_places_*.geojson` exists.  
- **Points missing:** check that boundary polygons match city names.  
- **Invalid websites:** the parser auto-prefixes `https://`.  
- **Large GeoJSON files:** consider Git LFS.

---

## Licensing
- **Code:** Apache License 2.0 (`LICENSE`)  
- **Data:** Creative Commons Attribution 4.0 International (`LICENSE-DATA.txt`)  
- See `NOTICE` for third-party attributions.

---

## Attribution & citation
If you use this work, please cite:

> **STARTUP (2025)**  
> *startup-cultural-data: Art & Cultural Places — LAU/EPCI + Overture Maps → Leaflet Map* [Data set].  
> *In Sustainable Transitions. Action Research and Training in Urban Perspective (STARTUP).*  
> [https://github.com/Liistamo/cultural_data](https://github.com/Liistamo/cultural_data)

Also acknowledge third-party data/software per `NOTICE` and `DATA-SOURCES-AND-METHODS.txt`.

---

## EU funding acknowledgement
This project has received funding from the **European Union’s Horizon Europe** research and innovation programme under **Grant Agreement No 101178523**.

Views and opinions expressed are those of the author(s) only and do not necessarily reflect those of the European Union or the granting authority.  
Neither the European Union nor the granting authority can be held responsible for them.

---

**Contact:** magnus.liistamo@humangeo.su.se  
Department of Human Geography, Stockholm University  
