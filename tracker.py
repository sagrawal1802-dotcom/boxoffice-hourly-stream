import json
import re
import time
from playwright.sync_api import sync_playwright


CITY = "mumbai"
REGION_CODE = "MUMBAI"
DATE_CODE = "20260826"

EVENT_CODES = [
    "ET00379311",
    "ET00513458",
    "ET00513506",
]

API_URL = (
    "https://in.bookmyshow.com/api/movies-data/"
    "v5/showtimes-by-event/primary-dynamic"
)


def header(title):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def find_strings(obj, keyword="cinepolis"):
    """
    Recursively search a JSON object and return dictionaries
    containing the requested keyword somewhere in their values.
    """
    results = []

    if isinstance(obj, dict):
        text = json.dumps(
            obj,
            ensure_ascii=False
        ).lower()

        if keyword.lower() in text:
            results.append(obj)

        for value in obj.values():
            results.extend(
                find_strings(value, keyword)
            )

    elif isinstance(obj, list):
        for item in obj:
            results.extend(
                find_strings(item, keyword)
            )

    return results


def extract_possible_venue_info(obj):
    """
    Recursively inspect dictionaries for venue/cinema fields.
    """
    found = []

    if isinstance(obj, dict):

        keys_lower = {
            str(k).lower(): k
            for k in obj.keys()
        }

        name = None
        venue_code = None
        city = None

        name_keys = [
            "venuename",
            "venue_name",
            "cinemaname",
            "cinema_name",
            "name",
            "displayname",
            "display_name",
        ]

        code_keys = [
            "venuecode",
            "venue_code",
            "cinemacode",
            "cinema_code",
        ]

        city_keys = [
            "city",
            "cityname",
            "city_name",
        ]

        for key in name_keys:
            if key in keys_lower:
                value = obj.get(keys_lower[key])

                if isinstance(value, str):
                    name = clean(value)

                    if name:
                        break

        for key in code_keys:
            if key in keys_lower:
                value = obj.get(keys_lower[key])

                if isinstance(value, (str, int)):
                    venue_code = str(value).strip()

                    if venue_code:
                        break

        for key in city_keys:
            if key in keys_lower:
                value = obj.get(keys_lower[key])

                if isinstance(value, str):
                    city = clean(value)

                    if city:
                        break

        if name and "cinepolis" in name.lower():

            found.append({
                "venue_name": name,
                "venue_code": venue_code or "",
                "city": city or "",
            })

        for value in obj.values():
            found.extend(
                extract_possible_venue_info(value)
            )

    elif isinstance(obj, list):

        for item in obj:
            found.extend(
                extract_possible_venue_info(item)
            )

    return found


def main():

    header(
        "BMS TOXIC - MUMBAI CINEPOLIS PROPERTY DISCOVERY"
    )

    print("City       :", CITY)
    print("Region     :", REGION_CODE)
    print("Date       :", DATE_CODE)
    print("Event codes:", ", ".join(EVENT_CODES))
    print("Mode       : DISCOVERY ONLY")
    print()
    print("NO GOOGLE SHEETS")
    print("NO SEAT API")
    print("NO SEAT PARSING")

    all_venues = {}

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 768,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # First open BMS to establish browser context/cookies.
        try:

            print()
            print("Opening BMS...")

            response = page.goto(
                "https://in.bookmyshow.com/",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print(
                    "BMS homepage status:",
                    response.status
                )

        except Exception as e:

            print(
                "BMS homepage navigation warning:",
                e
            )

        page.wait_for_timeout(3000)

        for event_code in EVENT_CODES:

            header(
                f"REQUESTING SHOWTIME DATA - {event_code}"
            )

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

            response_data = None

            for attempt in range(1, 4):

                print(
                    f"Attempt {attempt}/3"
                )

                try:

                    result = page.request.get(
                        API_URL,
                        params=params,
                        headers={
                            "accept": "application/json, text/plain, */*",
                            "referer": (
                                "https://in.bookmyshow.com/"
                            ),
                            "origin": (
                                "https://in.bookmyshow.com"
                            ),
                        },
                        timeout=60000,
                    )

                    print(
                        "HTTP status:",
                        result.status
                    )

                    body = result.text()

                    print(
                        "Response size:",
                        len(body)
                    )

                    if result.status == 200:

                        try:

                            response_data = json.loads(
                                body
                            )

                            print(
                                "JSON successfully decoded."
                            )

                            break

                        except Exception as e:

                            print(
                                "JSON decode error:",
                                e
                            )

                    else:

                        print(
                            "Response preview:",
                            body[:200].replace(
                                "\n",
                                " "
                            )
                        )

                except Exception as e:

                    print(
                        "Request error:",
                        e
                    )

                if attempt < 3:
                    time.sleep(2)

            if response_data is None:

                print(
                    "NO SHOWTIME DATA FOR",
                    event_code
                )

                continue

            # ----------------------------------------------------
            # Search specifically for Cinepolis
            # ----------------------------------------------------

            cinepolis_blocks = find_strings(
                response_data,
                "cinepolis"
            )

            print(
                "JSON blocks containing Cinepolis:",
                len(cinepolis_blocks)
            )

            # ----------------------------------------------------
            # Recursively extract venue information
            # ----------------------------------------------------

            venues = extract_possible_venue_info(
                response_data
            )

            print(
                "Possible Cinepolis venue records:",
                len(venues)
            )

            for venue in venues:

                name = clean(
                    venue.get("venue_name")
                )

                code = clean(
                    venue.get("venue_code")
                )

                city = clean(
                    venue.get("city")
                )

                if not name:
                    continue

                key = (
                    name.lower(),
                    code.upper(),
                )

                if key not in all_venues:

                    all_venues[key] = {
                        "venue_name": name,
                        "venue_code": code,
                        "city": city,
                        "event_codes": [event_code],
                    }

                else:

                    existing = all_venues[key]

                    if event_code not in existing[
                        "event_codes"
                    ]:
                        existing[
                            "event_codes"
                        ].append(event_code)

            # ----------------------------------------------------
            # Print raw Cinepolis-containing blocks for debugging
            # ----------------------------------------------------

            if cinepolis_blocks:

                print()
                print(
                    "CINEPOLIS REFERENCES FOUND"
                )

                for i, block in enumerate(
                    cinepolis_blocks[:10],
                    start=1
                ):

                    try:

                        text = json.dumps(
                            block,
                            ensure_ascii=False
                        )

                        print(
                            f"\n--- Block {i} ---"
                        )

                        print(
                            text[:3000]
                        )

                    except Exception:
                        pass

        browser.close()

    # ============================================================
    # FINAL RESULT
    # ============================================================

    header(
        "CINEPOLIS PROPERTIES FOUND IN MUMBAI"
    )

    if not all_venues:

        print(
            "NO CINEPOLIS VENUE RECORDS WERE EXTRACTED."
        )

        print()
        print(
            "This means the JSON structure needs to be inspected "
            "before building the show scraper."
        )

    else:

        sorted_venues = sorted(
            all_venues.values(),
            key=lambda x: (
                x["venue_name"].lower(),
                x["venue_code"].lower(),
            ),
        )

        for index, venue in enumerate(
            sorted_venues,
            start=1
        ):

            print(
                f"\n{index}. {venue['venue_name']}"
            )

            print(
                "   Venue Code :",
                venue["venue_code"] or "(not found)"
            )

            print(
                "   City       :",
                venue["city"] or "(not found)"
            )

            print(
                "   Event Codes:",
                ", ".join(
                    venue["event_codes"]
                )
            )

        print()
        print(
            "TOTAL CINEPOLIS PROPERTIES:",
            len(sorted_venues)
        )

        with open(
            "cinepolis_mumbai_venues.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                sorted_venues,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print(
            "Saved: cinepolis_mumbai_venues.json"
        )

    header(
        "CINEPOLIS DISCOVERY RUN COMPLETED"
    )


if __name__ == "__main__":
    main()
