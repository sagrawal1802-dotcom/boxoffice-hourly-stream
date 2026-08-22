import os
import json
import re
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

SHEET_TAB_NAME = "Kurla_26Aug"

TARGET_DATE = "2026-08-26"
TARGET_MOVIE = "Toxic"
TARGET_THEATRE = "PVR Market City, Kurla (W), Mumbai"

BFILMY_URL = "https://bfilmy.pages.dev/District%20Advance/"

DEBUG_FILE = "bfilmy_debug.json"


# ============================================================
# HELPERS
# ============================================================

def contains_toxic(value):
    if value is None:
        return False

    text = str(value).lower()

    return (
        "toxic" in text
        or "fairy tale for grown" in text
    )


def safe_json(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=False
        )
    except Exception:
        return str(value)


def search_json(obj, path="$", results=None):

    if results is None:
        results = []

    try:

        if isinstance(obj, dict):

            for key, value in obj.items():

                current_path = f"{path}.{key}"

                # Search key/value itself
                if contains_toxic(key) or contains_toxic(value):

                    results.append({
                        "path": current_path,
                        "key": key,
                        "value": value
                    })

                search_json(
                    value,
                    current_path,
                    results
                )

        elif isinstance(obj, list):

            for i, value in enumerate(obj):

                search_json(
                    value,
                    f"{path}[{i}]",
                    results
                )

        elif isinstance(obj, str):

            if contains_toxic(obj):

                results.append({
                    "path": path,
                    "value": obj
                })

    except Exception:
        pass

    return results


# ============================================================
# MAIN
# ============================================================

def run():

    print("\n==============================================")
    print("BFILMY DISTRICT ADVANCE BOOKING DIAGNOSTIC")
    print("==============================================\n")

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

    print("1. Connecting to Google Sheets...")

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

    try:
        sheet = spreadsheet.worksheet(
            SHEET_TAB_NAME
        )
    except gspread.exceptions.WorksheetNotFound:

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=1000,
            cols=20
        )

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    now_ist = (
        datetime.datetime.now(
            datetime.timezone.utc
        )
        + datetime.timedelta(
            hours=5,
            minutes=30
        )
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # Debug object
    # --------------------------------------------------------

    debug = {
        "timestamp_ist": now_ist,
        "source": BFILMY_URL,
        "target_date": TARGET_DATE,
        "target_movie": TARGET_MOVIE,
        "target_theatre": TARGET_THEATRE,
        "requests": [],
        "responses": [],
        "json_matches": [],
        "dom_text": "",
        "page": {}
    }

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    print("\n2. Launching Chromium...")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage"
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
                "height": 1000
            },

            locale="en-IN",

            timezone_id="Asia/Kolkata"
        )

        page = context.new_page()

        # ----------------------------------------------------
        # REQUESTS
        # ----------------------------------------------------

        def on_request(request):

            try:

                debug["requests"].append({
                    "method": request.method,
                    "url": request.url,
                    "resource_type":
                        request.resource_type
                })

                print(
                    "[REQUEST]",
                    request.resource_type,
                    request.method,
                    request.url[:500]
                )

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        # ----------------------------------------------------
        # RESPONSES
        # ----------------------------------------------------

        def on_response(response):

            try:

                content_type = (
                    response.headers.get(
                        "content-type",
                        ""
                    ).lower()
                )

                record = {
                    "status": response.status,
                    "url": response.url,
                    "resource_type":
                        response.request.resource_type,
                    "content_type":
                        content_type
                }

                # ------------------------------------------------
                # JSON
                # ------------------------------------------------

                if "json" in content_type:

                    try:

                        body = response.text()

                        parsed = json.loads(
                            body
                        )

                        record["json"] = parsed

                        matches = search_json(
                            parsed
                        )

                        if matches:

                            print(
                                "\n*** TOXIC FOUND IN JSON ***"
                            )

                            print(
                                response.url
                            )

                            debug[
                                "json_matches"
                            ].append({
                                "url":
                                    response.url,
                                "matches":
                                    matches
                            })

                    except Exception as e:

                        record[
                            "json_error"
                        ] = str(e)

                debug[
                    "responses"
                ].append(record)

            except Exception as e:

                print(
                    "Response error:",
                    e
                )

        page.on(
            "response",
            on_response
        )

        # ====================================================
        # OPEN BFILMY
        # ====================================================

        print(
            "\n3. Opening BFilmy:"
        )

        print(
            BFILMY_URL
        )

        try:

            response = page.goto(
                BFILMY_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response:

                debug["page"][
                    "status"
                ] = response.status

                debug["page"][
                    "response_url"
                ] = response.url

                print(
                    "HTTP status:",
                    response.status
                )

                print(
                    "Response URL:",
                    response.url
                )

        except Exception as e:

            print(
                "Navigation error:",
                repr(e)
            )

            debug["page"][
                "navigation_error"
            ] = repr(e)

        # ----------------------------------------------------
        # Wait
        # ----------------------------------------------------

        print(
            "\n4. Waiting for BFilmy application..."
        )

        page.wait_for_timeout(
            8000
        )

        # ----------------------------------------------------
        # Scroll
        # ----------------------------------------------------

        print(
            "\n5. Scrolling..."
        )

        for _ in range(8):

            try:

                page.mouse.wheel(
                    0,
                    1200
                )

            except Exception:
                pass

            page.wait_for_timeout(
                1000
            )

        # ----------------------------------------------------
        # Extra wait
        # ----------------------------------------------------

        page.wait_for_timeout(
            5000
        )

        # ====================================================
        # PAGE INFO
        # ====================================================

        print(
            "\n6. Reading page..."
        )

        try:

            debug["page"][
                "final_url"
            ] = page.url

            debug["page"][
                "title"
            ] = page.title()

            print(
                "Final URL:",
                page.url
            )

            print(
                "Title:",
                page.title()
            )

        except Exception:
            pass

        # ====================================================
        # BODY TEXT
        # ====================================================

        try:

            body = page.locator(
                "body"
            ).inner_text()

            debug[
                "dom_text"
            ] = body[:1000000]

            print(
                "\nBODY TEXT PREVIEW:"
            )

            print(
                body[:15000]
            )

            if contains_toxic(body):

                print(
                    "\n*** TOXIC FOUND IN PAGE ***"
                )

            else:

                print(
                    "\nToxic not found in visible page text."
                )

        except Exception as e:

            print(
                "Body error:",
                repr(e)
            )

        # ====================================================
        # HTML
        # ====================================================

        try:

            html = page.content()

            debug["page"][
                "html_size"
            ] = len(html)

            debug["page"][
                "html_preview"
            ] = html[:10000]

            print(
                "\nHTML size:",
                len(html)
            )

        except Exception:
            pass

        # ====================================================
        # SCREENSHOT
        # ====================================================

        try:

            page.screenshot(
                path="bfilmy_page.png",
                full_page=True
            )

            debug["page"][
                "screenshot"
            ] = "bfilmy_page.png"

            print(
                "Screenshot saved."
            )

        except Exception as e:

            print(
                "Screenshot error:",
                repr(e)
            )

        # ====================================================
        # LOCAL STORAGE
        # ====================================================

        try:

            storage = page.evaluate(
                """
                () => {
                    const result = {};

                    for (
                        let i = 0;
                        i < localStorage.length;
                        i++
                    ) {
                        const key =
                            localStorage.key(i);

                        result[key] =
                            localStorage.getItem(key);
                    }

                    return result;
                }
                """
            )

            debug["page"][
                "local_storage"
            ] = storage

            print(
                "\nLocalStorage keys:",
                list(storage.keys())
            )

        except Exception:
            pass

        browser.close()

    # ========================================================
    # SAVE DEBUG
    # ========================================================

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
        "Created:",
        DEBUG_FILE
    )

    # ========================================================
    # GOOGLE SHEET
    # ========================================================

    print(
        "\n8. Updating Google Sheet..."
    )

    existing = sheet.get_all_values()

    if not existing:

        sheet.append_row(
            [
                "Timestamp IST",
                "Date",
                "Theatre",
                "Movie",
                "Source",
                "HTTP Status",
                "Final URL",
                "Page Title",
                "Requests",
                "JSON Responses",
                "Toxic Found",
                "Status"
            ],
            value_input_option="USER_ENTERED"
        )

    toxic_found = (
        "YES"
        if (
            contains_toxic(
                debug.get(
                    "dom_text",
                    ""
                )
            )
            or len(
                debug.get(
                    "json_matches",
                    []
                )
            ) > 0
        )
        else "NO"
    )

    sheet.append_row(
        [
            now_ist,
            TARGET_DATE,
            TARGET_THEATRE,
            TARGET_MOVIE,
            BFILMY_URL,
            debug["page"].get(
                "status",
                ""
            ),
            debug["page"].get(
                "final_url",
                ""
            ),
            debug["page"].get(
                "title",
                ""
            ),
            len(
                debug["requests"]
            ),
            len(
                debug["responses"]
            ),
            toxic_found,
            "Diagnostic complete"
        ],
        value_input_option="USER_ENTERED"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print(
        "\n=============================================="
    )

    print(
        "BFILMY DIAGNOSTIC COMPLETE"
    )

    print(
        "=============================================="
    )

    print(
        "HTTP Status:",
        debug["page"].get(
            "status",
            ""
        )
    )

    print(
        "Final URL:",
        debug["page"].get(
            "final_url",
            ""
        )
    )

    print(
        "Page Title:",
        debug["page"].get(
            "title",
            ""
        )
    )

    print(
        "Requests:",
        len(
            debug["requests"]
        )
    )

    print(
        "Responses:",
        len(
            debug["responses"]
        )
    )

    print(
        "Toxic JSON matches:",
        len(
            debug["json_matches"]
        )
    )

    print(
        "Toxic in DOM:",
        toxic_found
    )

    print(
        "\nFiles:"
    )

    print(
        "bfilmy_debug.json"
    )

    print(
        "bfilmy_page.png"
    )

    print(
        "\nSend me the GitHub Actions output after this run."
    )


if __name__ == "__main__":
    run()
