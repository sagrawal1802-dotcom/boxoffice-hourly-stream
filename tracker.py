import os
import json
import re
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

DEBUG_FILE = "bms_discover_debug.json"


def save_debug(data):
    try:
        with open(
            DEBUG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "Could not save debug file:",
            e
        )


def run():

    print(
        "========================================"
    )

    print(
        "BOOKMYSHOW DISCOVER API CAPTURE"
    )

    print(
        "========================================"
    )

    captured_responses = []

    requests_seen = []

    # --------------------------------------------------
    # GOOGLE SHEETS CONNECTION
    # --------------------------------------------------

    print(
        "\nConnecting to Google Sheets..."
    )

    try:

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

        print(
            "Google Sheets connected."
        )

    except Exception as e:

        print(
            "Google Sheets connection error:",
            e
        )

    # --------------------------------------------------
    # PLAYWRIGHT
    # --------------------------------------------------

    print(
        "\nStarting browser..."
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
        # CAPTURE REQUESTS
        # --------------------------------------------------

        def on_request(request):

            try:

                url = request.url

                if (
                    "/api/explore/v1/discover/"
                    in url
                ):

                    print(
                        "\nDISCOVER REQUEST:"
                    )

                    print(
                        url
                    )

                    request_info = {
                        "url": url,
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "post_data": None
                    }

                    try:

                        request_info[
                            "post_data"
                        ] = request.post_data

                    except Exception:
                        pass

                    requests_seen.append(
                        request_info
                    )

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        # --------------------------------------------------
        # CAPTURE DISCOVER API RESPONSE
        # --------------------------------------------------

        def on_response(response):

            try:

                url = response.url

                if (
                    "/api/explore/v1/discover/"
                    not in url
                ):
                    return

                print(
                    "\n"
                    + "=" * 90
                )

                print(
                    "DISCOVER API RESPONSE FOUND"
                )

                print(
                    "URL:"
                )

                print(
                    url
                )

                print(
                    "STATUS:",
                    response.status
                )

                print(
                    "=" * 90
                )

                try:

                    body = response.text()

                except Exception as e:

                    print(
                        "Could not read response:",
                        e
                    )

                    return

                if not body:

                    print(
                        "Empty response."
                    )

                    return

                # --------------------------------------------------
                # TRY JSON
                # --------------------------------------------------

                try:

                    parsed = json.loads(
                        body
                    )

                except Exception:

                    parsed = None

                response_data = {

                    "url": url,

                    "status": response.status,

                    "content_type":
                        response.headers.get(
                            "content-type",
                            ""
                        ),

                    "body_length":
                        len(body),

                    "body_text":
                        body[:200000],

                    "json":
                        parsed
                }

                captured_responses.append(
                    response_data
                )

                print(
                    "Response size:",
                    len(body)
                )

                print(
                    "\nFIRST 5000 CHARACTERS:"
                )

                print(
                    body[:5000]
                )

                print(
                    "\nSaved in memory."
                )

            except Exception as e:

                print(
                    "Response capture error:",
                    e
                )

        page.on(
            "response",
            on_response
        )

        # --------------------------------------------------
        # OPEN MOVIE LISTING
        # --------------------------------------------------

        url = (
            "https://in.bookmyshow.com/"
            "explore/movies-mumbai"
        )

        print(
            "\nOpening:"
        )

        print(
            url
        )

        try:

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as e:

            print(
                "Page navigation error:",
                e
            )

        # --------------------------------------------------
        # WAIT FOR INITIAL API CALLS
        # --------------------------------------------------

        print(
            "\nWaiting for BookMyShow API calls..."
        )

        page.wait_for_timeout(
            10000
        )

        # --------------------------------------------------
        # SCROLL
        # --------------------------------------------------

        print(
            "\nScrolling to trigger additional pages..."
        )

        for i in range(12):

            print(
                "Scroll",
                i + 1,
                "of 12"
            )

            try:

                page.evaluate(
                    "window.scrollBy(0, 1200)"
                )

            except Exception:
                pass

            page.wait_for_timeout(
                2000
            )

        # --------------------------------------------------
        # EXTRA WAIT
        # --------------------------------------------------

        print(
            "\nWaiting for final API responses..."
        )

        page.wait_for_timeout(
            10000
        )

        # --------------------------------------------------
        # CAPTURE CURRENT PAGE DATA
        # --------------------------------------------------

        print(
            "\nCapturing page information..."
        )

        page_info = {}

        try:

            page_info[
                "title"
            ] = page.title()

        except Exception:

            page_info[
                "title"
            ] = ""

        try:

            page_info[
                "url"
            ] = page.url

        except Exception:

            page_info[
                "url"
            ] = ""

        try:

            page_info[
                "body_text"
            ] = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )[:50000]

        except Exception:

            page_info[
                "body_text"
            ] = ""

        # --------------------------------------------------
        # SAVE DEBUG
        # --------------------------------------------------

        final_data = {

            "generated_at":
                datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),

            "page":
                page_info,

            "discover_requests":
                requests_seen,

            "discover_responses":
                captured_responses,

            "response_count":
                len(captured_responses)
        }

        save_debug(
            final_data
        )

        # --------------------------------------------------
        # SCREENSHOT
        # --------------------------------------------------

        try:

            page.screenshot(
                path="bms_discover_page.png",
                full_page=True
            )

            print(
                "\nScreenshot saved:"
            )

            print(
                "bms_discover_page.png"
            )

        except Exception as e:

            print(
                "Screenshot error:",
                e
            )

        browser.close()

    # --------------------------------------------------
    # FINAL
    # --------------------------------------------------

    print(
        "\n"
        + "=" * 90
    )

    print(
        "CAPTURE COMPLETE"
    )

    print(
        "=" * 90
    )

    print(
        "Discover requests:",
        len(requests_seen)
    )

    print(
        "Discover responses:",
        len(captured_responses)
    )

    print(
        "\nDEBUG FILE:"
    )

    print(
        DEBUG_FILE
    )

    if len(captured_responses) == 0:

        print(
            "\nWARNING:"
        )

        print(
            "No /api/explore/v1/discover/ "
            "responses were captured."
        )

        print(
            "This means BookMyShow may be "
            "loading the data through another "
            "mechanism."
        )

    else:

        print(
            "\nSUCCESS:"
        )

        print(
            "The actual Discover API responses "
            "have been captured."
        )

    print(
        "\nNow download bms_discover_debug.json "
        "from the GitHub Actions artifact."
    )


if __name__ == "__main__":
    run()
