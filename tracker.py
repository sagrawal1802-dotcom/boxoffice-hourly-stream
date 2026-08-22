import os
import json
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

THEATRE_NAME = "PVR Market City, Kurla (W), Mumbai"

DISTRICT_URL = (
    "https://www.district.in/movies/"
    "pvr-market-city-kurla-w-mumbai-in-mumbai-CD1022270"
    f"?date={TARGET_DATE}"
)

DEBUG_FILE = "district_page_debug.json"


# ============================================================
# MAIN
# ============================================================

def run():

    print("\n==============================================")
    print("DISTRICT PAGE DIAGNOSTIC")
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
            cols=15
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
        "target_date": TARGET_DATE,
        "target_movie": TARGET_MOVIE,
        "theatre": THEATRE_NAME,
        "requested_url": DISTRICT_URL,

        "page": {},
        "console": [],
        "page_errors": [],
        "requests": [],
        "responses": [],
        "cookies": [],
        "html": "",
        "body_text": ""
    }

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

    print("\n2. Launching Chromium...")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=True,

            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
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

            timezone_id="Asia/Kolkata",

            java_script_enabled=True,

            ignore_https_errors=False
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Console
        # ----------------------------------------------------

        def on_console(msg):

            try:

                entry = {
                    "type": msg.type,
                    "text": msg.text
                }

                debug["console"].append(
                    entry
                )

                print(
                    "[CONSOLE]",
                    msg.type,
                    msg.text[:500]
                )

            except Exception:
                pass

        page.on(
            "console",
            on_console
        )

        # ----------------------------------------------------
        # Page errors
        # ----------------------------------------------------

        def on_page_error(error):

            try:

                text = str(error)

                debug[
                    "page_errors"
                ].append(
                    text
                )

                print(
                    "[PAGE ERROR]",
                    text
                )

            except Exception:
                pass

        page.on(
            "pageerror",
            on_page_error
        )

        # ----------------------------------------------------
        # Requests
        # ----------------------------------------------------

        def on_request(request):

            try:

                debug[
                    "requests"
                ].append({
                    "method": request.method,
                    "url": request.url,
                    "resource_type":
                        request.resource_type
                })

                print(
                    "[REQUEST]",
                    request.resource_type,
                    request.method,
                    request.url[:300]
                )

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        # ----------------------------------------------------
        # Responses
        # ----------------------------------------------------

        def on_response(response):

            try:

                debug[
                    "responses"
                ].append({
                    "status": response.status,
                    "url": response.url,
                    "resource_type":
                        response.request.resource_type,
                    "content_type":
                        response.headers.get(
                            "content-type",
                            ""
                        )
                })

                # Print non-success responses
                if response.status >= 400:

                    print(
                        "[HTTP ERROR]",
                        response.status,
                        response.url[:400]
                    )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )

        # ----------------------------------------------------
        # Open District
        # ----------------------------------------------------

        print("\n3. Opening District URL:")
        print(DISTRICT_URL)

        response = None

        try:

            response = page.goto(
                DISTRICT_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response:

                print(
                    "\nInitial HTTP status:",
                    response.status
                )

                print(
                    "Initial response URL:",
                    response.url
                )

                debug["page"][
                    "initial_status"
                ] = response.status

                debug["page"][
                    "initial_response_url"
                ] = response.url

        except Exception as e:

            print(
                "\nPAGE.GOTO ERROR:",
                repr(e)
            )

            debug["page"][
                "goto_error"
            ] = repr(e)

        # ----------------------------------------------------
        # Wait
        # ----------------------------------------------------

        print(
            "\n4. Waiting for District JavaScript..."
        )

        page.wait_for_timeout(
            10000
        )

        # ----------------------------------------------------
        # Current URL
        # ----------------------------------------------------

        try:

            debug["page"][
                "final_url"
            ] = page.url

            print(
                "\nFinal URL:",
                page.url
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        try:

            title = page.title()

            debug["page"][
                "title"
            ] = title

            print(
                "Page title:",
                title
            )

        except Exception as e:

            print(
                "Title error:",
                repr(e)
            )

        # ----------------------------------------------------
        # HTML
        # ----------------------------------------------------

        print(
            "\n5. Capturing HTML..."
        )

        try:

            html = page.content()

            debug[
                "html"
            ] = html[:3000000]

            print(
                "HTML size:",
                len(html)
            )

            print(
                "HTML preview:"
            )

            print(
                html[:2000]
            )

        except Exception as e:

            print(
                "HTML error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Body text
        # ----------------------------------------------------

        print(
            "\n6. Capturing visible body text..."
        )

        try:

            body_text = page.locator(
                "body"
            ).inner_text(
                timeout=10000
            )

            debug[
                "body_text"
            ] = body_text[:500000]

            print(
                "Body text length:",
                len(body_text)
            )

            print(
                "\nBODY TEXT:"
            )

            print(
                body_text[:10000]
            )

        except Exception as e:

            print(
                "Body text error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Screenshot
        # ----------------------------------------------------

        print(
            "\n7. Taking screenshot..."
        )

        try:

            page.screenshot(
                path="district_page.png",
                full_page=True
            )

            debug["page"][
                "screenshot"
            ] = "district_page.png"

            print(
                "Screenshot saved."
            )

        except Exception as e:

            print(
                "Screenshot error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Cookies
        # ----------------------------------------------------

        print(
            "\n8. Capturing cookies..."
        )

        try:

            cookies = context.cookies()

            # Only save safe metadata.
            debug[
                "cookies"
            ] = [
                {
                    "name": c.get("name"),
                    "domain": c.get("domain"),
                    "path": c.get("path"),
                    "expires": c.get("expires")
                }
                for c in cookies
            ]

            print(
                "Cookies:",
                len(cookies)
            )

        except Exception as e:

            print(
                "Cookie error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Browser local storage keys
        # ----------------------------------------------------

        print(
            "\n9. Checking local storage..."
        )

        try:

            local_storage = page.evaluate(
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
            ] = local_storage

            print(
                "Local storage keys:",
                list(
                    local_storage.keys()
                )
            )

        except Exception as e:

            print(
                "Local storage error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Session storage
        # ----------------------------------------------------

        print(
            "\n10. Checking session storage..."
        )

        try:

            session_storage = page.evaluate(
                """
                () => {
                    const result = {};
                    for (
                        let i = 0;
                        i < sessionStorage.length;
                        i++
                    ) {
                        const key =
                            sessionStorage.key(i);

                        result[key] =
                            sessionStorage.getItem(key);
                    }
                    return result;
                }
                """
            )

            debug["page"][
                "session_storage"
            ] = session_storage

            print(
                "Session storage keys:",
                list(
                    session_storage.keys()
                )
            )

        except Exception as e:

            print(
                "Session storage error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Meta information
        # ----------------------------------------------------

        print(
            "\n11. Checking page metadata..."
        )

        try:

            metadata = page.evaluate(
                """
                () => {
                    return {
                        readyState:
                            document.readyState,

                        visibility:
                            document.visibilityState,

                        charset:
                            document.characterSet,

                        referrer:
                            document.referrer,

                        domain:
                            document.domain,

                        scripts:
                            Array.from(
                                document.scripts
                            ).map(
                                s => s.src
                            ).filter(Boolean),

                        links:
                            Array.from(
                                document.querySelectorAll(
                                    "link"
                                )
                            ).map(
                                l => l.href
                            ).filter(Boolean)
                    };
                }
                """
            )

            debug["page"][
                "metadata"
            ] = metadata

            print(
                json.dumps(
                    metadata,
                    indent=2
                )[:10000]
            )

        except Exception as e:

            print(
                "Metadata error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Wait again for late network
        # ----------------------------------------------------

        print(
            "\n12. Final 5-second network wait..."
        )

        page.wait_for_timeout(
            5000
        )

        browser.close()

    # ========================================================
    # SAVE DEBUG FILE
    # ========================================================

    print(
        "\n13. Saving diagnostic file..."
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
        "\n14. Writing diagnostic status to Google Sheet..."
    )

    header = [
        "Snapshot Timestamp (IST)",
        "Show Date",
        "Theatre",
        "Movie",
        "HTTP Status",
        "Final URL",
        "Page Title",
        "HTML Size",
        "Body Text Size",
        "XHR/Fetch Requests",
        "Total Requests",
        "HTTP Errors",
        "Page Errors",
        "Toxic Found",
        "Diagnostic File"
    ]

    existing = sheet.get_all_values()

    if not existing:

        sheet.append_row(
            header,
            value_input_option="USER_ENTERED"
        )

    initial_status = debug[
        "page"
    ].get(
        "initial_status",
        ""
    )

    final_url = debug[
        "page"
    ].get(
        "final_url",
        ""
    )

    title = debug[
        "page"
    ].get(
        "title",
        ""
    )

    html_size = len(
        debug.get(
            "html",
            ""
        )
    )

    body_size = len(
        debug.get(
            "body_text",
            ""
        )
    )

    xhr_fetch = sum(
        1
        for r in debug[
            "requests"
        ]
        if r.get(
            "resource_type"
        ) in [
            "xhr",
            "fetch"
        ]
    )

    http_errors = sum(
        1
        for r in debug[
            "responses"
        ]
        if r.get(
            "status",
            0
        ) >= 400
    )

    toxic_found = (
        "YES"
        if "toxic" in (
            debug.get(
                "body_text",
                ""
            ).lower()
        )
        else "NO"
    )

    sheet.append_row(
        [
            now_ist,
            TARGET_DATE,
            THEATRE_NAME,
            TARGET_MOVIE,
            initial_status,
            final_url,
            title,
            html_size,
            body_size,
            xhr_fetch,
            len(
                debug[
                    "requests"
                ]
            ),
            http_errors,
            len(
                debug[
                    "page_errors"
                ]
            ),
            toxic_found,
            DEBUG_FILE
        ],
        value_input_option="USER_ENTERED"
    )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print(
        "\n=============================================="
    )

    print(
        "DIAGNOSTIC COMPLETE"
    )

    print(
        "=============================================="
    )

    print(
        "HTTP Status:",
        initial_status
    )

    print(
        "Final URL:",
        final_url
    )

    print(
        "Page Title:",
        title
    )

    print(
        "HTML Size:",
        html_size
    )

    print(
        "Body Text Size:",
        body_size
    )

    print(
        "Total Requests:",
        len(
            debug["requests"]
        )
    )

    print(
        "XHR/Fetch:",
        xhr_fetch
    )

    print(
        "HTTP Errors:",
        http_errors
    )

    print(
        "Page Errors:",
        len(
            debug[
                "page_errors"
            ]
        )
    )

    print(
        "Toxic Found:",
        toxic_found
    )

    print(
        "\nFiles created:"
    )

    print(
        "district_page_debug.json"
    )

    print(
        "district_page.png"
    )

    print(
        "\nUpload district_page_debug.json here."
    )

    print(
        "If necessary, also upload district_page.png."
    )


if __name__ == "__main__":
    run()
