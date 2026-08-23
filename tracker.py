import json
import time
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

MOVIE_SLUG = "toxic-a-fairy-tale-for-grown-ups"

CITY = "mumbai"
REGION_CODE = "MUMBAI"
SHOW_DATE = "20260826"

EVENT_CODES = [
    "ET00379311",
    "ET00513458",
    "ET00513506",
]

OUTPUT_FILE = "cinepolis_mumbai_properties.json"
RAW_FILE = "bms_primary_dynamic_responses.json"

PAGE_TIMEOUT = 60000


# ============================================================
# BANNER
# ============================================================

def banner(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


# ============================================================
# BUILD BMS BUY TICKETS URL
# ============================================================

def build_url(event_code):

    params = {
        "etCodes": "*",
        "language": "hindi",
        "refEventCode": event_code,
    }

    return (
        f"https://in.bookmyshow.com/movies/"
        f"{CITY}/{MOVIE_SLUG}/buytickets/"
        f"{event_code}/{SHOW_DATE}"
        f"?{urlencode(params)}"
    )


# ============================================================
# RECURSIVE VENUE PARSER
# ============================================================

def extract_venue_cards(obj, results):

    if isinstance(obj, dict):

        if obj.get("type") == "venue-card":

            additional = obj.get("additionalData", {})

            venue_code = additional.get("venueCode")
            venue_name = additional.get("venueName")

            if venue_code and venue_name:

                if "cinepolis" in venue_name.lower():

                    results.append({
                        "venue_code": venue_code,
                        "venue_name": venue_name,
                        "raw": obj,
                    })

        for value in obj.values():
            extract_venue_cards(value, results)

    elif isinstance(obj, list):

        for value in obj:
            extract_venue_cards(value, results)


# ============================================================
# EXTRACT SHOWTIMES
# ============================================================

def extract_showtimes(venue_obj):

    shows = []

    data = venue_obj.get("data", {})

    sections = data.get("showtimesSections", [])

    for section in sections:

        section_name = ""

        try:
            section_name = (
                section
                .get("text", [{}])[0]
                .get("components", [{}])[0]
                .get("text", "")
            )
        except Exception:
            section_name = ""

        for show in section.get("showtimes", []):

            title = show.get("title")

            additional = show.get(
                "additionalData",
                {}
            )

            session_id = additional.get("sessionId")

            show_date = additional.get(
                "showDateCode"
            )

            show_datetime = additional.get(
                "showDateTime"
            )

            if title and session_id:

                shows.append({
                    "format": section_name,
                    "show_time": title,
                    "session_id": str(session_id),
                    "show_date": show_date,
                    "show_date_time": show_datetime,
                })

    return shows


# ============================================================
# MAIN
# ============================================================

def main():

    banner(
        "BMS TOXIC - LIVE PRIMARY-DYNAMIC CINEPOLIS DISCOVERY"
    )

    print()
    print("Movie :", MOVIE_SLUG)
    print("City  :", CITY)
    print("Region:", REGION_CODE)
    print("Date  :", SHOW_DATE)

    print()
    print("Event codes:")

    for event in EVENT_CODES:
        print(" ", event)

    print()
    print("IMPORTANT:")
    print("This version does NOT use a HAR file.")
    print("It does NOT directly call the BMS API.")
    print("The browser generates the BMS request.")
    print("Python captures the browser response.")
    print("No Google Sheets.")
    print("No seat API.")
    print("No YAML changes.")
    print()

    captured_responses = []

    with sync_playwright() as p:

        banner("LAUNCHING CHROMIUM")

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1536,
                "height": 864,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",

            # Important:
            # Block the service worker so Playwright can
            # observe the underlying network response.
            service_workers="block",

        )

        page = context.new_page()

        # --------------------------------------------------------
        # RESPONSE LISTENER
        # --------------------------------------------------------

        def handle_response(response):

            url = response.url

            if (
                "/api/movies-data/v5/"
                "showtimes-by-event/"
                "primary-dynamic"
                not in url
            ):
                return

            print()
            print("-" * 100)
            print("[PRIMARY-DYNAMIC RESPONSE]")
            print("Status :", response.status)
            print("URL    :", url)

            try:

                body = response.text()

                print(
                    "Size   :",
                    len(body)
                )

                if not body:
                    print(
                        "WARNING: Empty response body"
                    )
                    return

                captured_responses.append({
                    "url": url,
                    "status": response.status,
                    "body": body,
                })

                print(
                    "Captured successfully."
                )

            except Exception as e:

                print(
                    "Could not read response body:",
                    e
                )

            print("-" * 100)

        page.on(
            "response",
            handle_response
        )

        # --------------------------------------------------------
        # OPEN EACH EVENT
        # --------------------------------------------------------

        for event_code in EVENT_CODES:

            banner(
                f"OPENING BMS BUYTICKETS PAGE - {event_code}"
            )

            url = build_url(event_code)

            print()
            print("URL:")
            print(url)

            try:

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT,
                )

                if response:

                    print()
                    print(
                        "Initial page status:",
                        response.status
                    )

                print(
                    "Current URL:",
                    page.url
                )

            except Exception as e:

                print()
                print(
                    "Page navigation warning:",
                    e
                )

            print()
            print(
                "Waiting for BMS JavaScript..."
            )

            time.sleep(8)

            # ----------------------------------------------------
            # SCROLL
            # ----------------------------------------------------

            for i in range(12):

                try:

                    page.evaluate(
                        "window.scrollBy(0, 700)"
                    )

                except Exception:
                    pass

                time.sleep(0.5)

                print(
                    f"Scroll {i + 1}/12"
                )

            print()
            print(
                "Waiting for delayed BMS responses..."
            )

            time.sleep(5)

        # --------------------------------------------------------
        # FINAL WAIT
        # --------------------------------------------------------

        time.sleep(5)

        browser.close()

    # ============================================================
    # RESPONSE SUMMARY
    # ============================================================

    banner(
        "PRIMARY-DYNAMIC CAPTURE SUMMARY"
    )

    print(
        "Responses captured:",
        len(captured_responses)
    )

    if not captured_responses:

        print()
        print(
            "NO PRIMARY-DYNAMIC RESPONSE WAS CAPTURED."
        )

        print()
        print(
            "This means BMS did not expose the response"
        )
        print(
            "to the Playwright response listener."
        )

        print()
        print(
            "DO NOT change YAML."
        )

        return

    # ============================================================
    # SAVE RAW RESPONSES
    # ============================================================

    raw_output = []

    for item in captured_responses:

        raw_output.append({
            "url": item["url"],
            "status": item["status"],
            "body": item["body"],
        })

    with open(
        RAW_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            raw_output,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(
        "Raw responses saved:",
        RAW_FILE
    )

    # ============================================================
    # PARSE CINEPOLIS VENUES
    # ============================================================

    banner(
        "PARSING CINEPOLIS VENUE-CARD OBJECTS"
    )

    all_venues = []

    for index, item in enumerate(
        captured_responses,
        start=1
    ):

        print()
        print(
            f"Parsing response {index}"
        )

        try:

            data = json.loads(
                item["body"]
            )

        except Exception as e:

            print(
                "JSON parse failed:",
                e
            )

            continue

        found = []

        extract_venue_cards(
            data,
            found
        )

        print(
            "Cinepolis venue cards:",
            len(found)
        )

        for venue in found:

            venue_code = venue[
                "venue_code"
            ]

            venue_name = venue[
                "venue_name"
            ]

            shows = extract_showtimes(
                venue["raw"]
            )

            clean = {
                "venue_code": venue_code,
                "venue_name": venue_name,
                "shows": shows,
                "source_url": item["url"],
            }

            all_venues.append(
                clean
            )

    # ============================================================
    # DEDUPLICATE
    # ============================================================

    unique = {}

    for venue in all_venues:

        code = venue[
            "venue_code"
        ]

        if code not in unique:

            unique[code] = venue

        else:

            # Merge shows from duplicate responses
            existing = unique[code]

            existing_keys = {
                (
                    s.get("format"),
                    s.get("show_time"),
                    s.get("session_id"),
                )
                for s in existing["shows"]
            }

            for show in venue["shows"]:

                key = (
                    show.get("format"),
                    show.get("show_time"),
                    show.get("session_id"),
                )

                if key not in existing_keys:

                    existing["shows"].append(
                        show
                    )

    venues = list(
        unique.values()
    )

    # ============================================================
    # PRINT VENUES
    # ============================================================

    banner(
        "FINAL CINEPOLIS VENUES"
    )

    if not venues:

        print()
        print(
            "NO CINEPOLIS VENUES FOUND."
        )

    else:

        for i, venue in enumerate(
            venues,
            start=1
        ):

            print()
            print(
                f"{i}. {venue['venue_name']}"
            )

            print(
                "   Code :",
                venue["venue_code"]
            )

            print(
                "   Shows:",
                len(venue["shows"])
            )

            for show in sorted(
                venue["shows"],
                key=lambda x: (
                    x.get("format", ""),
                    x.get("show_time", ""),
                )
            ):

                print(
                    "      ",
                    f"{show.get('format', ''):<12}",
                    "|",
                    f"{show.get('show_time', ''):<9}",
                    "| Session",
                    show.get(
                        "session_id"
                    )
                )

    # ============================================================
    # SAVE CLEAN OUTPUT
    # ============================================================

    output = {
        "movie": (
            "Toxic: A Fairy Tale for Grown-ups"
        ),
        "event_codes": EVENT_CODES,
        "city": CITY,
        "region": REGION_CODE,
        "date": SHOW_DATE,
        "source": (
            "Live BMS browser "
            "primary-dynamic response"
        ),
        "venues": venues,
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
            ensure_ascii=False,
        )

    # ============================================================
    # FINAL SUMMARY
    # ============================================================

    banner(
        "DISCOVERY COMPLETED"
    )

    print()
    print(
        "Cinepolis properties:",
        len(venues)
    )

    print(
        "Raw response file:",
        RAW_FILE
    )

    print(
        "Clean discovery file:",
        OUTPUT_FILE
    )

    print()
    print(
        "No HAR file was required."
    )

    print(
        "No YAML was changed."
    )

    print(
        "No Google Sheets were accessed."
    )

    print(
        "No seat API was called."
    )


if __name__ == "__main__":
    main()
