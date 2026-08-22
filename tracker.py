import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

DEBUG_FILE = "bms_debug.txt"


def write_debug(text):
    print(text)

    with open(
        DEBUG_FILE,
        "a",
        encoding="utf-8"
    ) as f:
        f.write(text + "\n")


def run():

    # --------------------------------------------------
    # RESET DEBUG FILE
    # --------------------------------------------------

    with open(
        DEBUG_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "BOOKMYSHOW TRENDING DIAGNOSTIC\n"
        )

        f.write(
            "Started: "
            + datetime.datetime.now().isoformat()
            + "\n\n"
        )

    write_debug(
        "=============================================="
    )

    write_debug(
        "BOOKMYSHOW TRENDING DIAGNOSTIC"
    )

    write_debug(
        "=============================================="
    )

    # --------------------------------------------------
    # GOOGLE SHEETS
    # --------------------------------------------------

    write_debug(
        "\nConnecting to Google Sheets..."
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

    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    sheet = spreadsheet.get_worksheet(0)

    # --------------------------------------------------
    # PLAYWRIGHT
    # --------------------------------------------------

    write_debug(
        "\nStarting Chromium..."
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

        # --------------------------------------------------
        # REQUEST LOGGER
        # --------------------------------------------------

        def on_request(request):

            try:

                url = request.url

                resource_type = request.resource_type

                # We are particularly interested in these
                if resource_type in [
                    "xhr",
                    "fetch"
                ]:

                    write_debug(
                        "\n[REQUEST]"
                    )

                    write_debug(
                        "TYPE: "
                        + resource_type
                    )

                    write_debug(
                        "URL: "
                        + url
                    )

                    # POST body can reveal GraphQL/API query
                    try:

                        post_data = request.post_data

                        if post_data:

                            write_debug(
                                "POST DATA:"
                            )

                            write_debug(
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

        # --------------------------------------------------
        # RESPONSE LOGGER
        # --------------------------------------------------

        def on_response(response):

            try:

                url = response.url

                resource_type = response.request.resource_type

                content_type = (
                    response.headers
                    .get(
                        "content-type",
                        ""
                    )
                    .lower()
                )

                # Only API/XHR/fetch/json
                interesting = (
                    resource_type in [
                        "xhr",
                        "fetch"
                    ]
                    or
                    "json" in content_type
                    or
                    "graphql" in url.lower()
                )

                if not interesting:
                    return

                try:

                    body = response.text()

                except Exception:

                    return

                if not body:
                    return

                lower = body.lower()

                # ------------------------------------------------
                # VERY BROAD KEYWORD CHECK
                # ------------------------------------------------

                keywords = [
                    "trending",
                    "trend",
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
                    "velocity",
                    "ticket",
                    "booking"
                ]

                matched = [
                    word
                    for word in keywords
                    if word in lower
                ]

                if not matched:
                    return

                write_debug(
                    "\n"
                    + "=" * 80
                )

                write_debug(
                    "[IMPORTANT RESPONSE]"
                )

                write_debug(
                    "STATUS: "
                    + str(response.status)
                )

                write_debug(
                    "TYPE: "
                    + resource_type
                )

                write_debug(
                    "CONTENT TYPE: "
                    + content_type
                )

                write_debug(
                    "MATCHED KEYWORDS: "
                    + ", ".join(matched)
                )

                write_debug(
                    "URL:"
                )

                write_debug(
                    url
                )

                # ------------------------------------------------
                # RESPONSE BODY
                # ------------------------------------------------

                write_debug(
                    "\nRESPONSE BODY:"
                )

                # Don't truncate too aggressively.
                # First 50,000 characters should be enough
                # to identify the API structure.

                write_debug(
                    body[:50000]
                )

                write_debug(
                    "\n"
                    + "=" * 80
                )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )

        # --------------------------------------------------
        # DISCOVER MOVIES
        # --------------------------------------------------

        write_debug(
            "\nOpening BookMyShow Mumbai movies..."
        )

        try:

            page.goto(
                "https://in.bookmyshow.com/explore/movies-mumbai",
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(
                8000
            )

            # Scroll to trigger lazy loading
            for i in range(8):

                write_debug(
                    f"Scrolling {i + 1}/8..."
                )

                page.evaluate(
                    "window.scrollBy(0, 1200)"
                )

                page.wait_for_timeout(
                    1500
                )

        except Exception as e:

            write_debug(
                "Movie discovery error: "
                + str(e)
            )

        # --------------------------------------------------
        # FIND MOVIE LINKS
        # --------------------------------------------------

        movies = {}

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

                title = (
                    slug
                    .replace("-", " ")
                    .title()
                )

                if code not in movies:

                    movies[code] = {
                        "title": title,
                        "url": (
                            href
                            if href.startswith("http")
                            else
                            "https://in.bookmyshow.com"
                            + href
                        )
                    }

        except Exception as e:

            write_debug(
                "Movie extraction error: "
                + str(e)
            )

        write_debug(
            "\nMovies found: "
            + str(len(movies))
        )

        # --------------------------------------------------
        # PICK FIRST FEW MOVIES
        # --------------------------------------------------
        #
        # We don't need to inspect 100 movies.
        # 5 is enough to identify the API.
        # --------------------------------------------------

        selected = list(
            movies.items()
        )[:5]

        write_debug(
            "\nInspecting "
            + str(len(selected))
            + " movie pages..."
        )

        # --------------------------------------------------
        # VISIT MOVIE PAGES
        # --------------------------------------------------

        for number, (code, movie) in enumerate(
            selected,
            start=1
        ):

            write_debug(
                "\n\n"
                + "#" * 80
            )

            write_debug(
                f"MOVIE {number}/{len(selected)}"
            )

            write_debug(
                "TITLE: "
                + movie["title"]
            )

            write_debug(
                "EVENT CODE: "
                + code
            )

            write_debug(
                "URL: "
                + movie["url"]
            )

            write_debug(
                "#" * 80
            )

            try:

                page.goto(
                    movie["url"],
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                # Important:
                # wait for dynamic BMS components
                page.wait_for_timeout(
                    10000
                )

                # Scroll entire page
                for i in range(6):

                    page.evaluate(
                        "window.scrollBy(0, 1000)"
                    )

                    page.wait_for_timeout(
                        1500
                    )

                # Additional wait
                page.wait_for_timeout(
                    5000
                )

                # ------------------------------------------------
                # SAVE FULL PAGE TEXT
                # ------------------------------------------------

                try:

                    body_text = page.locator(
                        "body"
                    ).inner_text()

                    write_debug(
                        "\nVISIBLE PAGE TEXT:"
                    )

                    write_debug(
                        body_text[:30000]
                    )

                except Exception:
                    pass

                # ------------------------------------------------
                # SAVE HTML
                # ------------------------------------------------

                try:

                    html = page.content()

                    # Search HTML for relevant terms
                    html_lower = html.lower()

                    html_keywords = [
                        "trending",
                        "booking",
                        "ticket",
                        "bought",
                        "booked",
                        "velocity"
                    ]

                    matched_html = [
                        x
                        for x in html_keywords
                        if x in html_lower
                    ]

                    write_debug(
                        "\nHTML KEYWORDS FOUND:"
                    )

                    write_debug(
                        ", ".join(matched_html)
                    )

                    # Save snippets around keywords
                    for keyword in matched_html:

                        positions = [
                            m.start()
                            for m in re.finditer(
                                keyword,
                                html_lower
                            )
                        ]

                        for pos in positions[:10]:

                            start = max(
                                0,
                                pos - 1000
                            )

                            end = min(
                                len(html),
                                pos + 3000
                            )

                            write_debug(
                                f"\nHTML SNIPPET "
                                f"FOR [{keyword}]:"
                            )

                            write_debug(
                                html[start:end]
                            )

                except Exception:
                    pass

                # ------------------------------------------------
                # SCREENSHOT
                # ------------------------------------------------

                try:

                    filename = (
                        "bms_debug_"
                        + code
                        + ".png"
                    )

                    page.screenshot(
                        path=filename,
                        full_page=True
                    )

                    write_debug(
                        "\nScreenshot saved: "
                        + filename
                    )

                except Exception as e:

                    write_debug(
                        "Screenshot error: "
                        + str(e)
                    )

            except Exception as e:

                write_debug(
                    "Movie page error: "
                    + str(e)
                )

        # --------------------------------------------------
        # FINISH
        # --------------------------------------------------

        browser.close()

    write_debug(
        "\n\n"
        + "=" * 80
    )

    write_debug(
        "DIAGNOSTIC COMPLETE"
    )

    write_debug(
        "Check bms_debug.txt"
    )

    write_debug(
        "=" * 80
    )


if __name__ == "__main__":
    run()
