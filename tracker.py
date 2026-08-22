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

SHEET_TAB_NAME = "Toxic_26Aug"

BFILMY_URL = "https://bfilmy.pages.dev/District%20Advance/"

TARGET_DATE = "2026-08-26"

TARGET_MOVIE = "Toxic"

TARGET_THEATRE = "PVR Market City, Kurla"

RAW_JSON_FILE = "bfilmy_toxic_raw.json"


# ============================================================
# EXCEL / GOOGLE SHEET HEADERS
# ============================================================

HEADERS = [
    "Snapshot Timestamp (IST)",
    "Show Date",
    "State",
    "City",
    "Cinema Chain",
    "Theatre",
    "Movie",
    "Language",
    "Format",
    "Screen / Audi",
    "Show Time",
    "Total Seats",
    "Available Seats",
    "Sold / Booked Seats",
    "Occupancy %",
    "Booking Source",
    "Data Status"
]


# ============================================================
# HELPERS
# ============================================================

def ist_now():

    return (
        datetime.datetime.now(
            datetime.timezone.utc
        )
        + datetime.timedelta(
            hours=5,
            minutes=30
        )
    )


def normalize(text):

    if text is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


def contains_toxic(value):

    text = normalize(value).lower()

    return (
        "toxic" in text
        or
        "fairy tale for grown" in text
    )


def is_number(value):

    if value is None:
        return False

    if isinstance(value, bool):
        return False

    if isinstance(value, (int, float)):
        return True

    text = normalize(value)

    return bool(
        re.fullmatch(
            r"\d+(?:\.\d+)?",
            text
        )
    )


def number(value):

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):

        return int(value)

    text = normalize(value)

    text = text.replace(
        ",",
        ""
    )

    match = re.search(
        r"\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        return int(
            float(
                match.group(0)
            )
        )
    except Exception:
        return None


def occupancy(booked, total):

    if total is None or total <= 0:
        return ""

    if booked is None:
        return ""

    return round(
        booked / total * 100,
        2
    )


def recursive_objects(obj):

    """
    Return every dictionary contained
    anywhere inside the JSON response.
    """

    results = []

    if isinstance(obj, dict):

        results.append(obj)

        for value in obj.values():

            results.extend(
                recursive_objects(value)
            )

    elif isinstance(obj, list):

        for value in obj:

            results.extend(
                recursive_objects(value)
            )

    return results


def key_value(obj, possible_keys):

    """
    Case-insensitive lookup of possible keys.
    """

    if not isinstance(obj, dict):
        return None

    lower_map = {
        str(k).lower(): v
        for k, v in obj.items()
    }

    for key in possible_keys:

        if key.lower() in lower_map:

            return lower_map[
                key.lower()
            ]

    return None


# ============================================================
# SEAT FIELD DETECTION
# ============================================================

TOTAL_KEYS = [
    "totalseats",
    "total_seats",
    "totalSeats",
    "capacity",
    "total",
    "seatcount",
    "seatCount",
    "totalSeatCount",
    "maxSeats"
]

AVAILABLE_KEYS = [
    "availableseats",
    "available_seats",
    "availableSeats",
    "avail_seats",
    "availSeats",
    "avail",
    "available",
    "curAvail",
    "currentAvailable",
    "remainingSeats",
    "remaining"
]

BOOKED_KEYS = [
    "bookedseats",
    "booked_seats",
    "bookedSeats",
    "soldseats",
    "sold_seats",
    "soldSeats",
    "ticketsSold",
    "tickets_sold",
    "booked",
    "sold"
]


def extract_seats(obj):

    total = number(
        key_value(
            obj,
            TOTAL_KEYS
        )
    )

    available = number(
        key_value(
            obj,
            AVAILABLE_KEYS
        )
    )

    booked = number(
        key_value(
            obj,
            BOOKED_KEYS
        )
    )

    # If total and available exist
    if total is not None and available is not None:

        if booked is None:

            booked = max(
                0,
                total - available
            )

    # If total and booked exist
    if total is not None and booked is not None:

        if available is None:

            available = max(
                0,
                total - booked
            )

    # Sanity checks
    if total is not None and total < 0:
        total = None

    if available is not None and available < 0:
        available = None

    if booked is not None and booked < 0:
        booked = None

    return (
        total,
        available,
        booked
    )


# ============================================================
# MOVIE / SHOW DETECTION
# ============================================================

def object_contains_toxic(obj):

    if not isinstance(obj, dict):
        return False

    for key, value in obj.items():

        if contains_toxic(key):
            return True

        if isinstance(
            value,
            (str, int, float)
        ):

            if contains_toxic(value):
                return True

    return False


def likely_show_object(obj):

    if not isinstance(obj, dict):
        return False

    keys = " ".join(
        str(k).lower()
        for k in obj.keys()
    )

    show_words = [
        "show",
        "showtime",
        "show_time",
        "timing",
        "starttime",
        "start_time",
        "seat",
        "audi",
        "screen",
        "cinema",
        "theatre",
        "theater"
    ]

    return any(
        word in keys
        for word in show_words
    )


def extract_text_field(
    obj,
    keys
):

    value = key_value(
        obj,
        keys
    )

    if value is None:
        return ""

    if isinstance(
        value,
        (dict, list)
    ):
        return ""

    return normalize(value)


# ============================================================
# SHOW ROW EXTRACTION
# ============================================================

def make_row(
    obj,
    snapshot
):

    if not isinstance(obj, dict):
        return None

    # --------------------------------------------------------
    # Movie
    # --------------------------------------------------------

    movie = extract_text_field(
        obj,
        [
            "movie",
            "movieName",
            "movie_name",
            "movieTitle",
            "movie_title",
            "title",
            "film",
            "filmName"
        ]
    )

    # --------------------------------------------------------
    # Theatre
    # --------------------------------------------------------

    theatre = extract_text_field(
        obj,
        [
            "theatre",
            "theater",
            "theatreName",
            "theaterName",
            "cinema",
            "cinemaName",
            "venue",
            "venueName"
        ]
    )

    # --------------------------------------------------------
    # City / State
    # --------------------------------------------------------

    city = extract_text_field(
        obj,
        [
            "city",
            "cityName"
        ]
    )

    state = extract_text_field(
        obj,
        [
            "state",
            "stateName"
        ]
    )

    # --------------------------------------------------------
    # Chain
    # --------------------------------------------------------

    chain = extract_text_field(
        obj,
        [
            "chain",
            "chainName",
            "cinemaChain",
            "cinema_chain",
            "brand",
            "brandName"
        ]
    )

    # --------------------------------------------------------
    # Language
    # --------------------------------------------------------

    language = extract_text_field(
        obj,
        [
            "language",
            "lang",
            "languageName"
        ]
    )

    # --------------------------------------------------------
    # Format
    # --------------------------------------------------------

    fmt = extract_text_field(
        obj,
        [
            "format",
            "screenFormat",
            "screen_format",
            "formatName",
            "experience"
        ]
    )

    # --------------------------------------------------------
    # Audi
    # --------------------------------------------------------

    audi = extract_text_field(
        obj,
        [
            "audi",
            "audiName",
            "audi_name",
            "screen",
            "screenName",
            "screen_name"
        ]
    )

    # --------------------------------------------------------
    # Show time
    # --------------------------------------------------------

    show_time = extract_text_field(
        obj,
        [
            "showTime",
            "show_time",
            "time",
            "timing",
            "startTime",
            "start_time"
        ]
    )

    # --------------------------------------------------------
    # Date
    # --------------------------------------------------------

    show_date = extract_text_field(
        obj,
        [
            "date",
            "showDate",
            "show_date",
            "bookingDate",
            "booking_date"
        ]
    )

    # --------------------------------------------------------
    # Seat information
    # --------------------------------------------------------

    total, available, booked = extract_seats(
        obj
    )

    # --------------------------------------------------------
    # Decide whether this is a useful object
    # --------------------------------------------------------

    has_show_information = any(
        [
            movie,
            theatre,
            show_time,
            audi,
            language,
            fmt
        ]
    )

    has_seat_information = any(
        [
            total is not None,
            available is not None,
            booked is not None
        ]
    )

    if not has_show_information and not has_seat_information:
        return None

    # --------------------------------------------------------
    # Movie filter
    # --------------------------------------------------------

    if movie:

        if not contains_toxic(movie):
            return None

    # If object itself has Toxic somewhere
    elif not object_contains_toxic(obj):

        return None

    # --------------------------------------------------------
    # Theatre filter
    # --------------------------------------------------------

    if theatre:

        if (
            "market city" not in theatre.lower()
            and
            "kurla" not in theatre.lower()
        ):

            return None

    # --------------------------------------------------------
    # Date filter
    # --------------------------------------------------------

    if show_date:

        date_digits = re.sub(
            r"\D",
            "",
            show_date
        )

        target_digits = re.sub(
            r"\D",
            "",
            TARGET_DATE
        )

        # Only reject if it clearly specifies another date
        if (
            len(date_digits) >= 8
            and
            target_digits not in date_digits
        ):

            return None

    # --------------------------------------------------------
    # Calculate missing seat value
    # --------------------------------------------------------

    if (
        total is not None
        and
        available is not None
        and
        booked is None
    ):

        booked = max(
            0,
            total - available
        )

    if (
        total is not None
        and
        booked is not None
        and
        available is None
    ):

        available = max(
            0,
            total - booked
        )

    occ = occupancy(
        booked,
        total
    )

    # --------------------------------------------------------
    # Default values
    # --------------------------------------------------------

    if not movie:
        movie = "Toxic: A Fairy Tale for Grown-ups"

    if not theatre:
        theatre = TARGET_THEATRE

    if not city:
        city = "Mumbai"

    if not state:
        state = "Maharashtra"

    if not chain:
        chain = "PVR INOX"

    return [
        snapshot,
        TARGET_DATE,
        state,
        city,
        chain,
        theatre,
        movie,
        language,
        fmt,
        audi,
        show_time,
        total if total is not None else "",
        available if available is not None else "",
        booked if booked is not None else "",
        occ,
        "BFilmy / District",
        "Seat data found"
        if has_seat_information
        else "Show found - seat data unavailable"
    ]


# ============================================================
# MAIN
# ============================================================

def run():

    print(
        "\n=============================================="
    )

    print(
        "TOXIC 26 AUGUST BFILMY TRACKER"
    )

    print(
        "==============================================\n"
    )

    snapshot = ist_now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

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

        print(
            "Creating sheet:",
            SHEET_TAB_NAME
        )

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=5000,
            cols=len(HEADERS)
        )

        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

    print(
        "\n2. Launching BFilmy..."
    )

    captured_json = []

    captured_text = []

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
        # Capture JSON responses
        # ----------------------------------------------------

        def on_response(response):

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

                    parsed = json.loads(
                        body
                    )

                except Exception:

                    return

                captured_json.append({
                    "url": response.url,
                    "status": response.status,
                    "data": parsed
                })

                print(
                    "[JSON]",
                    response.status,
                    response.url[:300]
                )

            except Exception:
                pass

        page.on(
            "response",
            on_response
        )

        # ----------------------------------------------------
        # Open BFilmy
        # ----------------------------------------------------

        print(
            "\n3. Opening:"
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

                print(
                    "HTTP:",
                    response.status
                )

        except Exception as e:

            print(
                "Navigation error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Wait for application
        # ----------------------------------------------------

        print(
            "\n4. Waiting for data..."
        )

        page.wait_for_timeout(
            10000
        )

        # ----------------------------------------------------
        # Scroll
        # ----------------------------------------------------

        print(
            "5. Scrolling page..."
        )

        for i in range(12):

            try:

                page.mouse.wheel(
                    0,
                    1500
                )

            except Exception:
                pass

            page.wait_for_timeout(
                800
            )

        # ----------------------------------------------------
        # Extra wait
        # ----------------------------------------------------

        page.wait_for_timeout(
            5000
        )

        # ----------------------------------------------------
        # DOM
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text()

            captured_text.append(
                body_text
            )

            print(
                "\nDOM length:",
                len(body_text)
            )

            if contains_toxic(
                body_text
            ):

                print(
                    "Toxic found in DOM."
                )

            else:

                print(
                    "Toxic not found in DOM."
                )

        except Exception as e:

            print(
                "DOM error:",
                repr(e)
            )

        # ----------------------------------------------------
        # Screenshot
        # ----------------------------------------------------

        try:

            page.screenshot(
                path="bfilmy_toxic.png",
                full_page=True
            )

        except Exception:
            pass

        browser.close()

    # ========================================================
    # PROCESS JSON
    # ========================================================

    print(
        "\n6. Processing captured JSON..."
    )

    print(
        "JSON responses:",
        len(captured_json)
    )

    all_objects = []

    for response in captured_json:

        data = response.get(
            "data"
        )

        objects = recursive_objects(
            data
        )

        for obj in objects:

            if object_contains_toxic(
                obj
            ):

                all_objects.append({
                    "url":
                        response.get(
                            "url",
                            ""
                        ),
                    "object":
                        obj
                })

    print(
        "Objects containing Toxic:",
        len(all_objects)
    )

    # ========================================================
    # EXTRACT ROWS
    # ========================================================

    rows = []

    seen = set()

    print(
        "\n7. Extracting show records..."
    )

    for item in all_objects:

        obj = item[
            "object"
        ]

        row = make_row(
            obj,
            snapshot
        )

        if row is None:
            continue

        # Avoid duplicates
        dedupe_key = tuple(
            str(x)
            for x in row
        )

        if dedupe_key in seen:
            continue

        seen.add(
            dedupe_key
        )

        rows.append(
            row
        )

    # ========================================================
    # FALLBACK: SEARCH ALL OBJECTS
    # ========================================================

    if not rows:

        print(
            "\nNo direct Toxic show rows found."
        )

        print(
            "Running broader show-object search..."
        )

        for response in captured_json:

            objects = recursive_objects(
                response.get(
                    "data"
                )
            )

            for obj in objects:

                if not likely_show_object(
                    obj
                ):
                    continue

                # Only consider objects whose
                # surrounding JSON response
                # contains Toxic somewhere.

                response_text = json.dumps(
                    response.get(
                        "data"
                    ),
                    ensure_ascii=False
                )

                if not contains_toxic(
                    response_text
                ):
                    continue

                row = make_row(
                    obj,
                    snapshot
                )

                if row is None:
                    continue

                dedupe_key = tuple(
                    str(x)
                    for x in row
                )

                if dedupe_key in seen:
                    continue

                seen.add(
                    dedupe_key
                )

                rows.append(
                    row
                )

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print(
        "\n=============================================="
    )

    print(
        "EXTRACTED RECORDS:",
        len(rows)
    )

    print(
        "=============================================="
    )

    for row in rows:

        print(
            " | ".join(
                str(x)
                for x in row
            )
        )

    # ========================================================
    # SAVE RAW DATA
    # ========================================================

    print(
        "\n8. Saving raw BFilmy responses..."
    )

    with open(
        RAW_JSON_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            captured_json,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "Created:",
        RAW_JSON_FILE
    )

    # ========================================================
    # WRITE TO GOOGLE SHEETS
    # ========================================================

    if rows:

        print(
            "\n9. Writing records to Google Sheet..."
        )

        # Make sure header exists
        existing = sheet.get_all_values()

        if not existing:

            sheet.append_row(
                HEADERS,
                value_input_option="USER_ENTERED"
            )

        sheet.append_rows(
            rows,
            value_input_option="USER_ENTERED"
        )

        print(
            "Written:",
            len(rows),
            "rows"
        )

    else:

        print(
            "\n9. NO EXTRACTABLE SHOW RECORDS."
        )

        print(
            "The raw JSON file has been saved."
        )

        print(
            "This means BFilmy is loading Toxic,"
        )

        print(
            "but the show/seat structure needs"
        )

        print(
            "to be mapped from the actual JSON."
        )

    # ========================================================
    # FINAL
    # ========================================================

    print(
        "\n=============================================="
    )

    print(
        "TRACKER COMPLETE"
    )

    print(
        "=============================================="
    )

    print(
        "Snapshot:",
        snapshot
    )

    print(
        "Target:",
        TARGET_MOVIE,
        TARGET_DATE
    )

    print(
        "Target theatre:",
        TARGET_THEATRE
    )

    print(
        "JSON responses:",
        len(captured_json)
    )

    print(
        "Toxic objects:",
        len(all_objects)
    )

    print(
        "Rows written:",
        len(rows)
    )

    print(
        "Raw file:",
        RAW_JSON_FILE
    )


if __name__ == "__main__":
    run()
