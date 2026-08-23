import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HAR_FILE = "toxic_bms_6(1).har"
OUTPUT_FILE = "cinepolis_mumbai_properties.json"

TARGET = "Cinepolis"

print("=" * 100)
print("BMS TOXIC - HAR BASED CINEPOLIS DISCOVERY")
print("=" * 100)

print()
print("HAR FILE :", HAR_FILE)
print()
print("Reading HAR...")
print()

har_path = Path(HAR_FILE)

if not har_path.exists():
    raise FileNotFoundError(
        f"HAR file not found: {HAR_FILE}"
    )

with open(har_path, "r", encoding="utf-8") as f:
    har = json.load(f)

entries = har.get("log", {}).get("entries", [])

print("HAR entries:", len(entries))

print()
print("=" * 100)
print("SEARCHING BMS SHOWTIME RESPONSES")
print("=" * 100)

showtime_entries = []

for index, entry in enumerate(entries):

    request = entry.get("request", {})
    response = entry.get("response", {})
    url = request.get("url", "")

    if "showtimes-by-event" not in url:
        continue

    if response.get("status") != 200:
        continue

    content = response.get("content", {})
    text = content.get("text", "")

    if not text:
        continue

    showtime_entries.append({
        "index": index,
        "url": url,
        "text": text
    })

    print()
    print("SHOWTIME RESPONSE FOUND")
    print("HAR index :", index)
    print("Status    :", response.get("status"))
    print("Size      :", len(text))
    print("URL       :", url)

print()
print("Total valid showtime responses:", len(showtime_entries))

if not showtime_entries:
    print()
    print("NO SHOWTIME RESPONSE FOUND")
    print("=" * 100)
    raise SystemExit(0)

# ------------------------------------------------------------------
# Extract venue-card objects recursively
# ------------------------------------------------------------------

def extract_cinepolis_venues(obj, results):

    if isinstance(obj, dict):

        if obj.get("type") == "venue-card":

            additional = obj.get("additionalData", {})

            venue_code = additional.get("venueCode")
            venue_name = additional.get("venueName")

            if (
                venue_code
                and venue_name
                and TARGET.lower() in venue_name.lower()
            ):

                results.append({
                    "venueCode": venue_code,
                    "venueName": venue_name
                })

        for value in obj.values():
            extract_cinepolis_venues(value, results)

    elif isinstance(obj, list):

        for value in obj:
            extract_cinepolis_venues(value, results)


all_venues = []

for item in showtime_entries:

    try:
        data = json.loads(item["text"])
    except Exception as e:
        print()
        print("JSON parse failed for HAR index:", item["index"])
        print("Error:", e)
        continue

    found = []

    extract_cinepolis_venues(data, found)

    for venue in found:
        venue["har_index"] = item["index"]
        venue["source_url"] = item["url"]

    all_venues.extend(found)


# ------------------------------------------------------------------
# Deduplicate
# ------------------------------------------------------------------

unique = {}

for venue in all_venues:

    code = venue["venueCode"]

    if code not in unique:
        unique[code] = venue


venues = list(unique.values())

# ------------------------------------------------------------------
# Print results
# ------------------------------------------------------------------

print()
print("=" * 100)
print("CINEPOLIS VENUES FOUND IN HAR")
print("=" * 100)

if not venues:

    print()
    print("NO CINEPOLIS VENUE-CARD RECORDS FOUND")
    print()

else:

    for i, venue in enumerate(venues, 1):

        print()
        print(f"{i}. {venue['venueName']}")
        print("   Code :", venue["venueCode"])
        print("   HAR  :", venue["har_index"])

print()
print("=" * 100)
print("TOTAL UNIQUE CINEPOLIS VENUES:", len(venues))
print("=" * 100)

# ------------------------------------------------------------------
# Build clean output
# ------------------------------------------------------------------

output = {
    "source": "HAR",
    "movie": "Toxic: A Fairy Tale for Grown-ups",
    "region": "MUMBAI",
    "discovery_method": "BMS showtimes-by-event primary-dynamic response",
    "venues": venues
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print()
print("Saved:", OUTPUT_FILE)
print()
print("IMPORTANT:")
print("This version only reads the HAR.")
print("No BMS requests are made.")
print("No seat API is called.")
print("No showtime API is called.")
print("No Google Sheets are accessed.")
print("No YAML is modified.")
print("No existing tracker logic is modified.")
print()
