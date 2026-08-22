import os
import json
import re
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

SHEET_TAB_NAME = "Toxic_26Aug"

URL = "https://bfilmy.pages.dev/District%20Advance/"

TARGET_DATE = "2026-08-26"

RAW_FILE = "bfilmy_full_capture.json"
MATCH_FILE = "bfilmy_toxic_matches.json"


HEADERS = [
    "Snapshot Timestamp (IST)",
    "Show Date",
    "State",
    "City",
    "Cinema Chain",
    "Theatre",
    "Movie",
    "Event Code",
    "Language",
    "Format",
    "Screen / Audi",
    "Show Time",
    "Total Seats",
    "Available Seats",
    "Booked / Sold Seats",
    "Occupancy %",
    "Source",
    "Status"
]


def ist_now():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=5, minutes=30)
    ).strftime("%Y-%m-%d %H:%M:%S")


def walk(obj, path="$"):
    yield path, obj

    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def stringify(obj):
    try:
        return json.dumps(
            obj,
            ensure_ascii=False
        ).lower()
    except Exception:
        return str(obj).lower()


def text(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def find_keywords(obj):

    s = stringify(obj)

    keywords = [
        "toxic",
        "fairy tale",
        "grown-ups",
        "grownups",
        "kurla",
        "market city",
        "pvr",
        "26-08-2026",
        "2026-08-26",
        "26/08/2026",
        "showtime",
        "show_time",
        "show time",
        "available",
        "booked",
        "seats",
        "seat"
    ]

    return [
        k for k in keywords
        if k in s
    ]


def compact(obj):

    if isinstance(obj, dict):

        result = {}

        for k, v in obj.items():

            if isinstance(v, (dict, list)):

                result[k] = v

            else:

                result[k] = v

        return result

    return obj


def connect_sheet():

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
            rows=5000,
            cols=len(HEADERS)
        )

        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

    values = sheet.get_all_values()

    if not values:

        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

    return sheet


def run():

    print(
        "\n=============================================="
    )

    print(
        "BFILMY RAW STRUCTURE DIAGNOSTIC"
    )

    print(
        "=============================================="
    )

    print(
        "Date:",
        TARGET_DATE
    )

    print(
        "URL:",
        URL
    )

    snapshot = ist_now()

    print(
        "\n1. Connecting to Google Sheets..."
    )

    sheet = connect_sheet()

    captured = []

    print(
        "\n2. Launching Chromium..."
    )

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

        def response_handler(response):

            try:

                content_type = response.headers.get(
                    "content-type",
                    ""
                ).lower()

                if "json" not in content_type:
                    return

                body = response.text()

                if not body:
                    return

                try:

                    data = json.loads(body)

                except Exception:

                    return

                captured.append({

                    "url": response.url,

                    "status": response.status,

                    "content_type": content_type,

                    "data": data

                })

            except Exception:
                pass

        page.on(
            "response",
            response_handler
        )

        print(
            "\n3. Opening BFilmy..."
        )

        try:

            response = page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response:

                print(
                    "HTTP status:",
                    response.status
                )

        except Exception as e:

            print(
                "Navigation error:",
                repr(e)
            )

        print(
            "\n4. Waiting..."
        )

        page.wait_for_timeout(
            10000
        )

        print(
            "\n5. Scrolling..."
        )

        for _ in range(20):

            try:

                page.mouse.wheel(
                    0,
                    1600
                )

            except Exception:
                pass

            page.wait_for_timeout(
                500
            )

        page.wait_for_timeout(
            5000
        )

        try:

            body = page.locator(
                "body"
            ).inner_text()

            print(
                "\nPage text:",
                len(body)
            )

            print(
                "Toxic in visible page:",
                "toxic" in body.lower()
            )

        except Exception:
            pass

        try:

            page.screenshot(
                path="bfilmy_full.png",
                full_page=True
            )

        except Exception:
            pass

        browser.close()

    print(
        "\n6. JSON responses captured:",
        len(captured)
    )

    # --------------------------------------------------------
    # SAVE EVERYTHING
    # --------------------------------------------------------

    with open(
        RAW_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            captured,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "Saved:",
        RAW_FILE
    )

    # --------------------------------------------------------
    # ANALYSE EVERY JSON RESPONSE
    # --------------------------------------------------------

    print(
        "\n=============================================="
    )

    print(
        "RESPONSE ANALYSIS"
    )

    print(
        "=============================================="
    )

    all_matches = []

    for response_number, response in enumerate(
        captured,
        start=1
    ):

        data = response["data"]

        print(
            f"\nJSON RESPONSE #{response_number}"
        )

        print(
            "URL:",
            response["url"]
        )

        print(
            "Status:",
            response["status"]
        )

        found = find_keywords(
            data
        )

        print(
            "Keywords:",
            ", ".join(found)
            if found
            else "NONE"
        )

        # ----------------------------------------------------
        # Every object containing relevant words
        # ----------------------------------------------------

        for path, obj in walk(data):

            if not isinstance(
                obj,
                (dict, list)
            ):

                continue

            keywords = find_keywords(
                obj
            )

            if not keywords:
                continue

            # Don't save gigantic root structures repeatedly
            if isinstance(obj, dict):

                if len(obj) > 100:

                    continue

            match = {

                "response_number":
                    response_number,

                "url":
                    response["url"],

                "path":
                    path,

                "keywords":
                    keywords,

                "object":
                    compact(obj)

            }

            all_matches.append(
                match
            )

            print(
                "\nMATCH:",
                path
            )

            print(
                "Keywords:",
                keywords
            )

            try:

                preview = json.dumps(
                    obj,
                    ensure_ascii=False
                )

                if len(preview) > 2000:

                    preview = preview[:2000] + "..."

                print(
                    preview
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # SAVE MATCHES
    # --------------------------------------------------------

    with open(
        MATCH_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            all_matches,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "\n=============================================="
    )

    print(
        "DIAGNOSTIC SUMMARY"
    )

    print(
        "=============================================="
    )

    print(
        "JSON responses:",
        len(captured)
    )

    print(
        "Relevant objects:",
        len(all_matches)
    )

    print(
        "Full capture:",
        RAW_FILE
    )

    print(
        "Relevant matches:",
        MATCH_FILE
    )

    # --------------------------------------------------------
    # GOOGLE SHEET STATUS
    # --------------------------------------------------------

    sheet.append_row(
        [
            snapshot,
            TARGET_DATE,
            "",
            "",
            "",
            "",
            "Toxic",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "BFilmy",
            f"Diagnostic: {len(captured)} JSON responses; {len(all_matches)} relevant objects"
        ],
        value_input_option="USER_ENTERED"
    )

    print(
        "\n=============================================="
    )

    print(
        "RUN COMPLETE"
    )

    print(
        "=============================================="
    )

    print(
        "Upload/download these two files from the GitHub Action:"
    )

    print(
        RAW_FILE
    )

    print(
        MATCH_FILE
    )


if __name__ == "__main__":
    run()
