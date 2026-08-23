import json
import re
import time
from datetime import datetime

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

MOVIE = "Toxic: A Fairy Tale for Grown-ups"
CITY = "mumbai"
REGION_CODE = "MUMBAI"
DATE_CODE = "20260826"

EVENT_CODES = [
    "ET00379311",  # Hindi 2D
    "ET00513458",  # IMAX
    "ET00513506",  # 4DX
]

BMS_MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

SHOWTIME_API = (
    "https://in.bookmyshow.com/api/movies-data/v5/"
    "showtimes-by-event/primary-dynamic"
)

OUTPUT_FILE = "cinepolis_mumbai_discovery.json"


# ============================================================
# PRINT
# ============================================================

def banner(title):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


# ============================================================
# NORMALIZE
# ============================================================

def clean(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return value

    return re.sub(r"\s+", " ", str(value)).strip()


def lower(value):
    return clean(value).lower()


# ============================================================
# CINEPOLIS DETECTION
# ============================================================

def is_cinepolis(value):
    if value is None:
        return False

    text = lower(value)

    return (
        "cinepolis" in text
        or "cinépolis" in text
    )


# ============================================================
# RECURSIVE VENUE EXTRACTION
# ============================================================

def recursive_find_venues(obj, path="root"):
    """
    Walk the complete BMS JSON.

    We intentionally don't assume a single fixed JSON structure.
    BMS has changed the showtime response structure multiple times.
    """

    results = []

    if isinstance(obj, dict):

        # Look for dictionary fields which look like venue information.
        venue_text = ""

        for key in [
            "venueName",
            "venue_name",
            "venue",
            "cinemaName",
            "cinema_name",
            "theatreName",
            "theatre_name",
            "name",
            "displayName",
            "title",
        ]:
            value = obj.get(key)

            if isinstance(value, str) and value.strip():
                if is_cinepolis(value):
                    venue_text = value
                    break

        if venue_text:

            record = {
                "venue_name": clean(venue_text),
                "venue_code": "",
                "address": "",
                "event_code": "",
                "format": "",
                "session_id": "",
                "path": path,
            }

            # Venue identifiers
            for key in [
                "venueCode",
                "venue_code",
                "cinemaCode",
                "cinema_code",
                "theatreCode",
                "theatre_code",
                "code",
                "id",
            ]:
                value = obj.get(key)

                if value is not None:
                    value = clean(value)

                    if value:
                        record["venue_code"] = value
                        break

            # Address
            for key in [
                "address",
                "venueAddress",
                "cinemaAddress",
                "theatreAddress",
                "location",
            ]:
                value = obj.get(key)

                if isinstance(value, str):
                    if value.strip():
                        record["address"] = clean(value)
                        break

                elif isinstance(value, dict):
                    parts = []

                    for v in value.values():
                        if isinstance(v, str):
                            parts.append(v)

                    if parts:
                        record["address"] = clean(" ".join(parts))
                        break

            # Event
            for key in [
                "eventCode",
                "event_code",
                "etCode",
                "et_code",
            ]:
                value = obj.get(key)

                if value:
                    record["event_code"] = clean(value)
                    break

            # Format
            for key in [
                "format",
                "formatName",
                "format_name",
                "languageFormat",
                "screenFormat",
            ]:
                value = obj.get(key)

                if isinstance(value, str) and value.strip():
                    record["format"] = clean(value)
                    break

            # Session
            for key in [
                "sessionId",
                "session_id",
                "sessionCode",
                "session_code",
                "session",
            ]:
                value = obj.get(key)

                if value is not None:
                    value = clean(value)

                    if value:
                        record["session_id"] = value
                        break

            results.append(record)

        for key, value in obj.items():
            results.extend(
                recursive_find_venues(
                    value,
                    f"{path}.{key}"
                )
            )

    elif isinstance(obj, list):

        for index, value in enumerate(obj):
            results.extend(
                recursive_find_venues(
                    value,
                    f"{path}[{index}]"
                )
            )

    return results


# ============================================================
# GENERIC TEXT SCAN
# ============================================================

def scan_cinepolis_strings(obj, found=None):

    if found is None:
        found = set()

    if isinstance(obj, dict):

        for key, value in obj.items():

            if isinstance(value, str):

                if is_cinepolis(value):
                    found.add(clean(value))

            elif isinstance(value, (dict, list)):
                scan_cinepolis_strings(value, found)

    elif isinstance(obj, list):

        for value in obj:
            scan_cinepolis_strings(value, found)

    return found


# ============================================================
# REQUEST SHOWTIME API THROUGH BROWSER SESSION
# ============================================================

def request_showtime(page, event_code):

    params = {
        "etCodes": "*",
        "dateCode": DATE_CODE,
        "isDesktop": "true",
        "regionCode": REGION_CODE,
        "xLocationShared": "false",
        "memberId": "",
        "lsId": "",
        "subCode": "",
        "appCode": "WEB",
        "language": "hindi",
        "refEventCode": event_code,
    }

    print()
    print("-" * 100)
    print("REQUESTING SHOWTIME DATA")
    print("-" * 100)

    print("Event code:", event_code)
    print("Endpoint:", SHOWTIME_API)

    print("\nParameters:")
    print(json.dumps(params, indent=2))

    for attempt in range(1, 4):

        print(f"\nAttempt {attempt}/3")

        try:

            response = page.request.get(
                SHOWTIME_API,
                params=params,
                headers={
                    "accept": "application/json, text/plain, */*",
                    "referer": BMS_MOVIE_URL,
                    "origin": "https://in.bookmyshow.com",
                    "x-requested-with": "XMLHttpRequest",
                },
                timeout=60000,
            )

            print("HTTP status:", response.status)

            body = response.text()

            print("Response size:", len(body))

            if response.status == 200 and body:

                try:
                    data = json.loads(body)

                    print("JSON received successfully.")

                    return data

                except Exception as e:

                    print("JSON parse error:", e)

                    print("Response preview:")
                    print(body[:1000])

            else:

                print("Response preview:")
                print(body[:500])

        except Exception as e:

            print("Request error:", repr(e))

        if attempt < 3:
            time.sleep(3)

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    banner("BMS TOXIC - MUMBAI CINEPOLIS PROPERTY DISCOVERY")

    print("Movie      :", MOVIE)
    print("City       :", CITY)
    print("Region     :", REGION_CODE)
    print("Date       :", DATE_CODE)
    print("Event codes:", ", ".join(EVENT_CODES))

    print()
    print("MODE:")
    print("PROPERTY DISCOVERY ONLY")
    print("NO GOOGLE SHEETS")
    print("NO SEAT API")
    print("NO SEAT PARSING")

    all_properties = []
    raw_event_data = {}

    with sync_playwright() as p:

        banner("LAUNCHING CHROMIUM")

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        # --------------------------------------------------------
        # First establish BMS session.
        # --------------------------------------------------------

        banner("ESTABLISHING BMS SESSION")

        try:

            response = page.goto(
                BMS_MOVIE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print("Movie page HTTP status:", response.status)
            else:
                print("Movie page returned no response.")

        except Exception as e:

            print("Movie page navigation error:", repr(e))

        print("Waiting for BMS session...")
        time.sleep(8)

        # Scroll to allow normal BMS JS to execute.
        for _ in range(5):

            try:
                page.mouse.wheel(0, 2500)
            except Exception:
                pass

            time.sleep(1)

        # --------------------------------------------------------
        # Request each known Toxic event.
        # --------------------------------------------------------

        for event_code in EVENT_CODES:

            data = request_showtime(
                page,
                event_code
            )

            if data is None:

                print(
                    f"\nNO SHOWTIME DATA FOR {event_code}"
                )

                continue

            raw_event_data[event_code] = data

            # ----------------------------------------------------
            # Search JSON recursively.
            # ----------------------------------------------------

            records = recursive_find_venues(
                data,
                path="root"
            )

            strings = scan_cinepolis_strings(
                data
            )

            print()
            print(
                f"Cinepolis-related strings found: "
                f"{len(strings)}"
            )

            for value in sorted(strings):

                print("  ", value)

            print()
            print(
                f"Potential Cinepolis venue records: "
                f"{len(records)}"
            )

            for record in records:

                record["source_event_code"] = event_code

                all_properties.append(record)

        # --------------------------------------------------------
        # Close browser.
        # --------------------------------------------------------

        browser.close()

    # ============================================================
    # DEDUPLICATE
    # ============================================================

    unique = {}

    for record in all_properties:

        name = clean(record.get("venue_name"))

        if not name:
            continue

        code = clean(record.get("venue_code"))

        key = (
            lower(name),
            code
        )

        if key not in unique:

            unique[key] = record

        else:

            existing = unique[key]

            for field in [
                "address",
                "event_code",
                "format",
                "session_id",
            ]:

                if (
                    not existing.get(field)
                    and record.get(field)
                ):
                    existing[field] = record[field]

    properties = list(unique.values())

    # ============================================================
    # RESULT
    # ============================================================

    banner("CINEPOLIS PROPERTIES FOUND IN MUMBAI")

    if not properties:

        print("NO CINEPOLIS VENUE RECORDS WERE EXTRACTED.")

        print()
        print(
            "IMPORTANT: This does NOT mean there are no Cinepolis "
            "properties."
        )

        print(
            "It means the BMS response structure did not expose "
            "the venue field in the expected form."
        )

    else:

        for index, record in enumerate(properties, 1):

            print()
            print(
                f"[{index}] "
                f"{record.get('venue_name', '')}"
            )

            print(
                "    Venue Code :",
                record.get("venue_code", "")
            )

            print(
                "    Address    :",
                record.get("address", "")
            )

            print(
                "    Event Code :",
                record.get("event_code", "")
            )

            print(
                "    Format     :",
                record.get("format", "")
            )

            print(
                "    Session    :",
                record.get("session_id", "")
            )

    # ============================================================
    # SAVE OUTPUT
    # ============================================================

    output = {
        "timestamp": datetime.now().isoformat(),
        "movie": MOVIE,
        "city": CITY,
        "region_code": REGION_CODE,
        "date": DATE_CODE,
        "event_codes": EVENT_CODES,
        "properties": properties,
        "property_count": len(properties),
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 100)
    print("DISCOVERY COMPLETED")
    print("=" * 100)
    print("Cinepolis properties:", len(properties))
    print("Saved:", OUTPUT_FILE)
    print("=" * 100)


if __name__ == "__main__":
    main()
