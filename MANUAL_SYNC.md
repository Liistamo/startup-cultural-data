# MANUAL_SYNC — Copy data outputs to the theme

Use this when you want to **manually** copy the generated GeoJSON from
`startup-cultural-data` into the WordPress theme repo `startup-wp-theme`.

## macOS / Linux
```bash
# 1) Adjust absolute paths
DATA_REPO="/absolute/path/to/startup-cultural-data"
THEME_DIR="/absolute/path/to/startup-wp-theme/_tw"

# 2) Create target dirs (first time)
mkdir -p "$THEME_DIR/assets/geojson/boundaries"

# 3) Copy latest outputs
rsync -av --delete   "$DATA_REPO/geojson/clean_cultural_places_".*.geojson   "$THEME_DIR/assets/geojson/"

rsync -av --delete   "$DATA_REPO/geojson/boundaries/"*_boundary_*.geojson   "$THEME_DIR/assets/geojson/boundaries/"
```

## Windows PowerShell
```powershell
# 1) Adjust absolute paths
$DATA_REPO  = "C:\path	o\startup-cultural-data"
$THEME_DIR  = "C:\path	o\startup-wp-theme\_tw"

# 2) Create target dirs (first time)
New-Item -ItemType Directory -Force -Path "$THEME_DIRssets\geojsonoundaries" | Out-Null

# 3) Copy latest outputs
Copy-Item -Path "$DATA_REPO\geojson\clean_cultural_places_*.geojson" `
          -Destination "$THEME_DIRssets\geojson" -Force

Copy-Item -Path "$DATA_REPO\geojsonoundaries\*_boundary_*.geojson" `
          -Destination "$THEME_DIRssets\geojsonoundaries" -Force
```

**Done.** Open your site and the map should reflect the new data. The template always uses the newest matching files.
