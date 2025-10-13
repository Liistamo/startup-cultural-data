README — geojson/lau/ (source cache)
====================================

Purpose
-------
This folder stores *source caches* downloaded from official providers. The
files are large and can always be re-downloaded, so they are usually
**excluded from Git** via .gitignore.

What may appear here
--------------------
- LAU_RG_01M_2024_4326.geojson      (Eurostat / GISCO — LAU 2024, EPSG:4326)
- EPCI_FR_2024.geojson              (Etalab — French EPCI polygons; optional)

How these files are created
---------------------------
Run in the repository root:
  python3 01_fetch_lau_boundaries.py

Optional (choose a specific EPCI source URL if you don’t have a local copy):
  export EPCI_FR_2024_URL="https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2024/geojson/epci-100m.geojson"
  python3 01_fetch_lau_boundaries.py

Why this folder is not versioned
--------------------------------
- Files can exceed GitHub’s 100 MB limit.
- They are reproducible: the script above will re-download them when missing.
- Keeping them out of Git keeps the repository lightweight.

Do not edit by hand
-------------------
These files may be overwritten by the pipeline. If you need persistent
edits, do that in a separate processing step and write results to
geojson/boundaries/ instead.

Sources / references
--------------------
- Eurostat GISCO LAU 2024 (1:1M, WGS84): https://gisco-services.ec.europa.eu/distribution/v2/lau/
- Etalab (French EPCI 2024): https://etalab.gouv.fr/  and
  dataset access via data.gouv.fr: https://www.data.gouv.fr/
  Example GeoJSON (100m): https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2024/geojson/epci-100m.geojson

Notes
-----
- Coordinate reference system expected by the pipeline: EPSG:4326.
- If the cache is deleted, the next pipeline run will restore it automatically.
