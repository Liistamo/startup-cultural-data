# fetch_lau_boundaries.py
# Fetches Eurostat/GISCO LAU 2024 (GeoJSON, EPSG:4326), filters your cities,
# builds the Ruhr union (Dortmund+Bochum+Gelsenkirchen) with tolerant matching,
# and retrieves Eurométropole de Strasbourg directly from the French EPCI layer (SIREN 246700488).

import sys, os, re, unicodedata, datetime, pathlib
import geopandas as gpd
import pandas as pd

# --- Source URL: Eurostat / GISCO LAU 2024, 1:1M, WGS84 ---
LAU_GEOJSON = "https://gisco-services.ec.europa.eu/distribution/v2/lau/geojson/LAU_RG_01M_2024_4326.geojson"

# --- Output directories ---
OUT_LAU = pathlib.Path("geojson/lau")          # cache + raw sources (LAU/EPCI)
OUT_LAU.mkdir(parents=True, exist_ok=True)

OUT_BOUND = pathlib.Path("geojson/boundaries") # final per-city / metropolitan files
OUT_BOUND.mkdir(parents=True, exist_ok=True)

# --- Local cache file for LAU ---
LAU_CACHE = OUT_LAU / "LAU_RG_01M_2024_4326.geojson"

# --- EPCI (France) source: local cache or URL via environment variable ---
EPCI_DEFAULT_LOCAL = OUT_LAU / "EPCI_FR_2024.geojson"
EPCI_ENV_VAR_NAME  = "EPCI_FR_2024_URL"  # environment variable name
EPCI_URL_FALLBACK  = "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2024/geojson/epci-100m.geojson"

# --- Your cities: display name -> (LAU_NAME in source, country code CNTR_CODE) ---
# Note: Rome is "Roma" in LAU.
# Strasbourg is omitted here because we fetch it from EPCI ("Eurométropole de Strasbourg").
CITIES = {
    "Stockholm":   ("Stockholm",  "SE"),
    "Madrid":      ("Madrid",     "ES"),
    "Sevilla":     ("Sevilla",    "ES"),
    "Rome":        ("Roma",       "IT"),
    "Gdańsk":      ("Gdańsk",     "PL"),
    "Trenčín":     ("Trenčín",    "SK"),
}

# --- Ruhr aggregate built directly from German LAU ---
RUHR_CITIES = [
    ("Dortmund",      "DE"),
    ("Bochum",        "DE"),
    ("Gelsenkirchen", "DE"),
]
RUHR_DISPLAY = "Dortmund Bochum Gelsenkirchen"

# --- EPCI: Eurométropole de Strasbourg ---
EMS_SIREN = "246700488"
EMS_LABEL = "Eurométropole de Strasbourg"

def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def load_lau():
    """Load LAU 2024 from local cache if present, else from GISCO, and save to cache."""
    if LAU_CACHE.exists():
        print(f"📂 Using local cache: {LAU_CACHE}")
        gdf = gpd.read_file(LAU_CACHE)
    else:
        print("⬇️  Downloading LAU 2024 GeoJSON from Eurostat/GISCO …")
        gdf = gpd.read_file(LAU_GEOJSON)
        gdf.to_file(LAU_CACHE, driver="GeoJSON")
        print(f"💾 Saved local copy: {LAU_CACHE}")

    # Ensure WGS84
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf

def _norm(s: str) -> str:
    """Loosely normalize a string for robust comparisons (accents/ligatures/case)."""
    if s is None:
        return ""
    s = s.replace("œ", "oe").replace("Œ", "Oe")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.casefold().strip()

def select_city_lau(gdf: gpd.GeoDataFrame, display: str, lau_name: str, cntr: str) -> gpd.GeoDataFrame:
    """
    Extract a municipality from LAU by tolerant name + country code, then dissolve
    into a single geometry if multiple parts exist.
    Matching tolerance:
      1) exact (casefold)
      2) prefix (handles 'Dortmund, Stadt', etc.)
      3) contains with boundary (e.g. 'Dortmund' in 'Dortmund, Stadt')
    """
    cand = gdf[gdf.get("CNTR_CODE") == cntr].copy()
    if cand.empty:
        print(f"❌ Country {cntr} not found in LAU 2024 for {display}.")
        return gpd.GeoDataFrame(columns=["city","geometry"], geometry="geometry", crs=gdf.crs)

    # 1) exact (casefold)
    sel = cand[cand["LAU_NAME"].str.casefold() == lau_name.casefold()]
    # 2) prefix (handles trailing qualifiers like ', Stadt')
    if sel.empty:
        sel = cand[cand["LAU_NAME"].str.startswith(lau_name, na=False)]
    # 3) contains with anchored prefix (name at start, then comma or end)
    if sel.empty:
        sel = cand[cand["LAU_NAME"].str.contains(rf"^{re.escape(lau_name)}(,|$)", case=False, na=False)]

    if sel.empty:
        print(f"❌ Could not find {display} ({lau_name}/{cntr}) in LAU 2024.")
        return gpd.GeoDataFrame(columns=["city","geometry"], geometry="geometry", crs=gdf.crs)

    sel = sel.dissolve()
    sel["city"] = display
    return sel[["city","geometry"]]

def build_ruhr_from_lau(lau: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Build the union of Dortmund + Bochum + Gelsenkirchen with tolerant matching.
    Uses the same (exact/prefix/anchored-contains) logic as select_city_lau.
    """
    parts = []
    lau_de = lau[lau.get("CNTR_CODE") == "DE"].copy()
    if lau_de.empty:
        print("❌ No German LAU units found in the dataset.")
        return gpd.GeoDataFrame(columns=["city","geometry"], geometry="geometry", crs=lau.crs)

    for name, cntr in RUHR_CITIES:
        # exact (casefold)
        sel = lau_de[lau_de["LAU_NAME"].str.casefold() == name.casefold()]
        # prefix (”, Stadt” and similar)
        if sel.empty:
            sel = lau_de[lau_de["LAU_NAME"].str.startswith(name, na=False)]
        # anchored contains
        if sel.empty:
            sel = lau_de[lau_de["LAU_NAME"].str.contains(rf"^{re.escape(name)}(,|$)", case=False, na=False)]

        if sel.empty:
            print(f"❌ Could not find {name} in German LAU.")
        else:
            parts.append(sel)

    if not parts:
        return gpd.GeoDataFrame(columns=["city","geometry"], geometry="geometry", crs=lau.crs)

    merged = pd.concat(parts, ignore_index=True)
    ruhr_union = merged.dissolve()
    ruhr_union["city"] = RUHR_DISPLAY
    return ruhr_union[["city","geometry"]]

def load_epci_fr():
    """
    Load French intercommunal boundaries (EPCI) either from a local cache file
    or from a URL provided via the EPCI_FR_2024_URL environment variable.
    Falls back to a public Etalab URL if no env var and no local file.
    """
    if EPCI_DEFAULT_LOCAL.exists():
        print(f"📂 Using local EPCI file: {EPCI_DEFAULT_LOCAL}")
        source = EPCI_DEFAULT_LOCAL
    else:
        env_url = os.environ.get(EPCI_ENV_VAR_NAME, "").strip()
        source = env_url or EPCI_URL_FALLBACK
        if not source:
            raise RuntimeError(
                "No EPCI source found. Place a file at "
                f"{EPCI_DEFAULT_LOCAL} or set {EPCI_ENV_VAR_NAME} to a URL."
            )
        print(f"⬇️  Reading EPCI from URL: {source}")

    gdf = gpd.read_file(source)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf

def _pick_col(gdf: gpd.GeoDataFrame, candidates):
    """Return the first existing column name from a list of candidate names."""
    for c in candidates:
        if c in gdf.columns:
            return c
    return None

def build_epci_by_siren(epci_gdf: gpd.GeoDataFrame, siren: str, label: str) -> gpd.GeoDataFrame:
    """
    Select an EPCI geometry by SIREN code and dissolve to one geometry.
    Falls back to a name-based search if the code column is not found or does not match.
    """
    # Include 'code' and 'epci' as possible field names
    siren_col = _pick_col(epci_gdf, ["SIREN", "SIREN_EPCI", "CODE_EPCI", "EPCI", "siren", "code", "epci"])
    if not siren_col:
        # Helpful debug: show which columns actually exist
        print("Columns in EPCI:", list(epci_gdf.columns))
        raise RuntimeError("No SIREN column found in EPCI layer.")

    sel = epci_gdf[epci_gdf[siren_col].astype(str) == str(siren)].copy()

    # Fallback: if the code still doesn't match, try a name column (Etalab: 'nom')
    if sel.empty:
        name_col = _pick_col(epci_gdf, ["LIBEPCI", "LIB_NAME", "NOM_EPCI", "NOM", "nom", "name"])
        if name_col is not None:
            cand = epci_gdf[epci_gdf[name_col].str.contains("Eurom", case=False, na=False)]
            if not cand.empty:
                sel = cand.copy()

    if sel.empty:
        print(f"❌ Could not find EPCI with SIREN {siren}.")
        return gpd.GeoDataFrame(columns=["city","geometry"], geometry="geometry", crs=epci_gdf.crs)

    dissolved = sel.dissolve()
    dissolved["city"] = label
    return dissolved[["city", "geometry"]]

def main():
    stamp = now_stamp()
    lau = load_lau()

    outputs = []

    # 1) One file per city in CITIES (NOTE: Strasbourg is handled via EPCI and is therefore omitted here)
    for display, (lau_name, cntr) in CITIES.items():
        sel = select_city_lau(lau, display, lau_name, cntr)
        if sel.empty:
            continue
        out_path = OUT_BOUND / f"{display.lower().replace(' ','_')}_boundary_{stamp}.geojson"
        sel.to_file(out_path, driver="GeoJSON")
        print(f"📝 Saved: {out_path}")
        outputs.append(sel)

    # 2) Ruhr aggregate (Dortmund+Bochum+Gelsenkirchen) from LAU with tolerant matching
    ruhr = build_ruhr_from_lau(lau)
    if not ruhr.empty:
        ruhr_path = OUT_BOUND / f"{RUHR_DISPLAY.lower().replace(' ','_')}_boundary_{stamp}.geojson"
        ruhr.to_file(ruhr_path, driver="GeoJSON")
        print(f"📝 Saved: {ruhr_path}")
        outputs.append(ruhr)

    # 3) Eurométropole de Strasbourg via EPCI (SIREN 246700488)
    try:
        epci = load_epci_fr()
        ems = build_epci_by_siren(epci, siren=EMS_SIREN, label=EMS_LABEL)
        if not ems.empty:
            ems_path = OUT_BOUND / f"eurometropole_strasbourg_boundary_{stamp}.geojson"
            ems.to_file(ems_path, driver="GeoJSON")
            print(f"📝 Saved: {ems_path}")
            outputs.append(ems)
    except Exception as e:
        print("⚠️ EPCI read failed:", e)

    # 4) Merged file (all boundaries in one FeatureCollection) for convenience
    if outputs:
        all_boundaries = pd.concat(outputs, ignore_index=True)
        merged_out = OUT_BOUND / f"city_boundaries_{stamp}.geojson"
        gpd.GeoDataFrame(all_boundaries, geometry="geometry", crs=4326).to_file(merged_out, driver="GeoJSON")
        print(f"✅ Done. Merged file: {merged_out}")
    else:
        print("⚠️ Nothing to save.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ Error:", e)
        sys.exit(1)
