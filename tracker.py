import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

DEBUG_FILE = "bms_full_debug.json"


# =========================================================
# TICKET PARSER
# =========================================================

def parse_tickets(raw_str):
    if raw_str is None:
        return 0

    text = str(raw_str).strip().replace(",", "")

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


# =========================================================
# POSSIBLE TRENDING TEXT
# =========================================================

def find_trending_text(text):

    if not text:
        return []

    patterns = [

        r".{0,300}(?:trending|trend).{0,500}",

        r".{0,300}(?:tickets?\s+bought).{0,500}",

        r".{0,300}(?:tickets?\s+booked).{0,500}",

        r".{0,300}(?:booking\s+velocity).{0,500}",

        r".{0,300}(?:recent\s+bookings?).{0,500}",

        r".{0,300}(?:ticket\s+count).{0,500}",

        r".{0,300}(?:booked).{0,500}",

        r".{0,300}(?:bought).{0,500}"
    ]

    results = []

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                text,
                re.IGNORECASE | re.DOTALL
            )

            for match in matches:

                cleaned = re.sub(
                    r"\s+",
                    " ",
                    match
                ).strip()

                if cleaned and cleaned not in results:
                    results.append(cleaned[:1500])

        except Exception:
            pass

    return results[:100]


# =========================================================
# MAIN
# =========================================================

def run():

    # -----------------------------------------------------
    # RESET DEBUG FILE
    # -----------------------------------------------------

    debug_data = {
        "started_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "requests": [],
        "responses": [],
        "movies": [],
        "page_text": "",
        "page_html_matches": []
    }

    with open(
        DEBUG_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            debug_data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "=============================================="
    )

    print(
        "BOOKMYSHOW MOVIE + API DEBUG TRACKER"
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

    # =====================================================
    # STORAGE
    # =====================================================

    unique_movies = {}

    captured_requests = []

    captured_responses = []

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
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
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
        # REQUEST LOGGER
        # =================================================

        def on_request(request):

            try:

                resource_type = request.resource_type

                if resource_type not in [
                    "xhr",
                    "fetch"
                ]:
                    return

                url = request.url

                item = {
                    "type": resource_type,
                    "method": request.method,
                    "url": url,
                    "post_data": None
                }

                try:

                    item["post_data"] = (
                        request.post_data
                    )

                except Exception:
                    pass

                captured_requests.append(
                    item
                )

                # Print only BMS API requests
                if "bookmyshow.com/api/" in url:

                    print(
                        "\n[BMS API REQUEST]"
                    )

                    print(
                        url
                    )

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        # =================================================
        # RESPONSE LOGGER
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

                # We mainly want BookMyShow responses
                if (
                    "bookmyshow.com" not in
                    url.lower()
                ):
                    return

                try:

                    body = response.text()

                except Exception:

                    return

                if not body:
                    return

                # Save response
                item = {
                    "url": url,
                    "status": response.status,
                    "content_type":
                        response.headers.get(
                            "content-type",
                            ""
                        ),
                    "body": body[:150000]
                }

                captured_responses.append(
                    item
                )

                # Look for potentially useful content
                lower = body.lower()

                interesting_words = [
                    "trending",
                    "trend",
                    "velocity",
                    "ticket",
                    "booking",
                    "booked",
                    "bought",
                    "recent"
                ]

                matched = [
                    x
                    for x in interesting_words
                    if x in lower
                ]

                if matched:

                    print(
                        "\n------------------------------------------"
                    )

                    print(
                        "[INTERESTING BMS RESPONSE]"
                    )

                    print(
                        "URL:",
                        url
                    )

                    print(
                        "STATUS:",
                        response.status
                    )

                    print(
                        "MATCHED:",
                        ", ".join(matched)
                    )

                    # Show snippets
                    snippets = find_trending_text(
                        body
                    )

                    for snippet in snippets[:10]:

                        print(
                            "\nSNIPPET:"
                        )

                        print(
                            snippet
                        )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )

        # =================================================
        # OPEN MOVIE LISTING
        # =================================================

        print(
            "\n3. Opening Mumbai movie listing..."
        )

        try:

            page.goto(
                "https://in.bookmyshow.com/explore/movies-mumbai",
                wait_until="domcontentloaded",
                timeout=30000
            )

        except Exception as e:

            print(
                "Explore error:",
                e
            )

        # IMPORTANT:
        # Same waiting approach that worked for movie discovery

        page.wait_for_timeout(
            5000
        )

        # =================================================
        # SCROLL
        # =================================================

        print(
            "\n4. Loading more movies..."
        )

        for i in range(8):

            print(
                "Scroll",
                i + 1,
                "/ 8"
            )

            try:

                page.evaluate(
                    "window.scrollBy(0, 1500)"
                )

            except Exception:
                pass

            page.wait_for_timeout(
                1200
            )

        # Extra wait for API calls
        page.wait_for_timeout(
            5000
        )

        # =================================================
        # DISCOVER MOVIES
        # =================================================

        print(
            "\n5. Discovering active movies..."
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

            print(
                "Links found:",
                len(links)
            )

            for item in links:

                href = item["href"]

                # SAME REGEX AS YOUR ORIGINAL WORKING CODE

                match = re.search(
                    r"/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})",
                    href,
                    re.IGNORECASE
                )

                if not match:
                    continue

                slug = match.group(1)

                code = match.group(2)

                title = (
                    slug
                    .replace("-", " ")
                    .title()
                )

                if code not in unique_movies:

                    unique_movies[code] = {

                        "title": title,

                        "url": (
                            href
                            if href.startswith("http")
                            else
                            "https://in.bookmyshow.com"
                            + href
                        ),

                        "code": code
                    }

        except Exception as e:

            print(
                "Movie extraction error:",
                e
            )

        print(
            "\nFOUND MOVIES:",
            len(unique_movies)
        )

        for code, movie in unique_movies.items():

            print(
                movie["title"],
                "|",
                code
            )

        # =================================================
        # CAPTURE VISIBLE TEXT
        # =================================================

        print(
            "\n6. Capturing listing-page text..."
        )

        page_text = ""

        try:

            page_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

            print(
                "Page text length:",
                len(page_text)
            )

        except Exception as e:

            print(
                "Could not capture page text:",
                e
            )

        # =================================================
        # CAPTURE HTML
        # =================================================

        print(
            "\n7. Searching page HTML..."
        )

        html_matches = []

        try:

            html = page.content()

            html_lower = html.lower()

            search_words = [
                "trending",
                "trend",
                "ticket",
                "booking",
                "booked",
                "bought",
                "velocity"
            ]

            for word in search_words:

                positions = [
                    m.start()
                    for m in re.finditer(
                        word,
                        html_lower
                    )
                ]

                for pos in positions[:20]:

                    start = max(
                        0,
                        pos - 1000
                    )

                    end = min(
                        len(html),
                        pos + 3000
                    )

                    html_matches.append(
                        {
                            "keyword": word,
                            "snippet":
                                html[start:end]
                        }
                    )

        except Exception as e:

            print(
                "HTML capture error:",
                e
            )

        print(
            "HTML matches:",
            len(html_matches)
        )

        # =================================================
        # WAIT A LITTLE MORE FOR API RESPONSES
        # =================================================

        print(
            "\n8. Final API wait..."
        )

        page.wait_for_timeout(
            5000
        )

        # =================================================
        # SAVE DEBUG FILE
        # =================================================

        print(
            "\n9. Saving debug information..."
        )

        debug_data = {

            "generated_at":
                datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),

            "movie_count":
                len(unique_movies),

            "movies":
                list(
                    unique_movies.values()
                ),

            "requests":
                captured_requests,

            "responses":
                captured_responses,

            "page_text":
                page_text[:100000],

            "page_html_matches":
                html_matches[:200]
        }

        try:

            with open(
                DEBUG_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    debug_data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print(
                "DEBUG FILE CREATED:"
            )

            print(
                DEBUG_FILE
            )

        except Exception as e:

            print(
                "Debug file error:",
                e
            )

        # =================================================
        # WRITE MOVIES TO GOOGLE SHEET
        # =================================================

        print(
            "\n10. Writing movie data to Google Sheet..."
        )

        rows_to_append = []

        for code, movie in unique_movies.items():

            # We are NOT claiming a Trending number yet.
            # This is intentionally diagnostic.

            rows_to_append.append(
                [
                    now_ist,
                    movie["title"],
                    code,
                    0,
                    "API Diagnostic - Trending Not Yet Extracted",
                    "All India"
                ]
            )

        if rows_to_append:

            sheet.append_rows(
                rows_to_append,
                value_input_option="USER_ENTERED"
            )

            print(
                "Movie rows written:",
                len(rows_to_append)
            )

        browser.close()

    # =====================================================
    # FINISH
    # =====================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "COMPLETE"
    )

    print(
        "=" * 70
    )

    print(
        "Movies found:",
        len(unique_movies)
    )

    print(
        "API requests captured:",
        len(captured_requests)
    )

    print(
        "API responses captured:",
        len(captured_responses)
    )

    print(
        "Debug file:",
        DEBUG_FILE
    )

    print(
        "\nIMPORTANT:"
    )

    print(
        "Download bms_full_debug.json "
        "from your GitHub Actions run."
    )


if __name__ == "__main__":
    run()
