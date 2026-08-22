import os
import json
import re
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

DEBUG_FILE = "bms_trending_debug.json"


# =========================================================
# HELPERS
# =========================================================

def parse_tickets(value):

    if value is None:
        return 0

    text = str(value).replace(",", "").strip()

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*([KM]?)",
        text,
        re.IGNORECASE
    )

    if not match:
        return 0

    number = float(match.group(1))
    suffix = match.group(2).upper()

    if suffix == "K":
        number *= 1000
    elif suffix == "M":
        number *= 1000000

    return int(number)


def clean_title(slug):

    return (
        slug
        .replace("-", " ")
        .title()
        .strip()
    )


def find_numbers_near_keywords(text):

    results = []

    if not text:
        return results

    patterns = [

        # 1.2K tickets bought
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?\s*(?:bought|booked)",

        # 1.2K tickets
        r"(\d+(?:\.\d+)?\s*[KMkm]?)\s*tickets?",

        # tickets bought: 1.2K
        r"tickets?\s*(?:bought|booked)\s*[:\-]?\s*(\d+(?:\.\d+)?\s*[KMkm]?)",

        # recentBookings: 123
        r"(?:recentBookings|recent_bookings)\s*[:=]\s*[\"']?(\d+(?:\.\d+)?\s*[KMkm]?)",

        # bookingVelocity: 123
        r"(?:bookingVelocity|booking_velocity)\s*[:=]\s*[\"']?(\d+(?:\.\d+)?\s*[KMkm]?)",

        # ticketCount: 123
        r"(?:ticketCount|ticket_count)\s*[:=]\s*[\"']?(\d+(?:\.\d+)?\s*[KMkm]?)",

        # bookingCount: 123
        r"(?:bookingCount|booking_count)\s*[:=]\s*[\"']?(\d+(?:\.\d+)?\s*[KMkm]?)"
    ]

    for pattern in patterns:

        try:

            matches = re.finditer(
                pattern,
                text,
                re.IGNORECASE
            )

            for match in matches:

                number = parse_tickets(
                    match.group(1)
                )

                if number > 0:

                    start = max(
                        0,
                        match.start() - 500
                    )

                    end = min(
                        len(text),
                        match.end() + 500
                    )

                    results.append({
                        "number": number,
                        "match": match.group(0),
                        "context": text[start:end]
                    })

        except Exception:
            pass

    return results


def recursive_search(
    obj,
    event_code,
    title,
    path=""
):

    found = []

    try:

        if isinstance(obj, dict):

            for key, value in obj.items():

                key_text = str(key)

                current_path = (
                    f"{path}.{key_text}"
                )

                key_lower = key_text.lower()

                # Convert value to searchable text
                try:

                    value_text = json.dumps(
                        value,
                        ensure_ascii=False
                    )

                except Exception:

                    value_text = str(value)

                # -------------------------------------------------
                # Check if this object is associated with movie
                # -------------------------------------------------

                movie_related = (

                    event_code.lower()
                    in value_text.lower()

                    or

                    title.lower()
                    in value_text.lower()
                )

                # -------------------------------------------------
                # Interesting field names
                # -------------------------------------------------

                interesting_key = any(
                    x in key_lower
                    for x in [
                        "trend",
                        "velocity",
                        "booking",
                        "booked",
                        "bought",
                        "ticket",
                        "recent",
                        "count"
                    ]
                )

                if interesting_key:

                    found.append({
                        "path": current_path,
                        "key": key_text,
                        "value": value
                    })

                # Search textual values
                if movie_related:

                    number_matches = (
                        find_numbers_near_keywords(
                            value_text
                        )
                    )

                    for item in number_matches:

                        item["path"] = current_path
                        item["key"] = key_text

                        found.append(
                            item
                        )

                # Continue recursively
                found.extend(
                    recursive_search(
                        value,
                        event_code,
                        title,
                        current_path
                    )
                )

        elif isinstance(obj, list):

            for index, value in enumerate(obj):

                current_path = (
                    f"{path}[{index}]"
                )

                found.extend(
                    recursive_search(
                        value,
                        event_code,
                        title,
                        current_path
                    )
                )

    except Exception:
        pass

    return found


# =========================================================
# MAIN
# =========================================================

def run():

    debug = {
        "started": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "api_requests": [],
        "api_responses": [],
        "movies": [],
        "results": []
    }

    print(
        "=============================================="
    )

    print(
        "BOOKMYSHOW TRENDING TRACKER - API VERSION"
    )

    print(
        "=============================================="
    )

    # =====================================================
    # GOOGLE SHEETS
    # =====================================================

    print(
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

    header = sheet.row_values(1)

    if not header or header[0] != "Timestamp (IST)":

        sheet.insert_row(
            [
                "Timestamp (IST)",
                "Movie Title",
                "Event Code",
                "Tickets Sold (Last 1 Hr)",
                "Raw Status Text",
                "Scope"
            ],
            1
        )

    # =====================================================
    # TIME
    # =====================================================

    now_ist = (
        datetime.datetime.now(
            datetime.timezone.utc
        )
        + datetime.timedelta(
            hours=5,
            minutes=30
        )
    ).strftime(
        "%Y-%m-%d %H:00:00"
    )

    # =====================================================
    # PLAYWRIGHT
    # =====================================================

    print(
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
                "width": 1366,
                "height": 768
            },

            locale="en-IN",

            timezone_id="Asia/Kolkata"
        )

        page = context.new_page()

        # =================================================
        # REQUEST CAPTURE
        # =================================================

        def handle_request(request):

            try:

                url = request.url

                if "bookmyshow.com/api/" not in url:
                    return

                item = {
                    "url": url,
                    "method": request.method,
                    "resource_type":
                        request.resource_type,
                    "headers":
                        dict(request.headers),
                    "post_data": None
                }

                try:

                    item["post_data"] = (
                        request.post_data
                    )

                except Exception:
                    pass

                debug["api_requests"].append(
                    item
                )

                # We specifically want discover API
                if "/discover/" in url:

                    print(
                        "\n[BMS DISCOVER REQUEST]"
                    )

                    print(
                        url
                    )

                    print(
                        "METHOD:",
                        request.method
                    )

            except Exception:
                pass

        page.on(
            "request",
            handle_request
        )

        # =================================================
        # RESPONSE CAPTURE
        # =================================================

        def handle_response(response):

            try:

                url = response.url

                if "bookmyshow.com/api/" not in url:
                    return

                try:

                    body = response.text()

                except Exception:

                    return

                if not body:
                    return

                item = {
                    "url": url,
                    "status": response.status,
                    "headers":
                        dict(response.headers),
                    "body": body[:250000]
                }

                debug["api_responses"].append(
                    item
                )

                if "/discover/" in url:

                    print(
                        "\n[BMS DISCOVER RESPONSE]"
                    )

                    print(
                        "STATUS:",
                        response.status
                    )

                    print(
                        "SIZE:",
                        len(body)
                    )

                    print(
                        "URL:",
                        url
                    )

                    # Try JSON
                    try:

                        parsed = json.loads(
                            body
                        )

                        item["json"] = parsed

                    except Exception:

                        parsed = None

            except Exception:
                pass

        page.on(
            "response",
            handle_response
        )

        # =================================================
        # OPEN MOVIE LISTING
        # =================================================

        print(
            "\n3. Opening BookMyShow movie listing..."
        )

        try:

            page.goto(
                "https://in.bookmyshow.com/explore/movies-mumbai",
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as e:

            print(
                "Page error:",
                e
            )

        # Give initial API calls time
        page.wait_for_timeout(
            7000
        )

        # =================================================
        # MOVIE DISCOVERY
        # =================================================

        print(
            "\n4. Discovering movies..."
        )

        unique_movies = {}

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

                href = item["href"]

                match = re.search(
                    r"/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})",
                    href,
                    re.IGNORECASE
                )

                if not match:
                    continue

                slug = match.group(1)

                code = match.group(2)

                title = clean_title(
                    slug
                )

                if code not in unique_movies:

                    unique_movies[code] = {
                        "title": title,
                        "code": code,
                        "url": (
                            href
                            if href.startswith("http")
                            else
                            "https://in.bookmyshow.com"
                            + href
                        )
                    }

        except Exception as e:

            print(
                "Movie discovery error:",
                e
            )

        debug["movies"] = list(
            unique_movies.values()
        )

        print(
            "\nMOVIES FOUND:",
            len(unique_movies)
        )

        for code, movie in unique_movies.items():

            print(
                movie["title"],
                "|",
                code
            )

        # =================================================
        # SCROLL
        # =================================================

        print(
            "\n5. Scrolling listing page..."
        )

        for i in range(10):

            try:

                page.evaluate(
                    "window.scrollBy(0, 1400)"
                )

            except Exception:
                pass

            page.wait_for_timeout(
                1500
            )

        # Extra API wait
        page.wait_for_timeout(
            7000
        )

        # =================================================
        # ANALYZE API RESPONSES
        # =================================================

        print(
            "\n6. Analysing captured API responses..."
        )

        results = {}

        for code, movie in unique_movies.items():

            title = movie["title"]

            tickets = 0

            raw_status = (
                "No Trending Data Found"
            )

            matches_for_movie = []

            for response in debug[
                "api_responses"
            ]:

                body = response.get(
                    "body",
                    ""
                )

                url = response.get(
                    "url",
                    ""
                )

                if not body:
                    continue

                # Only consider responses containing
                # this movie's Event Code
                if (
                    code.lower()
                    not in body.lower()
                    and
                    code.lower()
                    not in url.lower()
                ):

                    continue

                print(
                    "\nChecking:",
                    title,
                    "|",
                    code
                )

                # -----------------------------------------
                # Raw text search
                # -----------------------------------------

                raw_matches = (
                    find_numbers_near_keywords(
                        body
                    )
                )

                for match in raw_matches:

                    matches_for_movie.append({
                        "type": "raw",
                        "url": url,
                        "data": match
                    })

                # -----------------------------------------
                # JSON search
                # -----------------------------------------

                parsed = response.get(
                    "json"
                )

                if parsed is not None:

                    json_matches = (
                        recursive_search(
                            parsed,
                            code,
                            title
                        )
                    )

                    for match in json_matches:

                        matches_for_movie.append({
                            "type": "json",
                            "url": url,
                            "data": match
                        })

            # -------------------------------------------------
            # Find an actual numeric ticket result
            # -------------------------------------------------

            for match in matches_for_movie:

                data = match.get(
                    "data",
                    {}
                )

                if isinstance(data, dict):

                    number = data.get(
                        "number",
                        0
                    )

                    if number > 0:

                        tickets = number

                        raw_status = (
                            data.get(
                                "match",
                                str(data)
                            )
                        )

                        break

                    value = data.get(
                        "value"
                    )

                    if value is not None:

                        number = parse_tickets(
                            value
                        )

                        if number > 0:

                            tickets = number

                            raw_status = (
                                f"{data.get('key')}: "
                                f"{value}"
                            )

                            break

            results[code] = {
                "tickets": tickets,
                "raw": raw_status,
                "matches": matches_for_movie[:100]
            }

            print(
                "RESULT:",
                title,
                "=>",
                tickets,
                "|",
                raw_status
            )

        # =================================================
        # SAVE DEBUG
        # =================================================

        debug["results"] = [
            {
                "event_code": code,
                "movie": unique_movies[code],
                "result": results[code]
            }
            for code in unique_movies
        ]

        print(
            "\n7. Saving debug file..."
        )

        with open(
            DEBUG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                debug,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(
            "Saved:",
            DEBUG_FILE
        )

        # =================================================
        # WRITE TO GOOGLE SHEET
        # =================================================

        print(
            "\n8. Updating Google Sheet..."
        )

        rows = []

        for code, movie in unique_movies.items():

            result = results.get(
                code,
                {}
            )

            rows.append(
                [
                    now_ist,
                    movie["title"],
                    code,
                    result.get(
                        "tickets",
                        0
                    ),
                    result.get(
                        "raw",
                        "No Trending Data Found"
                    ),
                    "All India"
                ]
            )

        if rows:

            sheet.append_rows(
                rows,
                value_input_option="USER_ENTERED"
            )

            print(
                "Rows added:",
                len(rows)
            )

        browser.close()

    # =====================================================
    # FINAL
    # =====================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "DONE"
    )

    print(
        "=" * 70
    )

    print(
        "Movies:",
        len(unique_movies)
    )

    print(
        "API requests:",
        len(debug["api_requests"])
    )

    print(
        "API responses:",
        len(debug["api_responses"])
    )

    print(
        "Debug:",
        DEBUG_FILE
    )


if __name__ == "__main__":
    run()
