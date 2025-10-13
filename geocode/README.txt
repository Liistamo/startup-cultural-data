Geocode Nominatim
=================

Ett Python-skript som geokodar adresser från en CSV-fil med hjälp av Nominatim (OpenStreetMap) via geopy.

Funktioner
----------
- Läser in en CSV-fil med kolumnerna: Adress, Hemsida, Kategori, Namn
- Om adressen saknar kommun läggs standardkommunen till (default: Stockholm)
- Använder Nominatim (OpenStreetMap) för geokodning
- Latitud och longitud sparas i separata kolumner
- Cachelagring för att undvika upprepade anrop
- Möjlighet till "dry-run" för att testa utan att spara
- Verboseläge för detaljerade loggar
- Utfilen sparas med tidsstämpel i filnamnet

Installation
------------
1. Klona eller kopiera projektet.
2. Skapa ett virtuellt Python-miljö (valfritt men rekommenderat):
   python3 -m venv venv
   source venv/bin/activate
3. Installera beroenden:
   pip install -r requirements.txt

requirements.txt innehåller:
   pandas>=2.1
   geopy>=2.4

Användning
----------
Grundläggande:
   python3 geocode_nominatim.py platser.csv

Dry-run (testläge, ingen fil sparas):
   python3 geocode_nominatim.py platser.csv --dry-run

Verbose (extra loggar):
   python3 geocode_nominatim.py platser.csv --verbose

Med e-post för User-Agent (rekommenderas):
   python3 geocode_nominatim.py platser.csv --email magnus.liistamo@humangeo.su.se

Output
------
Skriptet skapar en ny CSV-fil med samma namn som input + _geocoded + tidsstämpel.
Exempel: platser_geocoded_20250124_153210.csv

Kolumner som läggs till:
   NormalizedAdress  - adressen med kommun pålagd om den saknades
   lat               - latitud
   lon               - longitud
   geocode_status    - status (ok, not_found, cached_ok, error, etc.)
   geocode_display_name - adressbeskrivning från Nominatim

Cache
-----
För att undvika att slå upp samma adress flera gånger används en cachefil (.geocode_cache.json).
Den uppdateras löpande under körningen.

Tips
----
- Ange alltid din e-postadress vid körning (--email) för att följa Nominatims regler.
- Använd --dry-run först för att kontrollera att adresserna normaliseras rätt.
- Om du kör många adresser: öka sömnpause (--sleep) för att vara snäll mot tjänsten.
