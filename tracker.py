import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

CITY = "mumbai"
REGION = "MUMBAI"
SHOW_DATE = "20260826"

EVENT_CODES = [
    "ET00379311",
    "ET00513458",
    "ET00513506",
]

MOVIE_URL = (
    "https://in.bookmyshow.com/movies/"
    "mumbai/toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

OUTPUT_FILE = "cinepolis_mumbai_properties.json"

BMS_DOMAIN = "https://in.bookmyshow.com"

PRIMARY_DYNAMIC = "/api/movies-data/v5/showtimes-by-event/primary-dynamic"


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    if not isinstance(value, str):
        return str(value)

    return re.sub(r"\s+", " ", value).strip()


def is_cinepolis(value):
    if not isinstance(value, str):
        return False

    return "cinepolis" in value.lower()


def extract_code_from_url(url):
    if not url:
        return ""

    # Examples:
    # .../CPVV
    # .../CSWO
    # .../CPVM

    match = re.search(r"/([A-Z0-9]{3,8})(?:[/?#]|$)", url)

    if match:
        return match.group(1)

    return ""


def normalize_url(url):
    if not url:
        return ""

    url = clean_text(url)

    if url.startswith("/"):
        return urljoin(BMS_DOMAIN, url)

    return url


# ============================================================
# RECURSIVE JSON SEARCH
# ============================================================

def recursively_find_cinepolis(obj, results, path="root"):
    """
    Search the complete BMS response recursively.

    We specifically look for objects containing:
        venueName
        redirectionUrl
        href
        cinema / venue identifiers

    We do NOT assume a fixed JSON depth.
    """

    if isinstance(obj, dict):

        venue_name = ""

        # ----------------------------------------------------
        # Possible venue-name fields
        # ----------------------------------------------------

        for key in [
            "venueName",
            "cinemaName",
            "theatreName",
            "theaterName",
            "name",
        ]:
            value = obj.get(key)

            if isinstance(value, str) and is_cinepolis(value):
                venue_name = clean_text(value)
                break

        # ----------------------------------------------------
        # If this object itself represents Cinepolis
        # ----------------------------------------------------

        if venue_name:

            possible_urls = []

            for key in [
                "redirectionUrl",
                "redirectUrl",
                "url",
                "href",
                "cinemaUrl",
                "venueUrl",
                "webUrl",
            ]:
                value = obj.get(key)

                if isinstance(value, str) and value:
                    possible_urls.append(value)

            # Search the object values for a BMS cinema URL
            for value in obj.values():

                if isinstance(value, str):

                    if (
                        "bookmyshow.com/cinemas/" in value
                        or "/cinemas/" in value
                    ):
                        possible_urls.append(value)

            venue_url = ""

            for candidate in possible_urls:

                candidate = normalize_url(candidate)

                if "/cinemas/" in candidate:
                    venue_url = candidate
                    break

            # ------------------------------------------------
            # Find BMS cinema code
            # ------------------------------------------------

            venue_code = ""

            # Direct fields first
            for key in [
                "venueCode",
                "cinemaCode",
                "theatreCode",
                "theaterCode",
                "code",
                "cinemaId",
                "venueId",
            ]:

                value = obj.get(key)

                if value is not None:

                    value = clean_text(value)

                    if value:
                        venue_code = value
                        break

            # Try URL if code not directly available
            if not venue_code:
                venue_code = extract_code_from_url(venue_url)

            # ------------------------------------------------
            # Store
            # ------------------------------------------------

            results.append(
                {
                    "venue_name": venue_name,
                    "venue_code": venue_code,
                    "url": venue_url,
                    "json_path": path,
                }
            )

        # ----------------------------------------------------
        # Continue recursively
        # ----------------------------------------------------

        for key, value in obj.items():

            recursively_find_cinepolis(
                value,
                results,
                f"{path}.{key}"
            )

    elif isinstance(obj, list):

        for index, value in enumerate(obj):

            recursively_find_cinepolis(
                value,
                results,
                f"{path}[{index}]"
            )


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_properties(properties):

    unique = {}

    for item in properties:

        name = clean_text(item.get("venue_name"))
        code = clean_text(item.get("venue_code"))
        url = clean_text(item.get("url"))

        if not name:
            continue

        # Prefer code as primary key
        if code:
            key = f"CODE:{code.upper()}"

        elif url:
            key = f"URL:{url.lower()}"

        else:
            key = f"NAME:{name.lower()}"

        # Keep the most complete version
        if key not in unique:

            unique[key] = {
                "venue_name": name,
                "venue_code": code,
                "url": url,
            }

        else:

            existing = unique[key]

            if not existing["venue_code"] and code:
                existing["venue_code"] = code

            if not existing["url"] and url:
                existing["url"] = url

    return list(unique.values())


# ============================================================
# PARSE RESPONSE
# ============================================================

def parse_response_body(body, source_url):

    found = []

    if not body:
        return found

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    try:

        data = json.loads(body)

        recursively_find_cinepolis(
            data,
            found,
            "response"
        )

        if found:
            return found

    except Exception:
        pass

    # --------------------------------------------------------
    # Sometimes BMS embeds JSON/stringified JSON
    # --------------------------------------------------------

    try:

        text = body

        # Search for venueName around Cinepolis
        pattern = re.compile(
            r'"venueName"\s*:\s*"([^"]*cinepolis[^"]*)"',
            re.IGNORECASE
        )

        for match in pattern.finditer(text):

            venue_name = clean_text(match.group(1))

            start = max(0, match.start() - 3000)
            end = min(len(text), match.end() + 5000)

            surrounding = text[start:end]

            url_match = re.search(
                r'https?://in\.bookmyshow\.com/cinemas/[^"\\]+',
                surrounding,
                re.IGNORECASE
            )

            venue_url = ""

            if url_match:
                venue_url = url_match.group(0)

            code = extract_code_from_url(venue_url)

            found.append(
                {
                    "venue_name": venue_name,
                    "venue_code": code,
                    "url": venue_url,
                    "json_path": "text-search",
                }
            )

    except Exception:
        pass

    return found


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 100)
    print("BMS TOXIC - MUMBAI CINEPOLIS PROPERTY DISCOVERY")
    print("=" * 100)

    print()
    print("Movie URL :", MOVIE_URL)
    print("City      :", CITY)
    print("Region    :", REGION)
    print("Date      :", SHOW_DATE)

    print()
    print("Event codes:")
    for code in EVENT_CODES:
        print(" ", code)

    print()
    print("THIS VERSION:")
    print(" - Uses Playwright browser session")
    print(" - Captures BMS network responses")
    print(" - Parses actual BMS JSON recursively")
    print(" - Searches venueName for Cinepolis")
    print(" - Does NOT call the seat API")
    print(" - Does NOT access Google Sheets")
    print(" - Does NOT modify the existing tracker")
    print(" - Does NOT change YAML")

    print()
    print("=" * 100)
    print("LAUNCHING CHROMIUM")
    print("=" * 100)

    captured_responses = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Network response handler
        # ----------------------------------------------------

        def handle_response(response):

            try:

                url = response.url

                # We are primarily interested in BMS responses
                if "bookmyshow.com" not in url:
                    return

                request = response.request

                resource_type = request.resource_type

                # Primary dynamic is the important endpoint
                interesting = (
                    PRIMARY_DYNAMIC in url
                    or "/api/movies-data/" in url
                    or "/showtimes" in url
                )

                if not interesting:
                    return

                print()
                print("[BMS RESPONSE]")
                print("Status :", response.status)
                print("Type   :", resource_type)
                print("URL    :", url)

                try:

                    body = response.body()

                    print(
                        "Size   :",
                        len(body),
                        "bytes"
                    )

                    captured_responses.append(
                        {
                            "url": url,
                            "status": response.status,
                            "resource_type": resource_type,
                            "body": body,
                        }
                    )

                except Exception as error:

                    print(
                        "Could not read response:",
                        repr(error)
                    )

            except Exception as error:

                print(
                    "Response handler error:",
                    repr(error)
                )

        page.on(
            "response",
            handle_response
        )

        # ----------------------------------------------------
        # Open movie page
        # ----------------------------------------------------

        print()
        print("=" * 100)
        print("OPENING TOXIC MUMBAI PAGE")
        print("=" * 100)

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

        except Exception as error:

            print(
                "Page open warning:",
                repr(error)
            )

        print()
        print("Waiting for BMS JavaScript...")

        page.wait_for_timeout(8000)

        # ----------------------------------------------------
        # Scroll
        # ----------------------------------------------------

        print()
        print("=" * 100)
        print("SCROLLING BMS PAGE")
        print("=" * 100)

        for i in range(12):

            try:

                page.evaluate(
                    """
                    () => {
                        window.scrollBy(
                            0,
                            Math.max(
                                600,
                                window.innerHeight * 0.85
                            )
                        );
                    }
                    """
                )

            except Exception:
                pass

            page.wait_for_timeout(1000)

            print(
                f"Scroll {i + 1}/12"
            )

        # ----------------------------------------------------
        # Go back to top
        # ----------------------------------------------------

        try:

            page.evaluate(
                "() => window.scrollTo(0, 0)"
            )

        except Exception:
            pass

        page.wait_for_timeout(3000)

        # ----------------------------------------------------
        # Additional wait for delayed requests
        # ----------------------------------------------------

        print()
        print(
            "Waiting for delayed BMS responses..."
        )

        page.wait_for_timeout(10000)

        # ----------------------------------------------------
        # Capture page HTML too
        # ----------------------------------------------------

        try:

            html = page.content()

            print()
            print(
                "Page HTML size:",
                len(html)
            )

            # Search HTML directly as fallback
            html_results = parse_response_body(
                html,
                page.url
            )

            if html_results:

                print()
                print(
                    "Cinepolis references found in HTML:",
                    len(html_results)
                )

                for item in html_results:
                    print(
                        " ",
                        item["venue_name"],
                        "|",
                        item["venue_code"],
                        "|",
                        item["url"]
                    )

                captured_responses.append(
                    {
                        "url": page.url,
                        "status": 200,
                        "resource_type": "document-html",
                        "body": html.encode("utf-8"),
                    }
                )

        except Exception as error:

            print(
                "HTML extraction warning:",
                repr(error)
            )

        browser.close()

    # ========================================================
    # PARSE ALL CAPTURED RESPONSES
    # ========================================================

    print()
    print("=" * 100)
    print("PARSING CAPTURED BMS RESPONSES")
    print("=" * 100)

    all_properties = []

    print()
    print(
        "Relevant BMS responses captured:",
        len(captured_responses)
    )

    for index, item in enumerate(
        captured_responses,
        start=1
    ):

        print()
        print(
            f"Response {index}/{len(captured_responses)}"
        )

        print(
            "Status:",
            item["status"]
        )

        print(
            "URL:",
            item["url"]
        )

        body = item["body"]

        if isinstance(body, bytes):

            try:
                body = body.decode(
                    "utf-8",
                    errors="ignore"
                )
            except Exception:
                body = ""

        results = parse_response_body(
            body,
            item["url"]
        )

        print(
            "Cinepolis matches:",
            len(results)
        )

        all_properties.extend(results)

    # ========================================================
    # DEDUPLICATE
    # ========================================================

    properties = deduplicate_properties(
        all_properties
    )

    # Sort alphabetically
    properties.sort(
        key=lambda x: x["venue_name"].lower()
    )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print()
    print("=" * 100)
    print("FINAL CINEPOLIS PROPERTY LIST")
    print("=" * 100)

    if not properties:

        print()
        print(
            "NO CINEPOLIS PROPERTIES FOUND."
        )

    else:

        for index, property_data in enumerate(
            properties,
            start=1
        ):

            print()
            print(
                f"{index}. "
                f"{property_data['venue_name']}"
            )

            print(
                "   BMS Code:",
                property_data["venue_code"]
                or "NOT FOUND"
            )

            print(
                "   URL:",
                property_data["url"]
                or "NOT FOUND"
            )

    # ========================================================
    # SAVE JSON
    # ========================================================

    output = {
        "movie": "Toxic: A Fairy Tale for Grown-ups",
        "city": CITY,
        "region": REGION,
        "date": SHOW_DATE,
        "event_codes": EVENT_CODES,
        "source": MOVIE_URL,
        "property_count": len(properties),
        "properties": properties,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 100)
    print("DISCOVERY COMPLETED")
    print("=" * 100)

    print()
    print(
        "Cinepolis properties found:",
        len(properties)
    )

    print(
        "Saved:",
        OUTPUT_FILE
    )

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "This is still discovery only."
    )

    print(
        "No seat requests were made."
    )

    print(
        "No Google Sheets changes were made."
    )

    print(
        "No existing tracker logic was changed."
    )


if __name__ == "__main__":
    main()
