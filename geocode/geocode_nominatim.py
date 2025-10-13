#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Geokodar en CSV med kolumnerna: Adress, Hemsida, Kategori, Namn (valfritt även Epost)
- Om adressen saknar kommun lägger vi på ", <city_default>" (default: Stockholm)
- Använder Nominatim (OpenStreetMap) via geopy
- Hämtar ev. website/email från OSM (extratags) -> OSMWebsite/OSMEmail + sammanslagna WebsiteFinal/EmailFinal
- Har enkel filcache så vi inte upprepar samma anrop
- --dry-run skriver bara ut resultat, sparar inte fil
- --verbose ger extra loggar
- Outputfil namnsätts med tidsstämpel om -o inte anges
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter


# Vanliga kommun-/stadsdelsnamn för heuristik (kompaktifieras för matchning)
MUNICIPALITIES_RAW = {
    "stockholm","solna","sundbyberg","norrtälje","upplands väsby","vallentuna","österåker",
    "vaxholm","danderyd","täby","lidingö","sollentuna","järfälla","upplands-bro","upplands bro",
    "ekerö","huddinge","botkyrka","salem","haninge","tyresö","nacka","värmdö","nynäshamn",
    "södertälje","sigtuna",
    "gamla stan","östermalm","vasastan","södermalm","kungsholmen","hägersten","årsta",
    "skärholmen","skarpnäck","farsta","hässelby","spånga","bromma","djurgården"
}
MUNICIPALITIES = {re.sub(r"\s+", "", m.lower()) for m in MUNICIPALITIES_RAW}


def compact(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def looks_complete(address: str) -> bool:
    """
    Heuristik för att avgöra om en kommun redan finns med:
    - Innehåller ett kommatecken (ofta "gata 1, Kommun")
    - Innehåller ett 5-siffrigt postnummer
    - Innehåller något känt kommun-/stadsdelsnamn
    """
    a = (address or "").strip()
    if not a:
        return False
    if "," in a:
        return True
    if re.search(r"\b\d{3}\s?\d{2}\b", a):  # t.ex. 141 89
        return True
    ac = compact(a)
    for muni in MUNICIPALITIES:
        if muni in ac:
            return True
    return False


def normalize_address(address: str, city_default: str) -> str:
    address = (address or "").strip()
    if not address:
        return address
    if looks_complete(address):
        return address
    return f"{address}, {city_default}"


def get_str(val) -> str:
    """
    Säker konvertering till str:
    - None -> ""
    - NaN (pandas) -> ""
    - Annars str(val)
    """
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except Exception:
        pass
    return str(val)


def load_cache(cache_path: str) -> Dict[str, Any]:
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, Any], cache_path: str) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


EMAIL_DEFAULTS: List[str] = ["magnus.liistamo@humangeo.su.se"]

def build_user_agent(emails_arg: Optional[str]) -> str:
    """
    Bygger en User-Agent som inkluderar e-post (rekommenderas av Nominatim).
    Kan utökas med --emails "a@b,c@d".
    """
    ua = "cultural-geocoder/1.1"
    emails: List[str] = EMAIL_DEFAULTS.copy()
    if emails_arg:
        extra = [e.strip() for e in emails_arg.split(",") if e.strip()]
        for e in extra:
            if e not in emails:
                emails.append(e)
    if emails:
        ua += " (" + "; ".join(emails) + ")"
    return ua


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main():
    parser = argparse.ArgumentParser(description="Geocode CSV via Nominatim (OpenStreetMap).")
    parser.add_argument("input", help="Input CSV-fil (måste ha kolumnerna: Adress, Hemsida, Kategori, Namn)")
    parser.add_argument("-o", "--output", default=None, help="Utfil (CSV). Default: <input>_geocoded_YYYYMMDD_HHMMSS.csv")
    parser.add_argument("--dry-run", action="store_true", help="Kör utan att spara outputfil")
    parser.add_argument("--verbose", action="store_true", help="Skriv extra loggar")
    parser.add_argument("--emails", default=None, help="Kommaseparerade e-postadresser för User-Agent (lägger till standard-e-post).")
    parser.add_argument("--city-default", default="Stockholm", help="Kommun som läggs till om saknas (default: Stockholm)")
    parser.add_argument("--cache", default=".geocode_cache.json", help="Sökväg till cachefil (default: .geocode_cache.json)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sekunders paus mellan Nominatim-anrop (default: 1.0)")
    args = parser.parse_args()

    if args.verbose:
        print(f"[INFO] Input: {args.input}")
        print(f"[INFO] Dry-run: {args.dry_run}")
        print(f"[INFO] Verbose: {args.verbose}")
        print(f"[INFO] City default: {args.city_default}")
        if EMAIL_DEFAULTS or args.emails:
            print(f"[INFO] E-post i User-Agent: {', '.join(EMAIL_DEFAULTS + ([args.emails] if args.emails else []))}")

    # Läs CSV
    try:
        # Läs som strängar och utan att skapa NaN för tomma fält
        df = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    except Exception as e:
        print(f"[ERROR] Kunde inte läsa CSV: {e}", file=sys.stderr)
        sys.exit(1)

    # Verifiera kolumner
    required_cols = ["Adress", "Hemsida", "Kategori", "Namn"]
    for col in required_cols:
        if col not in df.columns:
            print(f"[ERROR] Saknar kolumn: '{col}' i {args.input}", file=sys.stderr)
            sys.exit(1)

    # Initiera geocoder
    user_agent = build_user_agent(args.emails)
    geocoder = Nominatim(user_agent=user_agent, timeout=10)

    # Vi vill alltid få extratags (website/email) och addressdetails
    def _geocode_fn(q: str):
        return geocoder.geocode(q, addressdetails=True, extratags=True)

    geocode = RateLimiter(_geocode_fn, min_delay_seconds=max(args.sleep, 1.0), swallow_exceptions=True)

    cache = load_cache(args.cache)

    # Nya kolumner
    df["NormalizedAdress"] = df["Adress"].apply(lambda a: normalize_address(get_str(a), args.city_default))
    df["lat"] = None
    df["lon"] = None
    df["geocode_status"] = None
    df["geocode_display_name"] = None
    df["OSMWebsite"] = None
    df["WebsiteFinal"] = None
    df["OSMEmail"] = None
    df["EmailFinal"] = None

    for idx, row in df.iterrows():
        raw_addr = get_str(row.get("Adress")).strip()
        query = get_str(row.get("NormalizedAdress")).strip()

        if not query:
            df.at[idx, "geocode_status"] = "empty_address"
            if args.verbose:
                print(f"[WARN] Tom adress på rad {idx+1}")
            continue

        # Cacheträff?
        if query in cache:
            res = cache[query]
            if args.verbose:
                print(f"[CACHE] {query} -> ({res.get('lat')}, {res.get('lon')}) [{res.get('status')}]")

            df.at[idx, "lat"] = res.get("lat")
            df.at[idx, "lon"] = res.get("lon")
            df.at[idx, "geocode_status"] = res.get("status", "cached_ok")
            df.at[idx, "geocode_display_name"] = res.get("display_name")
            df.at[idx, "OSMWebsite"] = res.get("osm_website")
            df.at[idx, "OSMEmail"] = res.get("osm_email")

            input_site = get_str(row.get("Hemsida")).strip() or None
            df.at[idx, "WebsiteFinal"] = input_site or res.get("osm_website")

            input_email = None
            if "Epost" in df.columns:
                tmp_email = get_str(row.get("Epost")).strip()
                if tmp_email and EMAIL_RE.match(tmp_email):
                    input_email = tmp_email
            df.at[idx, "EmailFinal"] = input_email or res.get("osm_email")
            continue

        if args.verbose:
            print(f"[LOOKUP] '{raw_addr}' => '{query}'")

        try:
            location = geocode(query)
            if location:
                lat = location.latitude
                lon = location.longitude

                # extratags kan innehålla website / contact:website / url samt email / contact:email
                raw = location.raw or {}
                extratags = raw.get("extratags") or {}
                osm_website = extratags.get("website") or extratags.get("contact:website") or extratags.get("url")
                osm_email = extratags.get("email") or extratags.get("contact:email")

                # enkel sanering
                if osm_email and not EMAIL_RE.match(osm_email):
                    osm_email = None

                df.at[idx, "lat"] = lat
                df.at[idx, "lon"] = lon
                df.at[idx, "geocode_status"] = "ok"
                df.at[idx, "geocode_display_name"] = location.address
                df.at[idx, "OSMWebsite"] = osm_website
                df.at[idx, "OSMEmail"] = osm_email

                # Slå ihop input/OSM för site/email på ett robust sätt
                input_site = get_str(row.get("Hemsida")).strip() or None
                df.at[idx, "WebsiteFinal"] = input_site or osm_website

                input_email = None
                if "Epost" in df.columns:
                    tmp_email = get_str(row.get("Epost")).strip()
                    if tmp_email and EMAIL_RE.match(tmp_email):
                        input_email = tmp_email
                df.at[idx, "EmailFinal"] = input_email or osm_email

                cache[query] = {
                    "lat": lat,
                    "lon": lon,
                    "status": "ok",
                    "display_name": location.address,
                    "osm_website": osm_website,
                    "osm_email": osm_email,
                }

                if args.verbose:
                    print(f"[OK] {query} -> ({lat:.6f}, {lon:.6f}) | site={osm_website or '-'} | email={osm_email or '-'}")
            else:
                df.at[idx, "geocode_status"] = "not_found"
                cache[query] = {
                    "lat": None,
                    "lon": None,
                    "status": "not_found",
                    "display_name": None,
                    "osm_website": None,
                    "osm_email": None,
                }
                if args.verbose:
                    print(f"[MISS] {query} -> not_found")

        except Exception as e:
            df.at[idx, "geocode_status"] = f"error: {e.__class__.__name__}"
            if args.verbose:
                print(f"[ERROR] {query} -> {e}")

        # Liten extra säkerhet (utöver RateLimiter)
        time.sleep(0.0)

    # spara cache
    save_cache(cache, args.cache)

    # Skriv ut sample i dry-run
    if args.dry_run:
        if args.verbose:
            print("\n[DRY-RUN] Förhandsvisar de första raderna:")
        preview_cols = [
            "Adress","NormalizedAdress","Kategori","Namn",
            "lat","lon","geocode_status",
            "OSMWebsite","WebsiteFinal","OSMEmail","EmailFinal"
        ]
        use_cols = [c for c in preview_cols if c in df.columns]
        print(df[use_cols].head(20).to_string(index=False))
        print("\n[DRY-RUN] Ingen fil sparades.")
        return

    # Spara resultat (med tidsstämpel om ej angivet)
    if args.output:
        out_path = args.output
    else:
        base, _ = os.path.splitext(args.input)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = f"{base}_geocoded_{ts}.csv"

    try:
        df.to_csv(out_path, index=False)
        print(f"[DONE] Sparat: {out_path}")
    except Exception as e:
        print(f"[ERROR] Kunde inte spara output: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
