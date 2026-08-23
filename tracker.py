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

MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

EVENT_CODES = [
    "ET00379311",
    "ET00513458",
    "ET00513506",
]

OUTPUT_FILE = "cinepolis_mumbai_discovery.json"
RAW_FILE = "bms_captured_showtime_responses.json"


# ============================================================
# HELPERS
# ============================================================

def banner(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def clean(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return value

    return re.sub(r"\s+", " ", str(value)).strip()


def is_cinepolis(value):
    if not isinstance(value, str):
        return False

    text = value.lower()

    return (
        "cinepolis" in text
        or "cinépolis" in text
    )


# ============================================================
# FIND CINEPOLIS IN ANY JSON STRUCTURE
# ============================================================

def scan_json_for_cinepolis(obj, path="root", results=None):

    if results is None:
        results = []

    if isinstance(obj, dict):

        # Check whether this object itself contains Cinepolis.
        object_text = []

        for key, value in obj.items():

            if isinstance(value, str):
                object_text.append(value)

        joined = " | ".join(object_text)

        if is_cinepolis(joined):

            results.append({
                "path": path,
                "object": obj
            })

        for key, value in obj.items():

            scan_json_for_cinepolis(
                value,
                f"{path}.{key}",
                results
            )

    elif isinstance(obj, list):

        for index, value in enumerate(obj):

            scan_json_for_cinepolis(
                value,
                f"{path}[{index}]",
                results
            )

    return results


# ============================================================
# EXTRACT VENUE-LIKE OBJECTS
# ============================================================

def extract_properties(obj, event_code="", path="root"):

    found = []

    if isinstance(obj, dict):

        # Collect all string values.
        strings = {}

        for key, value in obj.items():

            if isinstance(value, str):
                strings[key] = clean(value)

        cinepolis_fields = []

        for key, value in strings.items():

            if is_cinepolis(value):
                cinepolis_fields.append((key, value))

        if cinepolis_fields:

            record = {
                "event_code": event_code,
                "venue_name": "",
                "venue_code": "",
                "address": "",
                "format": "",
                "language": "",
                "session_id": "",
                "time": "",
                "path": path,
            }

            # ------------------------------------------------
            # Venue name
            # ------------------------------------------------

            name_keys = [
                "venueName",
                "venue_name",
                "cinemaName",
                "cinema_name",
                "theatreName",
                "theatre_name",
                "name",
                "displayName",
                "display_name",
                "title",
            ]

            for key in name_keys:

                if key in strings:

                    if is_cinepolis(strings[key]):

                        record["venue_name"] = strings[key]
                        break

            # If no obvious venue-name field, use the
            # Cinepolis-containing value.
            if not record["venue_name"]:

                record["venue_name"] = cinepolis_fields[0][1]

            # ------------------------------------------------
            # Venue code
            # ------------------------------------------------

            code_keys = [
                "venueCode",
                "venue_code",
                "cinemaCode",
                "cinema_code",
                "theatreCode",
                "theatre_code",
                "code",
                "id",
            ]

            for key in code_keys:

                if key in strings:

                    record["venue_code"] = strings[key]
                    break

            # ------------------------------------------------
            # Address
            # ------------------------------------------------

            address_keys = [
                "address",
                "venueAddress",
                "venue_address",
                "cinemaAddress",
                "cinema_address",
                "theatreAddress",
                "theatre_address",
            ]

            for key in address_keys:

                if key in strings:

                    record["address"] = strings[key]
                    break

            # ------------------------------------------------
            # Format
            # ------------------------------------------------

            format_keys = [
                "format",
                "formatName",
                "format_name",
                "screenFormat",
                "screen_format",
                "languageFormat",
                "language_format",
            ]

            for key in format_keys:

                if key in strings:

                    record["format"] = strings[key]
                    break

            # ------------------------------------------------
            # Language
            # ------------------------------------------------

            language_keys = [
                "language",
                "languageName",
                "language_name",
            ]

            for key in language_keys:

                if key in strings:

                    record["language"] = strings[key]
                    break

            # ------------------------------------------------
            # Session
            # ------------------------------------------------

            session_keys = [
                "sessionId",
                "session_id",
                "sessionCode",
                "session_code",
            ]

            for key in session_keys:

                if key in strings:

                    record["session_id"] = strings[key]
                    break

            # ------------------------------------------------
            # Time
            # ------------------------------------------------

            time_keys = [
                "showTime",
                "show_time",
                "startTime",
                "start_time",
                "time",
            ]

            for key in time_keys:

                if key in strings:

                    record["time"] = strings[key]
                    break

            found.append(record)

        # Continue recursively.

        for key, value in obj.items():

            found.extend(
                extract_properties(
                    value,
                    event_code,
                    f"{path}.{key}"
                )
            )

    elif isinstance(obj, list):

        for index, value in enumerate(obj):

            found.extend(
                extract_properties(
                    value,
                    event_code,
                    f"{path}[{index}]"
                )
            )

    return found


# ============================================================
# NETWORK RESPONSE HANDLER
# ============================================================

def capture_response(response, captured):

    try:

        url = response.url

        # Only inspect BMS responses.
        if "bookmyshow.com" not in url:
            return

        resource_type = response.request.resource_type

        # Showtime API is normally XHR/fetch.
        if resource_type not in [
            "xhr",
            "fetch",
            "document",
        ]:
            return

        # We are especially interested in these.
        interesting = (
            "showtimes" in url.lower()
            or "primary-dynamic" in url.lower()
            or "movies-data" in url.lower()
            or "event" in url.lower()
        )

        if not interesting:
            return

        print()
        print("[NETWORK]")
        print("Status :", response.status)
        print("Type   :", resource_type)
        print("URL    :", url)

        try:

            body = response.text()

        except Exception as e:

            print("Could not read response:", repr(e))
            return

        print("Size   :", len(body))

        if not body:
            return

        # Don't store Cloudflare HTML.
        if body.lstrip().startswith("<!DOCTYPE"):
            print("Skipped HTML/Cloudflare response.")
            return

        try:

            data = json.loads(body)

        except Exception:

            print("Response is not JSON.")
            return

        captured.append({
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "status": response.status,
            "resource_type": resource_type,
            "data": data,
        })

        print("JSON CAPTURED")

    except Exception as e:

        print("Response handler error:", repr(e))


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
    print("IMPORTANT:")
    print("This version does NOT directly request the BMS API.")
    print("It captures responses generated by the BMS webpage.")

    captured = []

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

        # ----------------------------------------------------
        # Capture all relevant network responses.
        # ----------------------------------------------------

        page.on(
            "response",
            lambda response: capture_response(
                response,
                captured
            )
        )

        # ----------------------------------------------------
        # Open movie page.
        # ----------------------------------------------------

        banner("OPENING TOXIC MUMBAI PAGE")

        try:

            response = page.goto(
                MOVIE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:

                print(
                    "Movie page HTTP status:",
                    response.status
                )

        except Exception as e:

            print(
                "Movie page navigation error:",
                repr(e)
            )

        print()
        print("Waiting for BMS JavaScript...")
        time.sleep(10)

        # ----------------------------------------------------
        # Scroll.
        # ----------------------------------------------------

        banner("SCROLLING BMS PAGE")

        for i in range(8):

            try:

                page.mouse.wheel(
                    0,
                    2500
                )

            except Exception:
                pass

            print(
                f"Scroll {i + 1}/8"
            )

            time.sleep(1.5)

        # ----------------------------------------------------
        # Wait for delayed requests.
        # ----------------------------------------------------

        print()
        print(
            "Waiting for delayed BMS responses..."
        )

        time.sleep(10)

        # ----------------------------------------------------
        # If the page didn't trigger showtime API,
        # navigate to each event's buy-ticket page.
        # ----------------------------------------------------

        if len(captured) == 0:

            banner(
                "NO SHOWTIME RESPONSE YET - "
                "OPENING EVENT PAGES"
            )

            for event_code in EVENT_CODES:

                event_url = (
                    "https://in.bookmyshow.com/movies/mumbai/"
                    "toxic-a-fairy-tale-for-grown-ups/"
                    f"buytickets/{event_code}/"
                    f"{DATE_CODE}"
                    "?etCodes=*"
                    "&language=hindi"
                    f"&refEventCode={event_code}"
                )

                print()
                print(
                    "Opening:",
                    event_code
                )

                try:

                    response = page.goto(
                        event_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )

                    if response:

                        print(
                            "HTTP status:",
                            response.status
                        )

                except Exception as e:

                    print(
                        "Navigation error:",
                        repr(e)
                    )

                time.sleep(8)

                for i in range(4):

                    try:
                        page.mouse.wheel(
                            0,
                            2500
                        )
                    except Exception:
                        pass

                    time.sleep(1)

                time.sleep(5)

        # ----------------------------------------------------
        # Final wait.
        # ----------------------------------------------------

        time.sleep(5)

        browser.close()

    # ========================================================
    # SAVE RAW CAPTURE
    # ========================================================

    banner("CAPTURE SUMMARY")

    print(
        "Captured BMS JSON responses:",
        len(captured)
    )

    with open(
        RAW_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            captured,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(
        "Saved raw responses:",
        RAW_FILE
    )

    # ========================================================
    # SEARCH FOR CINEPOLIS
    # ========================================================

    banner("SEARCHING CAPTURED BMS DATA")

    all_records = []

    all_cinepolis_strings = set()

    for index, item in enumerate(captured, 1):

        event_code = ""

        url = item.get("url", "")

        for code in EVENT_CODES:

            if code in url:

                event_code = code
                break

        data = item.get("data")

        # ----------------------------------------------------
        # Find every Cinepolis occurrence.
        # ----------------------------------------------------

        matches = scan_json_for_cinepolis(
            data
        )

        print()
        print(
            f"Response {index}: "
            f"Cinepolis matches = {len(matches)}"
        )

        for match in matches:

            obj = match.get("object", {})

            for key, value in obj.items():

                if isinstance(value, str):

                    if is_cinepolis(value):

                        all_cinepolis_strings.add(
                            clean(value)
                        )

        # ----------------------------------------------------
        # Extract possible venue records.
        # ----------------------------------------------------

        records = extract_properties(
            data,
            event_code
        )

        all_records.extend(records)

        print(
            "Potential venue records:",
            len(records)
        )

    # ========================================================
    # PRINT CINEPOLIS STRINGS
    # ========================================================

    banner("CINEPOLIS TEXT FOUND")

    if all_cinepolis_strings:

        for value in sorted(
            all_cinepolis_strings
        ):

            print(value)

    else:

        print(
            "No Cinepolis text found in captured JSON."
        )

    # ========================================================
    # DEDUPLICATE VENUES
    # ========================================================

    unique = {}

    for record in all_records:

        name = clean(
            record.get("venue_name")
        )

        if not name:
            continue

        if not is_cinepolis(name):
            continue

        code = clean(
            record.get("venue_code")
        )

        key = (
            name.lower(),
            code
        )

        if key not in unique:

            unique[key] = record

    properties = list(
        unique.values()
    )

    # ========================================================
    # PRINT PROPERTIES
    # ========================================================

    banner(
        "CINEPOLIS PROPERTIES FOUND IN MUMBAI"
    )

    if not properties:

        print(
            "NO CINEPOLIS VENUE RECORDS FOUND."
        )

        print()
        print(
            "Raw BMS responses have been saved."
        )

        print(
            "File:",
            RAW_FILE
        )

        print()
        print(
            "Captured responses:",
            len(captured)
        )

    else:

        for index, record in enumerate(
            properties,
            1
        ):

            print()
            print(
                f"[{index}] "
                f"{record.get('venue_name', '')}"
            )

            print(
                "    Venue Code :",
                record.get(
                    "venue_code",
                    ""
                )
            )

            print(
                "    Address    :",
                record.get(
                    "address",
                    ""
                )
            )

            print(
                "    Event Code :",
                record.get(
                    "event_code",
                    ""
                )
            )

            print(
                "    Format     :",
                record.get(
                    "format",
                    ""
                )
            )

            print(
                "    Language   :",
                record.get(
                    "language",
                    ""
                )
            )

    # ========================================================
    # SAVE DISCOVERY RESULT
    # ========================================================

    output = {
        "timestamp": datetime.now().isoformat(),
        "movie": MOVIE,
        "city": CITY,
        "region": REGION_CODE,
        "date": DATE_CODE,
        "event_codes": EVENT_CODES,
        "captured_responses": len(captured),
        "cinepolis_strings": sorted(
            all_cinepolis_strings
        ),
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

    banner("DISCOVERY COMPLETED")

    print(
        "Cinepolis properties:",
        len(properties)
    )

    print(
        "Captured responses:",
        len(captured)
    )

    print(
        "Raw file:",
        RAW_FILE
    )

    print(
        "Discovery file:",
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()
