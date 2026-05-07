#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv, json, time, hashlib, sys, pathlib, requests
from urllib.parse import urlencode
from typing import Optional

INPUT_CSV  = "addresses.csv"        # måste innehålla kolumn: geocode_display_name
OUTPUT_CSV = "addresses_geocoded.csv"
CACHE_FILE = "geocode_cache.json"
USER_AGENT = "local-geocoder/1.0 (kontakt: magnus.liistamo@humangeo.su.se)"  # <-- byt till din e-post

BASE_URL = "https://nominatim.openstreetmap.org/search"  # offentlig, gratis

def load_cache():
    p = pathlib.Path(CACHE_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(cache):
    pathlib.Path(CACHE_FILE).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def norm_key(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()

def geocode(addr: str, session: requests.Session, cache: dict) -> Optional[dict]:
    key = norm_key(addr)
    if key in cache:
        return cache[key]

    # Begränsa sök till Norden/SE+FI och prioritera Sverige
    params = {
        "q": addr,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 0,
        "countrycodes": "se,fi",  # Kirkkonummi i listan kräver FI
        # "viewbox": "11.0,60.0,19.0,58.0", "bounded": 0,  # (ex. Stockholm-målning om du vill)
    }
    url = f"{BASE_URL}?{urlencode(params)}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        r = session.get(url, headers=headers, timeout=20)
        if r.status_code == 429:
            # för många anrop – vänta och försök igen
            time.sleep(2)
            r = session.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"⚠️  Geocode misslyckades för '{addr}': {e}", file=sys.stderr)
        data = []

    item = data[0] if data else None
    if item:
        res = {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "source": "nominatim",
        }
    else:
        res = None

    cache[key] = res
    # snäll rate limit
    time.sleep(1.0)
    return res

def main():
    cache = load_cache()
    out_rows = []
    seen = set()

    try:
        f = open(INPUT_CSV, newline="", encoding="utf-8")
    except FileNotFoundError:
        print(f"❌ Hittar inte {INPUT_CSV}. Lägg en CSV med kolumnen 'geocode_display_name' i samma mapp.", file=sys.stderr)
        sys.exit(1)

    with f:
        reader = csv.DictReader(f)
        if "geocode_display_name" not in (reader.fieldnames or []):
            print("❌ Input saknar kolumnen 'geocode_display_name'", file=sys.stderr)
            sys.exit(1)

        with requests.Session() as session:
            for row in reader:
                addr_raw = (row.get("geocode_display_name") or "").strip()
                if not addr_raw:
                    row["lat"] = ""
                    row["lon"] = ""
                    out_rows.append(row)
                    continue

                # hoppa över exakta dubletter i inläsningen
                sig = hashlib.sha1(addr_raw.encode("utf-8")).hexdigest()
                if sig in seen:
                    # fyll från cache direkt
                    res = cache.get(norm_key(addr_raw))
                else:
                    seen.add(sig)
                    try:
                        res = geocode(addr_raw, session, cache)
                    except Exception as e:
                        print(f"⚠️  Fel vid geocode('{addr_raw}'): {e}", file=sys.stderr)
                        res = None

                if res:
                    row["lat"] = res["lat"]
                    row["lon"] = res["lon"]
                else:
                    row["lat"] = ""
                    row["lon"] = ""

                out_rows.append(row)

    # skriv resultat
    fieldnames = list(out_rows[0].keys()) if out_rows else ["geocode_display_name","lat","lon"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f_out:
        w = csv.DictWriter(f_out, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    save_cache(cache)
    print(f"✅ Klart. Skrev {OUTPUT_CSV} (cache: {CACHE_FILE}).")

if __name__ == "__main__":
    main()
