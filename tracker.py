import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"


# ---------------------------------------------------------
# TICKET PARSER
# ---------------------------------------------------------

def parse_tickets(raw_str):
    if raw_str is None:
        return 0

    text = str(raw_str).strip()

    # Examples:
    # 1.2K -> 1200
    # 2K -> 2000
    # 850 -> 850
    # 1.5M -> 1500000

    match = re.search(r"(\d+(?:\.\d+)?)\s*([KM]?)", text, re.IGNORECASE)

    if not match:
        return 0

    number = float(match.group(1))
    suffix = match.group(2).upper()

    if suffix == "K":
        number *= 1000
    elif suffix == "M":
        number *= 1000000

    return int(number)


# ---------------------------------------------------------
# SEARCH ANY JSON OBJECT RECURSIVELY
# ---------------------------------------------------------

def search_json_for_trending(obj, results=None, path=""):
    if results is None:
        results = []

    try:
        if isinstance(obj, dict):

            for key, value in obj.items():

                key_lower = str(key).lower()

                interesting_key = any(word in key_lower for word in [
                    "trending",
                    "velocity",
                    "recentbooking",
                    "bookingvelocity",
                    "ticketcount",
                    "bookingcount",
                    "recentbook",
                    "bought",
                    "booked",
                    "ticket"
                ])

                if interesting_key:
                    results.append({
                        "path": f"{path}.{key}",
                        "key": key,
                        "value": value
                    })

                search_json_for_trending(
                    value,
                    results,
                    f"{path}.{key}"
                )

        elif isinstance(obj, list):

            for index, value in enumerate(obj):
                search_json_for_trending(
                    value,
                    results,
                    f"{path}[{index}]"
                )

    except Exception:
        pass

    return results


# ---------------------------------------------------------
# EXTRACT TICKET NUMBER FROM TEXT
# ---------------------------------------------------------

def extract_ticket_number(text):
    if not text:
        return 0, ""

    text = str(text)

    patterns = [

        # 1.2K tickets bought
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?\s*(?:bought|booked)",

        # 1.2K tickets bought in the last hour
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?.{0,80}?(?:bought|booked)",

        # tickets bought: 1.2K
        r"tickets?\s*(?:bought|booked)\s*[:\-]?\s*(\d+(?:\.\d+)?\s*[KMkm]?)",

        # 1.2K booked
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*(?:bought|booked)",

        # 1.2K tickets
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?",

        # "count": 123
        r'"(?:count|ticketCount|bookingCount|recentBookings)"\s*:\s*(\d+)',

        # "value": "1.2K"
        r'"(?:value|label|text)"\s*:\s*"([^"]*(?:ticket|booked|bought)[^"]*)"',
    ]

    for pattern in patterns:

        try:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE | re.DOTALL
            )

            if match:

                candidate = match.group(1)

                number = parse_tickets(candidate)

                if number > 0:
                    return number, match.group(0)[:500]

        except Exception:
            continue

    return 0, ""


# ---------------------------------------------------------
# CHECK JSON FOR TRENDING NUMBER
# ---------------------------------------------------------

def extract_from_json(text, movie_code=None, movie_title=None):

    if not text:
        return 0, ""

    # First try direct text extraction
    tickets, raw = extract_ticket_number(text)

    if tickets > 0:
        return tickets, raw

    # Try parsing JSON
    try:
        data = json.loads(text)
    except Exception:
        return 0, ""

    # Search interesting fields
    matches = search_json_for_trending(data)

    for item in matches:

        value = item.get("value")

        if value is None:
            continue

        # Convert object/list/value to text
        try:
            value_text = json.dumps(
                value,
                ensure_ascii=False
            )
        except Exception:
            value_text = str(value)

        tickets, raw = extract_ticket_number(value_text)

        if tickets > 0:
            return tickets, raw

        # Sometimes value itself is just a number
        key = str(item.get("key", "")).lower()

        if any(x in key for x in [
            "ticketcount",
            "bookingcount",
            "recentbooking"
        ]):

            try:
                number = parse_tickets(value)

                if number > 0:
                    return number, f"{item['key']}: {value}"

            except Exception:
                pass

    return 0, ""


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def run():

    print("==========================================")
    print("BOOKMYSHOW TRENDING TRACKER")
    print("==========================================")

    # -----------------------------------------------------
    # GOOGLE SHEETS
    # -----------------------------------------------------

    print("\n1. Connecting to Google Sheets...")

    sa_info = json.loads(
        os.environ["GCP_SA_KEY"]
    )

    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets"
        ]
    )

    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    sheet = spreadsheet.get_worksheet(0)

    header = sheet.row_values(1)

    expected_header = [
        "Timestamp (IST)",
        "Movie Title",
        "Event Code",
        "Tickets Sold (Last 1 Hr)",
        "Raw Status Text",
        "Scope"
    ]

    if not header or header[0] != "Timestamp (IST)":

        sheet.insert_row(
            expected_header,
            1
        )

    # -----------------------------------------------------
    # TIME
    # -----------------------------------------------------

    now_utc = datetime.datetime.now(
        datetime.timezone.utc
    )

    now_ist = (
        now_utc +
        datetime.timedelta(
            hours=5,
            minutes=30
        )
    ).strftime("%Y-%m-%d %H:00:00")

    # -----------------------------------------------------
    # MOVIES
    # -----------------------------------------------------

    unique_movies = {}

    rows_to_append = []

    # All network responses captured
    network_responses = []

    # -----------------------------------------------------
    # PLAYWRIGHT
    # -----------------------------------------------------

    print("\n2. Starting browser session...")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )

        context = browser.new_context(

            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),

            viewport={
                "width": 1366,
                "height": 768
            },

            locale="en-IN",

            timezone_id="Asia/Kolkata"
        )

        page = context.new_page()

        # -------------------------------------------------
        # NETWORK RESPONSE CAPTURE
        # -------------------------------------------------

        def on_response(response):

            try:

                url = response.url.lower()

                content_type = (
                    response.headers
                    .get("content-type", "")
                    .lower()
                )

                interesting_url = any(
                    x in url
                    for x in [
                        "api",
                        "graphql",
                        "booking",
                        "ticket",
                        "trending",
                        "event",
                        "movie"
                    ]
                )

                interesting_type = (
                    "json" in content_type
                    or "graphql" in url
                )

                if not (
                    interesting_url
                    or interesting_type
                ):
                    return

                try:
                    text = response.text()
                except Exception:
                    return

                if not text:
                    return

                # Only retain responses that could realistically
                # contain the Trending information.
                lower_text = text.lower()

                if any(
                    x in lower_text
                    for x in [
                        "trending",
                        "bookingvelocity",
                        "recentbookings",
                        "ticketcount",
                        "bookingcount",
                        "tickets bought",
                        "tickets booked",
                        "velocity"
                    ]
                ):

                    network_responses.append({
                        "url": response.url,
                        "text": text
                    })

                    print(
                        "\n[NETWORK] Possible Trending response:"
                    )

                    print(
                        response.url
                    )

                    print(
                        text[:1000]
                    )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )

        # -------------------------------------------------
        # DISCOVER MOVIES
        # -------------------------------------------------

        print(
            "\n3. Discovering active movies..."
        )

        try:

            page.goto(
                "https://in.bookmyshow.com/explore/movies-mumbai",
                wait_until="domcontentloaded",
                timeout=30000
            )

            page.wait_for_timeout(
                5000
            )

            # Scroll several times because BMS is dynamic
            for _ in range(4):

                page.evaluate(
                    "window.scrollBy(0, 1500)"
                )

                page.wait_for_timeout(
                    1000
                )

            links = page.eval_on_selector_all(
                "a",
                """
                elements =>
                    elements
                    .map(el => el.getAttribute('href'))
                    .filter(Boolean)
                """
            )

            for href in links:

                match = re.search(
                    r"/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})",
                    href,
                    re.IGNORECASE
                )

                if not match:
                    continue

                slug = match.group(1)

                code = match.group(2)

                if code not in unique_movies:

                    unique_movies[code] = {

                        "title": (
                            slug
                            .replace("-", " ")
                            .title()
                        ),

                        "url": (
                            href
                            if href.startswith("http")
                            else
                            f"https://in.bookmyshow.com{href}"
                        ),

                        "code": code
                    }

        except Exception as e:

            print(
                f"Explore error: {e}"
            )

        print(
            f"\nFound {len(unique_movies)} active movies."
        )

        # -------------------------------------------------
        # MOVIE-BY-MOVIE EXTRACTION
        # -------------------------------------------------

        for index, (code, meta) in enumerate(
            unique_movies.items(),
            start=1
        ):

            print("\n------------------------------------------")
            print(
                f"{index}/{len(unique_movies)} "
                f"{meta['title']} "
                f"({code})"
            )
            print("------------------------------------------")

            tickets = 0

            raw_text = "No Trending Badge Found"

            # Clear old network responses
            network_responses.clear()

            try:

                # -----------------------------------------
                # OPEN MOVIE PAGE
                # -----------------------------------------

                page.goto(
                    meta["url"],
                    wait_until="domcontentloaded",
                    timeout=30000
                )

                # Give BMS JavaScript time to load
                page.wait_for_timeout(
                    6000
                )

                # Scroll page
                for _ in range(3):

                    page.evaluate(
                        "window.scrollBy(0, 1200)"
                    )

                    page.wait_for_timeout(
                        1000
                    )

                # -----------------------------------------
                # METHOD 1
                # NETWORK RESPONSES
                # -----------------------------------------

                print(
                    "Checking network/API data..."
                )

                for response_data in network_responses:

                    response_url = response_data["url"]

                    response_text = response_data["text"]

                    # Check whether this response is
                    # related to current movie
                    related = (
                        code.lower()
                        in response_text.lower()
                        or
                        code.lower()
                        in response_url.lower()
                        or
                        meta["title"].lower()
                        in response_text.lower()
                    )

                    if not related:
                        continue

                    found, raw = extract_from_json(
                        response_text,
                        code,
                        meta["title"]
                    )

                    if found > 0:

                        tickets = found

                        raw_text = raw

                        print(
                            f"FOUND FROM NETWORK: "
                            f"{tickets}"
                        )

                        print(
                            f"RAW: {raw_text}"
                        )

                        break

                # -----------------------------------------
                # METHOD 2
                # VISIBLE DOM
                # -----------------------------------------

                if tickets == 0:

                    print(
                        "Checking visible page text..."
                    )

                    body_text = page.locator(
                        "body"
                    ).inner_text(
                        timeout=10000
                    )

                    found, raw = extract_ticket_number(
                        body_text
                    )

                    if found > 0:

                        tickets = found

                        raw_text = raw

                        print(
                            f"FOUND FROM DOM: "
                            f"{tickets}"
                        )

                # -----------------------------------------
                # METHOD 3
                # SEARCH ALL ELEMENTS
                # -----------------------------------------

                if tickets == 0:

                    print(
                        "Checking individual elements..."
                    )

                    elements = page.locator(
                        "span, div, p, section"
                    )

                    count = min(
                        elements.count(),
                        5000
                    )

                    for i in range(count):

                        try:

                            text = elements.nth(
                                i
                            ).inner_text(
                                timeout=1000
                            )

                        except Exception:

                            continue

                        if not text:
                            continue

                        lower = text.lower()

                        if any(
                            x in lower
                            for x in [
                                "bought",
                                "booked",
                                "trending",
                                "ticket"
                            ]
                        ):

                            found, raw = (
                                extract_ticket_number(
                                    text
                                )
                            )

                            if found > 0:

                                tickets = found

                                raw_text = text[:500]

                                print(
                                    f"FOUND FROM ELEMENT: "
                                    f"{tickets}"
                                )

                                print(
                                    f"TEXT: "
                                    f"{raw_text}"
                                )

                                break

                # -----------------------------------------
                # METHOD 4
                # PAGE HTML
                # -----------------------------------------

                if tickets == 0:

                    print(
                        "Checking page HTML..."
                    )

                    content = page.content()

                    found, raw = (
                        extract_ticket_number(
                            content
                        )
                    )

                    if found > 0:

                        tickets = found

                        raw_text = raw

                        print(
                            f"FOUND FROM HTML: "
                            f"{tickets}"
                        )

                # -----------------------------------------
                # METHOD 5
                # NEXT.JS / EMBEDDED JSON
                # -----------------------------------------

                if tickets == 0:

                    print(
                        "Checking embedded JSON..."
                    )

                    scripts = page.locator(
                        "script"
                    )

                    script_count = scripts.count()

                    for i in range(
                        min(script_count, 500)
                    ):

                        try:

                            script_text = (
                                scripts
                                .nth(i)
                                .inner_text(
                                    timeout=1000
                                )
                            )

                        except Exception:

                            continue

                        if not script_text:
                            continue

                        lower = script_text.lower()

                        if not any(
                            x in lower
                            for x in [
                                "trending",
                                "ticket",
                                "booking",
                                "velocity"
                            ]
                        ):
                            continue

                        found, raw = (
                            extract_from_json(
                                script_text,
                                code,
                                meta["title"]
                            )
                        )

                        if found > 0:

                            tickets = found

                            raw_text = raw

                            print(
                                f"FOUND FROM EMBEDDED JSON: "
                                f"{tickets}"
                            )

                            break

            except Exception as e:

                print(
                    f"Error checking "
                    f"{meta['title']}: {e}"
                )

            # ---------------------------------------------
            # FINAL RESULT
            # ---------------------------------------------

            if tickets == 0:

                print(
                    "TRENDING: NOT FOUND"
                )

            else:

                print(
                    f"TRENDING: {tickets} tickets"
                )

            rows_to_append.append(
                [
                    now_ist,
                    meta["title"],
                    code,
                    tickets,
                    raw_text,
                    "All India"
                ]
            )

        browser.close()

    # -----------------------------------------------------
    # GOOGLE SHEETS
    # -----------------------------------------------------

    if rows_to_append:

        print(
            f"\n4. Pushing "
            f"{len(rows_to_append)} rows "
            f"to Google Sheets..."
        )

        sheet.append_rows(
            rows_to_append,
            value_input_option="USER_ENTERED"
        )

        print(
            "\nDONE!"
        )

        print(
            "Data successfully written "
            "to Google Sheets."
        )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == "__main__":
    run()
