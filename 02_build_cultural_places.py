# cities.py
import subprocess
import datetime
import glob
import os
import sys
import re
import shutil

def build_city_boundaries_sql():
    """
    Builds a UNION ALL expression that reads all per-city GeoJSON files
    and assigns the city name from the filename: <city>_boundary_<ts>.geojson
    Example: 'madrid_boundary_2025-09-11_13-55-55.geojson' -> city='Madrid'
    """
    per_city = sorted(glob.glob("geojson/boundaries/*_boundary_*.geojson"))
    if not per_city:
        return None, None

    selects = []
    for path in per_city:
        base = os.path.basename(path)
        # city = everything before "_boundary_"
        city_slug = re.sub(r"_boundary_.*$", "", base, flags=re.IGNORECASE)
        city_name = city_slug.replace("_", " ").title()
        selects.append(
            f"SELECT '{city_name}'::VARCHAR AS city, geom FROM ST_Read('{path}')"
        )

    union_sql = " \nUNION ALL\n".join(selects)
    label = f"{len(per_city)} per-city files"
    return union_sql, label


def main():
    union_sql, label = build_city_boundaries_sql()
    if not union_sql:
        print("❌ No per-city files found in geojson/*_boundary_*.geojson")
        sys.exit(1)

    print(f"➡️  Reading city polygons from: {label}")

    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    output_filename = f"geojson/cultural_places_{timestamp}.geojson"
    counts_city_csv = f"geojson/city_counts_{timestamp}.csv"
    counts_city_cat_csv = f"geojson/city_category_counts_{timestamp}.csv"

    duckdb_bin = shutil.which("duckdb") or "./duckdb"

    sql_query = f"""
    INSTALL httpfs;
    INSTALL spatial;
    LOAD httpfs;
    LOAD spatial;

    SET s3_region='us-west-2';
    SET threads TO 4;
    PRAGMA enable_progress_bar = true;

    -- 1) City polygons from per-city files (city parsed from filename)
    CREATE OR REPLACE TABLE city_boundaries AS
    {union_sql};

    -- 2) Overture places (geometry already GEOMETRY in EPSG:4326 in Parquet)
    CREATE OR REPLACE TABLE overture_places AS
    SELECT
      geometry,
      names, categories, websites
    FROM read_parquet(
      's3://overturemaps-us-west-2/release/2025-05-21.0/theme=places/type=place/*.parquet'
    )
    WHERE categories.primary IN (
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
      'video_film_production', 'cabaret', 'choir', 'circus', 'country_dance_hall', 'dance_club', 'jazz_and_blues', 'marching_band', 'musical_band_orchestras_and_symphonies', 'circus_school', 'mass_media', 'landscaping',  'landscape_architect', 'blacksmiths', 'community_book_boxes', 'screen_printing_t_shirt_printing', 'orchard'
    );

    -- 3) Spatial join with city polygon
    -- Tip: switch to ST_Covers(c.geom, p.geometry) if you want to include points on the boundary
    CREATE OR REPLACE TABLE european_filtered AS
    SELECT
      p.geometry, p.names, p.categories, p.websites, c.city
    FROM overture_places p
    JOIN city_boundaries c
      ON ST_Within(p.geometry, c.geom);

    -- 4) GeoJSON export (FeatureCollection)
    CREATE OR REPLACE TABLE european_geojson AS
    SELECT
      '{{ "type": "FeatureCollection", "features": [' ||
        string_agg(
          '{{ "type": "Feature", "geometry": ' || ST_AsGeoJSON(geometry) ||
          ', "properties": {{ ' ||
            '"name": "' || replace(coalesce(names.primary, 'No name'), '"', '\\"') || '", ' ||
            '"category": "' || coalesce(categories.primary, 'No category') || '", ' ||
            '"website": "' || replace(coalesce(websites[1], 'No website'), '"', '\\"') || '", ' ||
            '"city": "' || city || '", ' ||
            '"color": "' ||
              CASE
                WHEN categories.primary = 'art_museum' THEN '#2ca02c'
                WHEN categories.primary = 'art_gallery' THEN '#1f77b4'
                WHEN categories.primary = 'contemporary_art_museum' THEN '#ff7f0e'
                WHEN categories.primary = 'modern_art_museum' THEN '#d62728'
                WHEN categories.primary = 'art_space_rental' THEN '#9467bd'
                WHEN categories.primary = 'art_tours' THEN '#e377c2'
                WHEN categories.primary = 'community_center' THEN '#17becf'
                WHEN categories.primary = 'cultural_center' THEN '#7b4173'
                WHEN categories.primary = 'library' THEN '#8c6d31'
                WHEN categories.primary = 'theaters_and_performance_venues' THEN '#843c39'
                WHEN categories.primary = 'theatre' THEN '#d62728'
                WHEN categories.primary = 'museum' THEN '#637939'
                WHEN categories.primary = 'music_venue' THEN '#ff7f0e'
                WHEN categories.primary = 'cinema' THEN '#bcbd22'
                WHEN categories.primary = 'arts_and_entertainment' THEN '#9467bd'
                WHEN categories.primary = 'attractions_and_activities' THEN '#1f77b4'
                ELSE
                  'hsl(' ||
                  CAST(((abs(hash(coalesce(categories.primary, 'other'))) % 24) * 15) AS INTEGER) ||
                  ', 72%, 46%)'
              END
            || '" }}' ||
          '}}'
        , ','
        ) ||
      '] }}'
    AS geojson
    FROM european_filtered;

    COPY (SELECT geojson FROM european_geojson)
    TO '{output_filename}' (FORMAT CSV, HEADER FALSE, DELIMITER '', QUOTE '');

    -- 5) Summaries (extra CSV files)
    CREATE OR REPLACE TABLE city_counts AS
    SELECT city, COUNT(*) AS n
    FROM european_filtered
    GROUP BY city
    ORDER BY city;

    COPY city_counts TO '{counts_city_csv}' (HEADER, DELIMITER ',');

    CREATE OR REPLACE TABLE city_category_counts AS
    SELECT
      c.city,
      a.category,
      COALESCE(ct.n, 0) AS n
    FROM (SELECT DISTINCT city FROM city_boundaries) AS c
    CROSS JOIN (
      SELECT DISTINCT COALESCE(categories.primary,'(null)') AS category
      FROM overture_places
    ) AS a
    LEFT JOIN (
      SELECT
        city,
        COALESCE(categories.primary,'(null)') AS category,
        COUNT(*) AS n
      FROM european_filtered
      GROUP BY city, categories.primary
    ) AS ct
      ON ct.city = c.city AND ct.category = a.category
    ORDER BY c.city, n DESC;

    COPY city_category_counts TO '{counts_city_cat_csv}' (HEADER, DELIMITER ',');


    """

    try:
        subprocess.run([duckdb_bin, "-c", sql_query], check=True)
    except subprocess.CalledProcessError as e:
        print("❌ DuckDB run failed:", e)
        sys.exit(1)

    print(f"✅ Export complete: {output_filename}")
    print(f"📄 City counts: {counts_city_csv}")
    print(f"📄 City x Category counts: {counts_city_cat_csv}")


if __name__ == "__main__":
    main()
