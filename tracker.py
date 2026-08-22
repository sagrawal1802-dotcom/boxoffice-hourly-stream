import os
import json
import re
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
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

DEBUG_FILE = "district_kurla_debug.json"


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def normalise(value):
    if value is None:
        return ""

    return str(value).strip().lower()


def is_toxic_text(value):

    if value is None:
        return False

    text = normalise(value)

    return (
        "toxic" in text
        or "fairy tale for grown" in text
    )


def looks_like_time(value):

    if value is None:
        return False

    text = str(value)

    patterns = [
        r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b",
        r"\b\d{1,2}:\d{2}\b"
    ]

    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in patterns
    )


def looks_like_id(key, value):

    if value is None:
        return False

    key = normalise(key)

    important = [
        "showid",
        "show_id",
        "sessionid",
        "session_id",
        "eventid",
        "event_id",
        "scheduleid",
        "schedule_id",
        "session",
        "show"
    ]

    return any(
        x in key
        for x in important
    )


def safe_json(value):

    try:
        return json.dumps(
            value,
            ensure_ascii=False
        )
    except Exception:
        return str(value)


# ============================================================
# RECURSIVE JSON SEARCH
# ============================================================

def recursively_find_toxic(
    obj,
    path="$",
    results=None
):

    if results is None:
        results = []

    try:

        if isinstance(obj, dict):

            # ------------------------------------------------
            # Check whether this entire object contains Toxic
            # ------------------------------------------------

            object_text = safe_json(obj)

            if is_toxic_text(object_text):

                results.append({
                    "path": path,
                    "object": obj
                })

            # ------------------------------------------------
            # Continue through every key
            # ------------------------------------------------

            for key, value in obj.items():

                current_path = (
                    f"{path}.{key}"
                )

                # Interesting IDs
                if looks_like_id(
                    key,
                    value
                ):

                    results.append({
                        "path": current_path,
                        "type": "identifier",
                        "key": key,
                        "value": value
                    })

                # Times
                if looks_like_time(value):

                    results.append({
                        "path": current_path,
                        "type": "time",
                        "key": key,
                        "value": value
                    })

                # Continue recursively
                recursively_find_toxic(
                    value,
                    current_path,
                    results
                )

        elif isinstance(obj, list):

            for index, value in enumerate(obj):

                current_path = (
                    f"{path}[{index}]"
                )

                recursively_find_toxic(
                    value,
                    current_path,
                    results
                )

        elif isinstance(obj, str):

            if is_toxic_text(obj):

                results.append({
                    "path": path,
                    "type": "text",
                    "value": obj
                })

    except Exception:
        pass

    return results


# ============================================================
# EXTRACT POSSIBLE SHOW OBJECTS
# ============================================================

def extract_show_candidates(obj):

    candidates = []

    def walk(value, path="$"):

        try:

            if isinstance(value, dict):

                keys = {
                    normalise(k)
                    for k in value.keys()
                }

                # --------------------------------------------
                # Indicators that this could be a show object
                # --------------------------------------------

                show_indicators = 0

                if any(
                    x in keys
                    for x in [
                        "showid",
                        "show_id",
                        "sessionid",
                        "session_id",
                        "scheduleid",
                        "schedule_id"
                    ]
                ):
                    show_indicators += 2

                if any(
                    x in keys
                    for x in [
                        "showtime",
                        "show_time",
                        "starttime",
                        "start_time",
                        "time"
                    ]
                ):
                    show_indicators += 1

                if any(
                    x in keys
                    for x in [
                        "movie",
                        "moviename",
                        "movie_name",
                        "movietitle",
                        "movie_title"
                    ]
                ):
                    show_indicators += 1

                if any(
                    x in keys
                    for x in [
                        "screen",
                        "screenname",
                        "screen_name",
                        "auditorium",
                        "audi"
                    ]
                ):
                    show_indicators += 1

                if show_indicators >= 2:

                    text = safe_json(
                        value
                    )

                    if is_toxic_text(text):

                        candidates.append({
                            "path": path,
                            "data": value
                        })

                # Continue
                for key, child in value.items():

                    walk(
                        child,
                        f"{path}.{key}"
                    )

            elif isinstance(value, list):

                for index, child in enumerate(value):

                    walk(
                        child,
                        f"{path}[{index}]"
                    )

        except Exception:
            pass

    walk(obj)

    return candidates


# ============================================================
# SEAT INFORMATION SEARCH
# ============================================================

def find_seat_information(
    obj,
    path="$",
    results=None
):

    if results is None:
        results = []

    seat_keywords = [
        "seat",
        "seats",
        "available",
        "availability",
        "booked",
        "blocked",
        "sold",
        "capacity",
        "total_seat",
        "available_seat",
        "booked_seat",
        "seatmap",
        "seat_map"
    ]

    try:

        if isinstance(obj, dict):

            for key, value in obj.items():

                key_lower = normalise(
                    key
                )

                if any(
                    keyword in key_lower
                    for keyword in seat_keywords
                ):

                    results.append({
                        "path": (
                            f"{path}.{key}"
                        ),
                        "key": key,
                        "value": value
                    })

                find_seat_information(
                    value,
                    f"{path}.{key}",
                    results
                )

        elif isinstance(obj, list):

            for index, value in enumerate(obj):

                find_seat_information(
                    value,
                    f"{path}[{index}]",
                    results
                )

    except Exception:
        pass

    return results


# ============================================================
# MAIN
# ============================================================

def run():

    print(
        "\n=============================================="
    )

    print(
        "DISTRICT TOXIC 26 AUGUST DIAGNOSTIC TRACKER"
    )

    print(
        "==============================================\n"
    )

    # ========================================================
    # GOOGLE SHEETS
    # ========================================================

    print(
        "1. Connecting to Google Sheets..."
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

    # ========================================================
    # TIMESTAMP
    # ========================================================

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

    # ========================================================
    # DEBUG STRUCTURE
    # ========================================================

    debug = {
        "timestamp_ist": now_ist,
        "target_date": TARGET_DATE,
        "target_movie": TARGET_MOVIE,
        "theatre": THEATRE_NAME,
        "url": DISTRICT_URL,
        "requests": [],
        "responses": [],
        "toxic_matches": [],
        "show_candidates": [],
        "seat_matches": [],
        "dom_text": ""
    }

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    print(
        "\n2. Launching District browser..."
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
                "height": 900
            },

            locale="en-IN",

            timezone_id="Asia/Kolkata"
        )

        page = context.new_page()

        # ====================================================
        # REQUEST LISTENER
        # ====================================================

        def on_request(request):

            try:

                resource_type = (
                    request.resource_type
                )

                if resource_type not in [
                    "xhr",
                    "fetch"
                ]:
                    return

                debug["requests"].append({
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(
                        request.headers
                    ),
                    "post_data": request.post_data
                })

                print(
                    "[REQUEST]",
                    request.method,
                    request.url
                )

            except Exception:
                pass

        page.on(
            "request",
            on_request
        )

        # ====================================================
        # RESPONSE LISTENER
        # ====================================================

        def on_response(response):

            try:

                if response.request.resource_type not in [
                    "xhr",
                    "fetch"
                ]:
                    return

                content_type = (
                    response.headers
                    .get(
                        "content-type",
                        ""
                    )
                    .lower()
                )

                url = response.url

                print(
                    "[RESPONSE]",
                    response.status,
                    url
                )

                # --------------------------------------------
                # Only JSON
                # --------------------------------------------

                if (
                    "json" not in content_type
                    and "javascript" not in content_type
                ):
                    return

                try:

                    body = response.text()

                except Exception:

                    return

                if not body:
                    return

                # Save response
                response_record = {
                    "url": url,
                    "status": response.status,
                    "content_type": content_type,
                    "body": body[:1000000]
                }

                # --------------------------------------------
                # Parse JSON
                # --------------------------------------------

                try:

                    parsed = json.loads(
                        body
                    )

                    response_record[
                        "parsed_json"
                    ] = parsed

                    # Search Toxic
                    toxic_matches = (
                        recursively_find_toxic(
                            parsed
                        )
                    )

                    if toxic_matches:

                        debug[
                            "toxic_matches"
                        ].extend(
                            toxic_matches
                        )

                        # Show candidates
                        candidates = (
                            extract_show_candidates(
                                parsed
                            )
                        )

                        debug[
                            "show_candidates"
                        ].extend(
                            candidates
                        )

                    # Seat information
                    seat_matches = (
                        find_seat_information(
                            parsed
                        )
                    )

                    if seat_matches:

                        debug[
                            "seat_matches"
                        ].extend(
                            [
                                {
                                    "url": url,
                                    "status":
                                        response.status,
                                    "matches":
                                        seat_matches[:500]
                                }
                            ]
                        )

                except Exception:

                    # Not valid JSON
                    pass

                debug[
                    "responses"
                ].append(
                    response_record
                )

            except Exception as e:

                print(
                    "Response handler error:",
                    e
                )

        page.on(
            "response",
            on_response
        )

        # ====================================================
        # OPEN DISTRICT
        # ====================================================

        print(
            "\n3. Opening:"
        )

        print(
            DISTRICT_URL
        )

        try:

            page.goto(
                DISTRICT_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as e:

            print(
                "Navigation error:",
                e
            )

        # Wait for API calls
        page.wait_for_timeout(
            7000
        )

        # ====================================================
        # SCROLL PAGE
        # ====================================================

        print(
            "\n4. Scrolling page..."
        )

        for i in range(8):

            try:

                page.mouse.wheel(
                    0,
                    1200
                )

            except Exception:
                pass

            page.wait_for_timeout(
                1500
            )

        # ====================================================
        # EXTRA WAIT
        # ====================================================

        page.wait_for_timeout(
            5000
        )

        # ====================================================
        # CAPTURE DOM TEXT
        # ====================================================

        print(
            "\n5. Capturing rendered page..."
        )

        try:

            debug["dom_text"] = (
                page.locator(
                    "body"
                ).inner_text()
            )

        except Exception:
            pass

        # ====================================================
        # PRINT TOXIC OCCURRENCES
        # ====================================================

        dom_text = debug[
            "dom_text"
        ]

        print(
            "\nToxic present in DOM:",
            is_toxic_text(dom_text)
        )

        if is_toxic_text(dom_text):

            positions = [
                m.start()
                for m in re.finditer(
                    "toxic",
                    dom_text,
                    re.IGNORECASE
                )
            ]

            for pos in positions[:20]:

                start = max(
                    0,
                    pos - 300
                )

                end = min(
                    len(dom_text),
                    pos + 700
                )

                print(
                    "\n--- TOXIC DOM CONTEXT ---"
                )

                print(
                    dom_text[start:end]
                )

        # ====================================================
        # CLOSE
        # ====================================================

        browser.close()

    # ========================================================
    # DEDUPLICATE
    # ========================================================

    print(
        "\n6. Processing captured data..."
    )

    unique_candidates = []

    seen = set()

    for candidate in debug[
        "show_candidates"
    ]:

        data = candidate.get(
            "data"
        )

        if not isinstance(
            data,
            dict
        ):
            continue

        key = safe_json(
            data
        )

        if key in seen:
            continue

        seen.add(key)

        unique_candidates.append(
            candidate
        )

    debug[
        "show_candidates"
    ] = unique_candidates

    # ========================================================
    # PRINT SUMMARY
    # ========================================================

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
        "XHR / Fetch requests:",
        len(debug["requests"])
    )

    print(
        "JSON responses:",
        len(debug["responses"])
    )

    print(
        "Toxic matches:",
        len(debug["toxic_matches"])
    )

    print(
        "Possible show objects:",
        len(debug["show_candidates"])
    )

    print(
        "Seat-related responses:",
        len(debug["seat_matches"])
    )

    # ========================================================
    # PRINT POSSIBLE SHOWS
    # ========================================================

    print(
        "\nPOSSIBLE TOXIC SHOW OBJECTS:"
    )

    for i, candidate in enumerate(
        debug["show_candidates"][:100],
        1
    ):

        print(
            f"\n--- SHOW CANDIDATE {i} ---"
        )

        print(
            "PATH:",
            candidate.get(
                "path"
            )
        )

        print(
            json.dumps(
                candidate.get(
                    "data"
                ),
                ensure_ascii=False,
                indent=2
            )[:5000]
        )

    # ========================================================
    # WRITE DEBUG FILE
    # ========================================================

    print(
        "\n7. Writing debug file..."
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
        "Debug file created:",
        DEBUG_FILE
    )

    # ========================================================
    # GOOGLE SHEET
    # ========================================================

    print(
        "\n8. Writing diagnostic information to sheet..."
    )

    # Create header if empty
    existing = sheet.get_all_values()

    if not existing:

        sheet.append_row(
            [
                "Snapshot Timestamp (IST)",
                "Show Date",
                "Theatre",
                "Movie Title",
                "Language",
                "Format",
                "Screen / Audi",
                "Show Time",
                "Show ID",
                "Session ID",
                "Total Seats",
                "Booked Seats",
                "Available Seats",
                "Occupancy %",
                "Data Status"
            ],
            value_input_option="USER_ENTERED"
        )

    # --------------------------------------------------------
    # We intentionally DON'T invent seat numbers.
    # --------------------------------------------------------

    if debug[
        "show_candidates"
    ]:

        for candidate in debug[
            "show_candidates"
        ]:

            data = candidate.get(
                "data",
                {}
            )

            if not isinstance(
                data,
                dict
            ):
                continue

            # Attempt only generic field extraction
            show_time = ""

            show_id = ""

            session_id = ""

            language = ""

            format_value = ""

            screen = ""

            for key, value in data.items():

                k = normalise(
                    key
                )

                if (
                    not show_time
                    and (
                        "showtime" in k
                        or "show_time" in k
                        or k == "time"
                        or "starttime" in k
                        or "start_time" in k
                    )
                ):

                    show_time = str(
                        value
                    )

                if (
                    not show_id
                    and (
                        k == "showid"
                        or k == "show_id"
                    )
                ):

                    show_id = str(
                        value
                    )

                if (
                    not session_id
                    and (
                        k == "sessionid"
                        or k == "session_id"
                    )
                ):

                    session_id = str(
                        value
                    )

                if (
                    not language
                    and "language" in k
                ):

                    language = str(
                        value
                    )

                if (
                    not format_value
                    and (
                        "format" in k
                        or "screenformat" in k
                    )
                ):

                    format_value = str(
                        value
                    )

                if (
                    not screen
                    and (
                        "screen" in k
                        or "audi" in k
                        or "auditorium" in k
                    )
                ):

                    screen = str(
                        value
                    )

            sheet.append_row(
                [
                    now_ist,
                    TARGET_DATE,
                    THEATRE_NAME,
                    TARGET_MOVIE,
                    language,
                    format_value,
                    screen,
                    show_time,
                    show_id,
                    session_id,
                    "",
                    "",
                    "",
                    "",
                    "Show detected - seat data not yet mapped"
                ],
                value_input_option="USER_ENTERED"
            )

    else:

        sheet.append_row(
            [
                now_ist,
                TARGET_DATE,
                THEATRE_NAME,
                TARGET_MOVIE,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "No show object detected - see district_kurla_debug.json"
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
        "IMPORTANT:"
    )

    print(
        "Upload district_kurla_debug.json after this run."
    )

    print(
        "That file will tell us the exact District response structure."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    run()
