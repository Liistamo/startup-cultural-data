#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert all CSV/TSV files in ./cleaned_data/ into ONE GeoJSON:
geojson/clean_cultural_places_YYYY-MM-DD_HH-MM-SS.geojson

Supported/mapped headers (case-insensitive, order does not matter):
- name
- website (also web/url/link)
- city (also stad)
- comments
- category (also "Suggested search term, if any")
- lat (also latitude/y)
- lon (also longitude/lng/x)
- delete (also remove/hide)

Rules:
- delete == 2 => row is excluded
- lat/lon: supports comma or dot decimals + Unicode minus signs
- lat+lon can be merged into ONE cell, e.g. "51.53, 7.44" → automatically split
- Category normalization:
    * Normalize incoming value to snake_case and compare against a whitelist.
    * If present in whitelist → return that exact snake_case.
    * If missing altogether → "Startup".
    * Otherwise → "Startup " + original.
- Output follows the same structure that the existing map expects.
- comments are included in properties if present.

NEW:
- Logging of rows skipped due to empty/invalid coordinates into
  geojson/skipped_rows_missing_coords_YYYY-MM-DD_HH-MM-SS.csv

NEW (BOUNDARY FILTER):
- If one or more .geojson files exist in geojson/boundaries/, only points INSIDE at least
  one polygon are exported (supports Polygon/MultiPolygon with holes). Rows outside the
  boundary are logged to the same skipped-CSV with reason="outside boundary".

NEW (OUTSIDE-BOUNDARY WHITELIST):
- Some places can be allowed even if they are outside any boundary via a name whitelist
  (case-insensitive and accent-safe).
"""

from __future__ import annotations
import csv, json, sys, zlib, re, unicodedata
from pathlib import Path
from datetime import datetime

# --- Paths ---
INPUT_DIR  = Path("cleaned_data")
OUTPUT_DIR = Path("geojson")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Name whitelist for places allowed outside any boundary ---
def _norm_name(s: str) -> str:
    # Apply NFKC, trim, strip surrounding quotes, then casefold for robust matching
    s = unicodedata.normalize("NFKC", (s or "").strip())
    s = s.strip("'").strip('"')
    return s.casefold()

OUTSIDE_NAME_WHITELIST_RAW = {
    "Dychová hudba Trenčianska dvanástka",
}
OUTSIDE_NAME_WHITELIST = {_norm_name(n) for n in OUTSIDE_NAME_WHITELIST_RAW}

def is_name_whitelisted(name: str) -> bool:
    return _norm_name(name) in OUTSIDE_NAME_WHITELIST

# --- Category colors (matches the existing front-end style) ---
FIXED_CATEGORY_COLORS = {
    "art_museum": "#2ca02c",
    "art_gallery": "#1f77b4",
    "contemporary_art_museum": "#ff7f0e",
    "modern_art_museum": "#d62728",
    "art_space_rental": "#9467bd",
    "art_tours": "#e377c2",
    "community_center": "#17becf",
    "cultural_center": "#7b4173",
    "library": "#8c6d31",
    "theaters_and_performance_venues": "#843c39",
    "theatre": "#d62728",
    "museum": "#637939",
    "music_venue": "#ff7f0e",
    "cinema": "#bcbd22",
    "arts_and_entertainment": "#9467bd",
    "attractions_and_activities": "#1f77b4",
    "opera_and_ballet": "#e377c2",
}

# Deterministic fallback palette for categories without fixed colors.
FALLBACK_PALETTE = [
    "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
    "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf",
]

def color_for(category: str | None) -> str:
    key = (category or "").strip().lower()
    if not key:
        return "#999999"
    if key in FIXED_CATEGORY_COLORS:
        return FIXED_CATEGORY_COLORS[key]
    # Stable hashing into the fallback palette so the same label always gets the same color.
    return FALLBACK_PALETTE[zlib.crc32(key.encode("utf-8")) % len(FALLBACK_PALETTE)]

# --- Numeric normalization helpers ---
# Common Unicode minus/dash characters that should be treated as ASCII '-'
MINUS_CHARS = "\u2212\u2013\u2014\u2012\uFE63\uFF0D"

def _normalize_number_str(s: str) -> str:
    # Normalize decimal comma to dot, unify minus signs, strip NBSP → plain space
    s = s.strip().replace(",", ".")
    for ch in MINUS_CHARS:
        s = s.replace(ch, "-")
    return s.replace("\u00a0", " ")

def to_float(val) -> float | None:
    # Convert various string formats into float, returning None for N/A-like tokens.
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    if s.lower().replace(" ", "") in ("n/a", "na", "nan", "-", "–"):
        return None
    s = _normalize_number_str(s)
    try:
        return float(s)
    except ValueError:
        return None

# Match a pair like "52.5, 13.4" or "52,5;13,4" etc. (various delimiters)
_PAIR_RE = re.compile(
    r'^\s*'
    r'([-\u2212]?\d+(?:[.,]\d+)?)'
    r'[\s,;|/]+'
    r'([-\u2212]?\d+(?:[.,]\d+)?)'
    r'\s*$'
)

def parse_latlon_pair(val) -> tuple[float | None, float | None]:
    # Try to parse a single field containing both lat and lon.
    if val is None:
        return (None, None)
    s = str(val).strip().replace("\u00a0", " ")
    if not s or s.lower() in ("n/a", "na", "-", "–"):
        return (None, None)
    m = _PAIR_RE.match(s)
    if not m:
        return (None, None)
    a = _normalize_number_str(m.group(1))
    b = _normalize_number_str(m.group(2))
    try:
        return (float(a), float(b))
    except ValueError:
        return (None, None)

def detect_delimiter(sample: str) -> str:
    """
    Heuristically detect delimiter from the first line while honoring quotes.
    Supports common candidates: comma, semicolon, tab, pipe, colon.
    """
    sample = (sample or "").lstrip("\ufeff")
    first = sample.splitlines()[0] if sample else ""
    cand = [",",";","\t","|",":"]
    cnt = {c:0 for c in cand}
    inq = False
    i = 0
    while i < len(first):
        ch = first[i]
        if ch == '"':
            if i+1 < len(first) and first[i+1] == '"':
                i += 2; continue
            inq = not inq
        else:
            if not inq and ch in cnt:
                cnt[ch] += 1
        i += 1
    best, bestn = ",", -1
    for c,n in cnt.items():
        if n > bestn: best, bestn = c, n
    return best

# Flexible header aliases to absorb variations from spreadsheets/exports.
ALIASES = {
    "latitude": "lat", "y": "lat",
    "longitude": "lon", "lng": "lon", "x": "lon",
    "web": "website", "url": "website", "link": "website",
    "stad": "city", "remove": "delete", "hide": "delete",
    "suggested search term, if any": "category",
}

def norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    return ALIASES.get(h, h)

def read_csv_file(path: Path) -> list[dict]:
    """
    Lightweight CSV/TSV reader:
    - detects delimiter
    - applies header normalization
    - pads/truncates rows to header width
    - returns list of dicts
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    delim = detect_delimiter(text)
    rows = list(csv.reader(text.splitlines(), delimiter=delim))
    if not rows:
        return []
    header = [norm_header(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        elif len(r) > len(header):
            r = r[:len(header)]
        out.append({ header[i]: r[i] for i in range(len(header)) })
    return out

def find_any_latlon_pair_string(rec: dict) -> str:
    # Scan all values and return the first string that looks like a "lat, lon" pair.
    for v in rec.values():
        s = str(v).strip()
        if _PAIR_RE.match(s):
            return s
    return ""

def try_extract_lat_lon(rec: dict) -> tuple[float | None, float | None, str | None]:
    """
    Attempt to extract lat/lon from dedicated fields, merged pair fields,
    or any field that looks like a coordinate pair. Returns (lat, lon, reason_if_failed).
    """
    raw_lat = rec.get("lat")
    raw_lon = rec.get("lon")

    lat = to_float(raw_lat)
    lon = to_float(raw_lon)
    if lat is not None and lon is not None:
        return lat, lon, None

    la, lo = parse_latlon_pair(raw_lat)
    if la is not None and lo is not None:
        return la, lo, None

    la, lo = parse_latlon_pair(raw_lon)
    if la is not None and lo is not None:
        return la, lo, None

    for k in ("latitude", "longitude", "coords", "coordinate", "position"):
        if k in rec and rec[k]:
            la, lo = parse_latlon_pair(rec[k])
            if la is not None and lo is not None:
                return la, lo, None

    for v in rec.values():
        la, lo = parse_latlon_pair(v)
        if la is not None and lo is not None:
            return la, lo, None

    # Diagnostics: helps the skipped-rows log explain what went wrong.
    lat_present = (raw_lat is not None and str(raw_lat).strip() != "")
    lon_present = (raw_lon is not None and str(raw_lon).strip() != "")
    pair_example = find_any_latlon_pair_string(rec)

    if not lat_present and not lon_present and not pair_example:
        return None, None, "no coordinate fields found"
    if (lat_present or lon_present) and not pair_example:
        return None, None, "could not parse numbers in lat/lon fields"
    if pair_example:
        return None, None, f"failed to parse coordinate pair: '{pair_example}'"
    return None, None, "unknown coordinate issue"

# --- URL normalization ---
_URL_RE = re.compile(r'^[a-z]+://', re.I)
def normalize_website(val: str | None) -> str | None:
    """
    Normalize website URLs:
    - return None for empty/N/A-like tokens
    - add https:// if scheme is missing
    """
    s = (val or "").strip()
    if not s or s.lower() in ("n/a", "na", "-", "–"):
        return None
    if not _URL_RE.match(s):
        s = "https://" + s.lstrip()
    return s

# -------------------------
# CATEGORY NORMALIZATION
# -------------------------

def _strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c))

def to_snake(s: str) -> str:
    # Lowercase, replace non-word sequences with underscores, collapse repeats, trim edges.
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def pretty_label(raw: str) -> str:
    # Turn machine labels into human-facing titles (not used in the exporter, kept for reference).
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"[_\+\&]", " ", s)
    s = re.sub(r"[‐-‒–—-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.title()

# Whitelist of accepted snake_case categories. Others get prefixed with "Startup ".
WHITELIST = {
    'art_museum','art_gallery','contemporary_art_museum','modern_art_museum',
    'art_space_rental','art_tours','community_center','cultural_center',
    'library','theaters_and_performance_venues','theatre','museum',
    'music_venue','cinema','arts_and_entertainment','attractions_and_activities',
    'arcade','auditorium','exhibition_and_trade_center','glass_blowing','makerspace',
    'opera_and_ballet','paint_and_sip','performing_arts','salsa_club','studio_taping',
    'virtual_reality_center','drive_in_theater','outdoor_movies','festival','fair',
    'film_festivals_and_organizations','general_festivals','music_festivals_and_organizations',
    'trade_fair','social_club','architecture','street_art',
    'asian_art_museum','cartooning_museum','childrens_museum','costume_museum',
    'decorative_arts_museum','design_museum','photography_museum','textile_museum',
    'history_museum','civilization_museum','community_museum','military_museum',
    'national_museum','science_museum','computer_museum','state_museum','aviation_museum',
    'sports_museum','dance_school','architecture_schools','art_school',
    'drama_school','music_school','photography_classes','arts_and_crafts','art_supply_store',
    'atelier','craft_shop','framing_store','handicraft_shop','paint_your_own_pottery',
    'bookstore','academic_bookstore','comic_books_store','music_and_dvd_store',
    'newspaper_and_magazines_store','video_game_store','vinyl_record_store','fashion',
    'designer_clothing','custom_t_shirt_store',
    'photography_store_and_services','urban_farm','audio_visual_production_and_design',
    'community_services_non_profits','architectural_tours',
    'print_media','media_critic','movie_critic','music_critic','video_game_critic','media_agency',
    'radio_station','television_station','animation_studio','book_magazine_distribution',
    'broadcasting_media_production','game_publisher','movie_television_studio','music_production',
    'art_restoration','theatrical_productions','dj_service','musician','silent_disco',
    'venue_and_event_space','videographer','photographer','architect','architectural_designer',
    'art_restoration_service','bookbinding','calligraphy','commissioned_artist','community_gardens',
    'goldsmith','graphic_designer','record_label','recording_and_rehearsal_studio',
    'video_film_production','cabaret','choir','circus','country_dance_hall','dance_club',
    'jazz_and_blues','marching_band','musical_band_orchestras_and_symphonies','circus_school',
    'mass_media','landscaping','landscape_architect','blacksmiths','community_book_boxes',
    'screen_printing_t_shirt_printing','orchard'
}

def normalize_category(raw_cat: str | None) -> str:
    original = (raw_cat or "").strip()
    if not original:
        return "Startup"
    snake = to_snake(original)
    if snake in WHITELIST:
        return snake
    return f"Startup {original}"

# -------------------------
# --- Boundary filter (reads GeoJSON in geojson/boundaries) ---
BOUNDARY_DIR = Path("geojson") / "boundaries"

def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """
    Ray-casting algorithm in a linear ring (lon,lat). True if inside the ring.
    Assumes ring is closed or treats it as such; requires at least 3 vertices.
    """
    inside = False
    n = len(ring)
    if n < 3:
        return False
    x, y = lon, lat
    x1, y1 = ring[0]
    for i in range(1, n + 1):
        x2, y2 = ring[i % n]
        if ((y1 > y) != (y2 > y)):
            xinters = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1
            if xinters > x:
                inside = not inside
        x1, y1 = x2, y2
    return inside

def _point_in_polygon(lon: float, lat: float, coords: list[list[list[float]]]) -> bool:
    """
    Polygon with holes support:
    - return True if inside outer ring and NOT inside any hole ring.
    """
    if not coords:
        return False
    outer = coords[0]
    if not _point_in_ring(lon, lat, outer):
        return False
    for hole in coords[1:]:
        if _point_in_ring(lon, lat, hole):
            return False
    return True

def _collect_polygons_from_geometry(geom: dict) -> list[list[list[list[float]]]]:
    """
    Normalize GeoJSON geometry → list of polygons in ring form:
    [ [ [ [x,y], ... ] outer, [hole], [hole]... ],  ... ]
    """
    gtype = (geom or {}).get("type")
    coords = (geom or {}).get("coordinates", [])
    polys = []
    if gtype == "Polygon":
        polys.append(coords)
    elif gtype == "MultiPolygon":
        polys.extend(coords)
    return polys

def _load_boundary_polygons() -> list[list[list[list[float]]]]:
    """
    Load all .geojson files from BOUNDARY_DIR and collect all polygons
    from FeatureCollections, Features, or bare Geometry objects.
    """
    polygons = []
    if not BOUNDARY_DIR.exists():
        return polygons
    for p in sorted(BOUNDARY_DIR.glob("*.geojson")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        dtype = data.get("type")
        if dtype == "FeatureCollection":
            for feat in data.get("features", []):
                geom = (feat or {}).get("geometry") or {}
                polygons.extend(_collect_polygons_from_geometry(geom))
        elif dtype == "Feature":
            geom = (data.get("geometry") or {})
            polygons.extend(_collect_polygons_from_geometry(geom))
        else:
            polygons.extend(_collect_polygons_from_geometry(data))
    return polygons

def point_inside_any_boundary(lon: float, lat: float, polygons: list) -> bool:
    """
    First test against a bounding box (cheap), then full point-in-polygon (expensive).
    Short-circuits as soon as one polygon contains the point.
    """
    for poly in polygons:
        if not poly or not poly[0]:
            continue
        xs = [pt[0] for pt in poly[0]]
        ys = [pt[1] for pt in poly[0]]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        if lon < minx or lon > maxx or lat < miny or lat > maxy:
            continue
        if _point_in_polygon(lon, lat, poly):
            return True
    return False
# -------------------------

def row_to_feature(rec: dict) -> dict | None:
    """
    Convert one row dict into a GeoJSON Feature (or None if dropped).
    This helper is not used in the main loop (kept for reference/evolution),
    as the main loop inlines similar logic to capture more diagnostics.
    """
    delv = (rec.get("delete") or "").strip()
    if delv == "2" or delv == 2:
        return None

    lat, lon, reason = try_extract_lat_lon(rec)
    if lat is None or lon is None:
        return None

    name     = (rec.get("name") or "").strip()
    category = normalize_category(rec.get("category"))
    website  = normalize_website(rec.get("website"))
    comments = (rec.get("comments") or "").strip()
    city     = (rec.get("city") or "").strip()

    props = {
        "name": name,
        "category": category,
        "city": city,
        "color": color_for(category),
    }
    if website:
        props["website"] = website
    if comments:
        props["comments"] = comments

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }

def main():
    if not INPUT_DIR.exists():
        print(f"❌ {INPUT_DIR} is missing", file=sys.stderr); sys.exit(1)

    # Load all boundary polygons (if any). If none exist: export without spatial filtering.
    boundary_polygons = _load_boundary_polygons()
    use_boundary = len(boundary_polygons) > 0
    if use_boundary:
        print(f"🧭 Boundary filter active ({len(boundary_polygons)} polygons found in {BOUNDARY_DIR}/)")
    else:
        print("ℹ️  No boundary files found; exporting without geographic filter.")


    # Gather all CSV and TSV files. Exit if none found so the caller notices immediately.
    csv_paths = sorted(list(INPUT_DIR.glob("*.csv")) + list(INPUT_DIR.glob("*.tsv")))
    if not csv_paths:
        print(f"❌ No CSV/TSV files found in {INPUT_DIR}/", file=sys.stderr); sys.exit(1)

    features = []
    total = kept = skip_del = skip_coord = 0
    skipped_rows: list[dict] = []

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_geojson = OUTPUT_DIR / f"clean_cultural_places_{ts}.geojson"
    out_skipped = OUTPUT_DIR / f"skipped_rows_missing_coords_{ts}.csv"

    for p in csv_paths:
        rows = read_csv_file(p)
        total += len(rows)
        for idx, rec in enumerate(rows, start=2):
            # Drop rows explicitly marked for deletion.
            delv = (rec.get("delete") or "").strip()
            if delv == "2" or delv == 2:
                skip_del += 1
                continue

            # Try to extract coordinates. If missing/invalid, log diagnostic info to skipped CSV.
            lat, lon, reason = try_extract_lat_lon(rec)
            if lat is None or lon is None:
                skip_coord += 1
                skipped_rows.append({
                    "source_file": p.name,
                    "row": idx,
                    "name": (rec.get("name") or "").strip(),
                    "city": (rec.get("city") or "").strip(),
                    "category": (rec.get("category") or "").strip(),
                    "website": (rec.get("website") or "").strip(),
                    "lat_field": (rec.get("lat") or "").strip(),
                    "lon_field": (rec.get("lon") or "").strip(),
                    "pair_example": find_any_latlon_pair_string(rec),
                    "delete": delv,
                    "reason": reason or "missing coordinates",
                })
                continue

            # Name needed early for outside-boundary whitelist check.
            name = (rec.get("name") or "").strip()

            # --- Boundary filter with whitelist bypass ---
            if use_boundary and not is_name_whitelisted(name) and not point_inside_any_boundary(lon, lat, boundary_polygons):
                skip_coord += 1
                skipped_rows.append({
                    "source_file": p.name,
                    "row": idx,
                    "name": name,
                    "city": (rec.get("city") or "").strip(),
                    "category": (rec.get("category") or "").strip(),
                    "website": (rec.get("website") or "").strip(),
                    "lat_field": (rec.get("lat") or "").strip(),
                    "lon_field": (rec.get("lon") or "").strip(),
                    "pair_example": find_any_latlon_pair_string(rec),
                    "delete": delv,
                    "reason": "outside boundary",
                })
                continue

            # Build the final feature (properties + geometry). Website/comments are optional fields.
            category = normalize_category(rec.get("category"))
            website  = normalize_website(rec.get("website"))
            comments = (rec.get("comments") or "").strip()
            city     = (rec.get("city") or "").strip()

            props = {
                "name": name,
                "category": category,
                "city": city,
                "color": color_for(category),
            }
            if website:
                props["website"] = website
            if comments:
                props["comments"] = comments

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            })
            kept += 1

    fc = {"type": "FeatureCollection", "features": features}

    # Write main GeoJSON output (compact separators, keep UTF-8 characters).
    with out_geojson.open("w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))

    # If anything got skipped, also write a diagnostic CSV to help curate/fix inputs.
    if skipped_rows:
        with out_skipped.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "source_file","row","name","city","category","website",
                    "lat_field","lon_field","pair_example","delete","reason"
                ]
            )
            writer.writeheader()
            writer.writerows(skipped_rows)

    # Summary for the console; messages are intentionally in English.
    print(f"✅ Wrote {out_geojson}")
    if skipped_rows:
        print(f"📝 Wrote log of skipped rows: {out_skipped}")
    print(f"   Total rows:               {total}")
    print(f"   Exported features:        {kept}")
    print(f"   Skipped delete==2:        {skip_del}")
    print(f"   Skipped without coords:   {skip_coord}  (incl. outside boundary)")
    print(f"   Whitelist (outside boundary): {len(OUTSIDE_NAME_WHITELIST)} names")

if __name__ == "__main__":
    main()
