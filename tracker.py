import os
import json
import re
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

DEBUG_FILE = "bms_api_debug.txt"


# =========================================================
# DEBUG LOGGER
# =========================================================

def debug_write(text):

    print(text)

    try:
        with open(
            DEBUG_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                str(text) + "\n"
            )

    except Exception:
        pass


# =========================================================
# TICKET PARSER
# =========================================================

def parse_tickets(value):

    if value is None:
        return 0

    text = str(value).strip()

    # Remove commas
    text = text.replace(",", "")

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*([KM]?)",
        text,
        re.IGNORECASE
    )

    if not match:
        return 0

    number = float(
        match.group(1)
    )

    suffix = match.group(2).upper()

    if suffix == "K":
        number *= 1000

    elif suffix == "M":
        number *= 1000000

    return int(number)


# =========================================================
# EXTRACT TICKETS FROM TEXT
# =========================================================

def extract_ticket_number(text):

    if not text:
        return 0, ""

    text = str(text)

    patterns = [

        # 1.2K tickets bought
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?\s*(?:bought|booked)",

        # 1.2K tickets booked in the last hour
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?.{0,100}?(?:bought|booked)",

        # tickets bought: 1.2K
        r"tickets?\s*(?:bought|booked)\s*[:\-]?\s*(\d+(?:\.\d+)?\s*[KMkm]?)",

        # 1.2K booked
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*(?:bought|booked)",

        # 1.2K tickets
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?",

        # Generic count fields
        r'"(?:ticketCount|ticket_count|bookingCount|booking_count|recentBookings|recent_bookings)"\s*:\s*(\d+)',

        # Generic label/text/value containing tickets
        r'"(?:label|text|value)"\s*:\s*"([^"]*(?:ticket|booked|bought)[^"]*)"',
    ]

    for pattern in patterns:

        try:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE | re.DOTALL
            )

            if not match:
                continue

            candidate = match.group(1)

            number = parse_tickets(
                candidate
            )

            if number > 0:

                return (
                    number,
                    match.group(0)[:500]
                )

        except Exception:
            continue

    return 0, ""


# =========================================================
# RECURSIVE JSON SEARCH
# =========================================================

def search_json(
    obj,
    path="",
    results=None
):

    if results is None:
        results = []

    try:

        if isinstance(obj, dict):

            for key, value in obj.items():

                key_text = str(key)

                key_lower = key_text.lower()

                interesting = any(
                    word in key_lower
                    for word in [
                        "trend",
                        "velocity",
                        "booking",
                        "ticket",
                        "bought",
                        "booked",
                        "count"
                    ]
                )

                if interesting:

                    results.append({
                        "path": (
                            f"{path}.{key_text}"
                        ),
                        "key": key_text,
                        "value": value
                    })

                search_json(
                    value,
                    f"{path}.{key_text}",
                    results
                )

        elif isinstance(obj, list):

            for i, value in enumerate(obj):

                search_json(
                    value,
                    f"{path}[{i}]",
                    results
                )

    except Exception:
        pass

    return results


# =========================================================
# EXTRACT FROM JSON
# =========================================================

def extract_from_json(
    text,
    event_code=None,
    movie_title=None
):

    if not text:
        return 0, ""

    # ---------------------------------------------
    # First search raw text
    # ---------------------------------------------

    number, raw = extract_ticket_number(
        text
    )

    if number > 0:
        return number, raw

    # ---------------------------------------------
    # Parse JSON
    # ---------------------------------------------

    try:

        data = json.loads(
            text
        )

    except Exception:

        return 0, ""

    # ---------------------------------------------
    # Search JSON recursively
    # ---------------------------------------------

    matches = search_json(
        data
    )

    for item in matches:

        value = item.get(
            "value"
        )

        key = str(
            item.get("key", "")
        ).lower()

        try:

            value_text = json.dumps(
                value,
                ensure_ascii=False
            )

        except Exception:

            value_text = str(value)

        # Check textual value
        number, raw = extract_ticket_number(
            value_text
        )

        if number > 0:

            return number, raw

        # Check numeric count fields
        if any(
            x in key
            for x in [
                "ticketcount",
                "ticket_count",
                "bookingcount",
                "booking_count",
                "recentbooking"
            ]
        ):

            try:

                number = parse_tickets(
                    value
                )

                if number > 0:

                    return (
                        number,
                        f"{item.get('key')}: {value}"
                    )

            except Exception:
                pass

    return 0, ""


# =========================================================
# MAIN
# =========================================================

def run():

    # ---------------------------------------------
    # RESET DEBUG FILE
    # ---------------------------------------------

    with open(
        DEBUG_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "BOOKMYSHOW API TRENDING DEBUG\n"
        )

        f.write(
            "Started: "
            + datetime.datetime.now().isoformat()
            + "\n\n"
        )

    debug_write(
        "============================================"
    )

    debug_write(
        "BOOKMYSHOW TRENDING TRACKER"
    )

    debug_write(
        "============================================"
    )

    # =================================================
    # GOOGLE SHEETS
    # =================================================

    debug_write(
        "\n1. Connecting to Google Sheets..."
    )

    sa_info = json.loads(
        os.environ["GCP_SA_KEY"]
    )

    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets"
        ]
    )

    client = gspread.authorize(
        creds
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    sheet = spreadsheet.get_worksheet(0)

    expected_header = [
        "Timestamp (IST)",
        "Movie Title",
        "Event Code",
        "Tickets Sold (Last 1 Hr)",
        "Raw Status Text",
        "Scope"
    ]

    header = sheet.row_values(
        1
    )

    if not header or header[0] != "Timestamp (IST)":

        sheet.insert_row(
            expected_header,
            1
        )

    # =================================================
    # TIME
    # =================================================

    now_utc = datetime.datetime.now(
        datetime.timezone.utc
    )

    now_ist = (
        now_utc
        + datetime.timedelta(
            hours=5,
            minutes=30
        )
    ).strftime(
        "%Y-%m-%d %H:00:00"
    )

    # =================================================
    # STORAGE
    # =================================================

    movies = {}

    api_responses = []

    # =================================================
    # PLAYWRIGHT
    # =================================================

    debug_write(
        "\n2. Starting browser..."
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = browser.new_context(

            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/124.0.0.0 "
                "Safari/537.36"
            ),

            viewport={
                "width": 1440,
                "height": 900
            },

            locale="en-IN",

            timezone_id="Asia/Kolkata"
        )

        page = context.new_page()

        # =================================================
        # REQUEST CAPTURE
        # =================================================

        def on_request(request):

            try:

                if request.resource_type not in [
                    "xhr",
                    "fetch"
                ]:
                    return

                url = request.url

                debug_write(
                    "\n[REQUEST]"
                )

                debug_write(
                    request.resource_type
                    + " "
                    + url
                )

                # Capture POST body
                try:

                    post_data = (
                        request.post_data
                    )

                    if post_data:

                        debug_write(
                            "POST DATA:"
                        )

                        debug_write(
                            post_data[:10000]
                        )

                except Exception:
                    pass

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        # =================================================
        # RESPONSE CAPTURE
        # =================================================

        def on_response(response):

            try:

                request = response.request

                if request.resource_type not in [
                    "xhr",
                    "fetch"
                ]:
                    return

                url = response.url

                content_type = (
                    response.headers
                    .get(
                        "content-type",
                        ""
                    )
                    .lower()
                )

                try:

                    body = response.text()

                except Exception:

                    return

                if not body:
                    return

                lower = body.lower()

                # Search broadly
                keywords = [
                    "trending",
                    "trend",
                    "velocity",
                    "bookingvelocity",
                    "booking_velocity",
                    "recentbooking",
                    "recent_booking",
                    "ticketcount",
                    "ticket_count",
                    "bookingcount",
                    "booking_count",
                    "ticketsbought",
                    "tickets_bought",
                    "ticketsbooked",
                    "tickets_booked",
                    "bought",
                    "booked",
                    "ticket",
                    "booking"
                ]

                matched = [
                    k
                    for k in keywords
                    if k in lower
                ]

                if not matched:
                    return

                data = {
                    "url": url,
                    "content_type": content_type,
                    "body": body
                }

                api_responses.append(
                    data
                )

                debug_write(
                    "\n"
                    + "=" * 90
                )

                debug_write(
                    "[INTERESTING API RESPONSE]"
                )

                debug_write(
                    "URL:"
                )

                debug_write(
                    url
                )

                debug_write(
                    "MATCHES:"
                )

                debug_write(
                    ", ".join(matched)
                )

                debug_write(
                    "BODY:"
                )

                debug_write(
                    body[:30000]
                )

                debug_write(
                    "=" * 90
                )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )

        # =================================================
        # OPEN ONLY MOVIE LISTING PAGE
        # =================================================

        debug_write(
            "\n3. Opening BookMyShow Mumbai movie listing..."
        )

        listing_url = (
            "https://in.bookmyshow.com/"
            "explore/movies-mumbai"
        )

        try:

            page.goto(
                listing_url,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as e:

            debug_write(
                "Page load error: "
                + str(e)
            )

        # Give APIs time to fire
        page.wait_for_timeout(
            8000
        )

        # =================================================
        # SCROLL LISTING PAGE
        # =================================================

        debug_write(
            "\n4. Scrolling listing page..."
        )

        for i in range(10):

            try:

                page.evaluate(
                    "window.scrollBy(0, 1000)"
                )

            except Exception:
                pass

            page.wait_for_timeout(
                1500
            )

        # Additional wait for lazy API calls
        page.wait_for_timeout(
            5000
        )

        # =================================================
        # EXTRACT MOVIE LINKS
        # =================================================

        debug_write(
            "\n5. Extracting movies..."
        )

        try:

            links = page.eval_on_selector_all(
                "a",
                """
                elements =>
                    elements
                    .map(el => ({
                        href: el.getAttribute('href'),
                        text: el.innerText
                    }))
                    .filter(x => x.href)
                """
            )

            for item in links:

                href = item[
                    "href"
                ]

                match = re.search(
                    r"/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})",
                    href,
                    re.IGNORECASE
                )

                if not match:
                    continue

                slug = match.group(1)

                event_code = match.group(2)

                title = (
                    slug
                    .replace("-", " ")
                    .title()
                )

                if event_code not in movies:

                    movies[event_code] = {
                        "title": title,
                        "code": event_code,
                        "url": (
                            href
                            if href.startswith("http")
                            else
                            "https://in.bookmyshow.com"
                            + href
                        )
                    }

        except Exception as e:

            debug_write(
                "Movie extraction error: "
                + str(e)
            )

        debug_write(
            "\nMovies found: "
            + str(len(movies))
        )

        # =================================================
        # SEARCH LISTING PAGE VISIBLE TEXT
        # =================================================

        debug_write(
            "\n6. Searching visible listing text..."
        )

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

            debug_write(
                "\nVISIBLE TEXT SAMPLE:"
            )

            debug_write(
                body_text[:30000]
            )

            # Try direct extraction
            number, raw = (
                extract_ticket_number(
                    body_text
                )
            )

            if number > 0:

                debug_write(
                    "\nFOUND GLOBAL TRENDING:"
                )

                debug_write(
                    str(number)
                )

                debug_write(
                    raw
                )

        except Exception as e:

            debug_write(
                "Visible text error: "
                + str(e)
            )

        # =================================================
        # SEARCH ALL API RESPONSES
        # =================================================

        debug_write(
            "\n7. Searching captured API responses..."
        )

        # =================================================
        # RESULTS
        # =================================================

        results = {}

        for event_code, movie in movies.items():

            tickets = 0

            raw_text = (
                "No Trending Data Found"
            )

            title = movie[
                "title"
            ]

            # -----------------------------------------
            # Search every captured API response
            # -----------------------------------------

            for response in api_responses:

                body = response[
                    "body"
                ]

                url = response[
                    "url"
                ]

                lower_body = body.lower()

                # Event code must ideally be
                # associated with this response
                code_match = (
                    event_code.lower()
                    in lower_body
                    or
                    event_code.lower()
                    in url.lower()
                )

                # Title match is secondary
                title_match = (
                    title.lower()
                    in lower_body
                )

                if not (
                    code_match
                    or title_match
                ):
                    continue

                number, raw = (
                    extract_from_json(
                        body,
                        event_code,
                        title
                    )
                )

                if number > 0:

                    tickets = number

                    raw_text = raw

                    debug_write(
                        "\nFOUND!"
                    )

                    debug_write(
                        "MOVIE: "
                        + title
                    )

                    debug_write(
                        "EVENT: "
                        + event_code
                    )

                    debug_write(
                        "TICKETS: "
                        + str(tickets)
                    )

                    debug_write(
                        "API: "
                        + url
                    )

                    debug_write(
                        "RAW: "
                        + raw_text
                    )

                    break

            results[
                event_code
            ] = {
                "tickets": tickets,
                "raw": raw_text
            }

        # =================================================
        # FINAL RESULTS
        # =================================================

        debug_write(
            "\n"
            + "=" * 90
        )

        debug_write(
            "FINAL RESULTS"
        )

        debug_write(
            "=" * 90
        )

        rows_to_append = []

        for event_code, movie in movies.items():

            result = results.get(
                event_code,
                {}
            )

            tickets = result.get(
                "tickets",
                0
            )

            raw_text = result.get(
                "raw",
                "No Trending Data Found"
            )

            debug_write(
                f"{movie['title']} | "
                f"{event_code} | "
                f"{tickets} | "
                f"{raw_text}"
            )

            rows_to_append.append(
                [
                    now_ist,
                    movie["title"],
                    event_code,
                    tickets,
                    raw_text,
                    "All India"
                ]
            )

        browser.close()

    # =================================================
    # GOOGLE SHEETS
    # =================================================

    debug_write(
        "\n8. Updating Google Sheet..."
    )

    if rows_to_append:

        sheet.append_rows(
            rows_to_append,
            value_input_option="USER_ENTERED"
        )

        debug_write(
            "Google Sheet updated."
        )

    else:

        debug_write(
            "No rows generated."
        )

    debug_write(
        "\n============================================"
    )

    debug_write(
        "COMPLETE"
    )

    debug_write(
        "Debug file: "
        + DEBUG_FILE
    )

    debug_write(
        "============================================"
    )


if __name__ == "__main__":
    run()
