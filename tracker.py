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

SHEET_TAB_NAME = "Toxic_26Aug"

BFILMY_URL = "https://bfilmy.pages.dev/District%20Advance/"

TARGET_DATE = "2026-08-26"

TARGET_MOVIE = "Toxic"

# EXACT BOOKMYSHOW EVENT CODE FOR TOXIC
TARGET_EVENT_CODE = "ET00378770"

TARGET_THEATRE_KEYWORDS = [
    "pvr market city",
    "market city kurla",
    "pvr marketcity",
    "kurla"
]

RAW_FILE = "bfilmy_toxic_raw.json"


# ============================================================
# GOOGLE SHEET HEADERS
# ============================================================

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
    "Sold / Booked Seats",
    "Occupancy %",
    "Booking Source",
    "Data Status"
]


# ============================================================
# TIME
# ============================================================

def get_ist_time():

    return (
        datetime.datetime.now(
            datetime.timezone.utc
        )
        + datetime.timedelta(
            hours=5,
            minutes=30
        )
    )


# ============================================================
# TEXT HELPERS
# ============================================================

def clean(value):

    if value is None:
        return ""

    if isinstance(value, bool):
        return str(value)

    if isinstance(
        value,
        (dict, list)
    ):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def lower(value):

    return clean(value).lower()


def contains_toxic(value):

    text = lower(value)

    return (
        "toxic: a fairy tale for grown-ups" in text
        or
        "toxic a fairy tale for grownups" in text
        or
        "toxic a fairy tale for grown-ups" in text
    )


def is_exact_toxic(obj):

    """
    IMPORTANT:
    Do not match generic 'Toxic'.

    Match the exact BMS event code OR
    the actual Toxic title.
    """

    if not isinstance(obj, dict):
        return False

    # --------------------------------------------------------
    # Event code
    # --------------------------------------------------------

    event_values = [
        obj.get("event_code"),
        obj.get("eventCode"),
        obj.get("event"),
        obj.get("eventCode"),
        obj.get("entity_code"),
        obj.get("entityCode")
    ]

    for value in event_values:

        if clean(value).upper() == TARGET_EVENT_CODE:
            return True

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title_keys = [
        "title",
        "movie",
        "movieName",
        "movie_name",
        "movieTitle",
        "movie_title",
        "film",
        "filmName"
    ]

    for key in title_keys:

        value = clean(
            obj.get(key)
        )

        if contains_toxic(value):
            return True

    return False


# ============================================================
# RECURSIVE JSON WALK
# ============================================================

def walk(obj, path="$"):

    yield path, obj

    if isinstance(obj, dict):

        for key, value in obj.items():

            yield from walk(
                value,
                f"{path}.{key}"
            )

    elif isinstance(obj, list):

        for i, value in enumerate(obj):

            yield from walk(
                value,
                f"{path}[{i}]"
            )


# ============================================================
# KEY LOOKUP
# ============================================================

def get_value(
    obj,
    keys
):

    if not isinstance(obj, dict):
        return None

    lower_keys = {
        str(k).lower(): k
        for k in obj.keys()
    }

    for wanted in keys:

        actual = lower_keys.get(
            wanted.lower()
        )

        if actual is not None:

            return obj[
                actual
            ]

    return None


# ============================================================
# NUMBER
# ============================================================

def to_number(value):

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(
        value,
        (int, float)
    ):
        return int(value)

    text = clean(value)

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


# ============================================================
# SEAT FIELDS
# ============================================================

TOTAL_KEYS = [
    "totalSeats",
    "total_seats",
    "totalSeatCount",
    "total_seat_count",
    "seatCount",
    "seat_count",
    "capacity",
    "total"
]

AVAILABLE_KEYS = [
    "availableSeats",
    "available_seats",
    "availSeats",
    "avail_seats",
    "available",
    "avail",
    "curAvail",
    "currentAvailable",
    "remainingSeats",
    "remaining"
]

BOOKED_KEYS = [
    "bookedSeats",
    "booked_seats",
    "booked",
    "soldSeats",
    "sold_seats",
    "sold",
    "ticketsSold",
    "tickets_sold"
]


def extract_seats(obj):

    total = to_number(
        get_value(
            obj,
            TOTAL_KEYS
        )
    )

    available = to_number(
        get_value(
            obj,
            AVAILABLE_KEYS
        )
    )

    booked = to_number(
        get_value(
            obj,
            BOOKED_KEYS
        )
    )

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

    return (
        total,
        available,
        booked
    )


# ============================================================
# OCCUPANCY
# ============================================================

def calculate_occupancy(
    booked,
    total
):

    if (
        booked is None
        or
        total is None
        or
        total <= 0
    ):

        return ""

    return round(
        booked / total * 100,
        2
    )


# ============================================================
# FIELD EXTRACTION
# ============================================================

def get_text(
    obj,
    keys
):

    value = get_value(
        obj,
        keys
    )

    return clean(value)


def get_movie(obj):

    return get_text(
        obj,
        [
            "movie",
            "movieName",
            "movie_name",
            "movieTitle",
            "movie_title",
            "film",
            "filmName",
            "title"
        ]
    )


def get_event_code(obj):

    value = get_value(
        obj,
        [
            "eventCode",
            "event_code",
            "event",
            "entityCode",
            "entity_code"
        ]
    )

    return clean(value).upper()


def get_theatre(obj):

    return get_text(
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


def get_city(obj):

    return get_text(
        obj,
        [
            "city",
            "cityName"
        ]
    )


def get_state(obj):

    return get_text(
        obj,
        [
            "state",
            "stateName"
        ]
    )


def get_chain(obj):

    return get_text(
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


def get_language(obj):

    return get_text(
        obj,
        [
            "language",
            "languageName",
            "lang"
        ]
    )


def get_format(obj):

    return get_text(
        obj,
        [
            "format",
            "formatName",
            "screenFormat",
            "screen_format",
            "experience"
        ]
    )


def get_audi(obj):

    return get_text(
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


def get_show_time(obj):

    return get_text(
        obj,
        [
            "showTime",
            "show_time",
            "showtime",
            "time",
            "timing",
            "startTime",
            "start_time"
        ]
    )


def get_date(obj):

    return get_text(
        obj,
        [
            "showDate",
            "show_date",
            "date",
            "bookingDate",
            "booking_date"
        ]
    )


# ============================================================
# THEATRE MATCH
# ============================================================

def theatre_matches(obj):

    theatre = lower(
        get_theatre(obj)
    )

    if not theatre:

        return False

    return any(
        keyword in theatre
        for keyword in TARGET_THEATRE_KEYWORDS
    )


# ============================================================
# DATE MATCH
# ============================================================

def date_matches(obj):

    value = get_date(obj)

    if not value:

        # If date isn't attached to the object,
        # don't reject it.
        return True

    value = clean(value)

    # Direct target formats
    possible = [
        "2026-08-26",
        "26-08-2026",
        "26/08/2026",
        "26.08.2026",
        "2026/08/26"
    ]

    for candidate in possible:

        if candidate in value:

            return True

    # If date is just another format, extract digits
    digits = re.sub(
        r"\D",
        "",
        value
    )

    return (
        "20260826" in digits
        or
        "26082026" in digits
    )


# ============================================================
# BUILD ROW
# ============================================================

def build_row(
    obj,
    snapshot
):

    if not isinstance(obj, dict):

        return None

    # Exact Toxic match
    if not is_exact_toxic(obj):

        return None

    event_code = get_event_code(
        obj
    )

    movie = get_movie(
        obj
    )

    # --------------------------------------------------------
    # Never accept Toxic Avenger
    # --------------------------------------------------------

    if "toxic avenger" in lower(
        movie
    ):

        return None

    # --------------------------------------------------------
    # Theatre
    # --------------------------------------------------------

    theatre = get_theatre(
        obj
    )

    # If a theatre exists and isn't Kurla,
    # reject it for this particular tracker.

    if theatre:

        if not theatre_matches(obj):

            return None

    # --------------------------------------------------------
    # Date
    # --------------------------------------------------------

    if not date_matches(obj):

        return None

    # --------------------------------------------------------
    # Other fields
    # --------------------------------------------------------

    state = get_state(
        obj
    )

    city = get_city(
        obj
    )

    chain = get_chain(
        obj
    )

    language = get_language(
        obj
    )

    fmt = get_format(
        obj
    )

    audi = get_audi(
        obj
    )

    show_time = get_show_time(
        obj
    )

    total, available, booked = extract_seats(
        obj
    )

    # --------------------------------------------------------
    # Calculate
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

    occ = calculate_occupancy(
        booked,
        total
    )

    # --------------------------------------------------------
    # No invented values
    # --------------------------------------------------------

    status_parts = []

    if show_time:
        status_parts.append(
            "Show time found"
        )

    if total is not None:
        status_parts.append(
            "Total seats found"
        )

    if available is not None:
        status_parts.append(
            "Available seats found"
        )

    if booked is not None:
        status_parts.append(
            "Booked seats found"
        )

    if not status_parts:

        status_parts.append(
            "Toxic record found - show/seat fields not directly attached"
        )

    return [
        snapshot,
        TARGET_DATE,
        state,
        city,
        chain,
        theatre,
        movie,
        event_code,
        language,
        fmt,
        audi,
        show_time,
        total if total is not None else "",
        available if available is not None else "",
        booked if booked is not None else "",
        occ,
        "BFilmy / District",
        " | ".join(
            status_parts
        )
    ]


# ============================================================
# MAIN
# ============================================================

def run():

    print(
        "\n=============================================="
    )

    print(
        "TOXIC 26 AUGUST - BFILMY EXTRACTION"
    )

    print(
        "=============================================="
    )

    print(
        "Target event:",
        TARGET_EVENT_CODE
    )

    print(
        "Target date:",
        TARGET_DATE
    )

    print(
        "Target theatre:",
        TARGET_THEATRE_KEYWORDS
    )

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    snapshot = get_ist_time().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

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

    try:

        sheet = spreadsheet.worksheet(
            SHEET_TAB_NAME
        )

    except gspread.exceptions.WorksheetNotFound:

        print(
            "Creating:",
            SHEET_TAB_NAME
        )

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=5000,
            cols=len(HEADERS)
        )

    # --------------------------------------------------------
    # Ensure header
    # --------------------------------------------------------

    current_values = sheet.get_all_values()

    if not current_values:

        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

    print(
        "\n2. Launching Chromium..."
    )

    captured = []

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
        # Capture JSON
        # ----------------------------------------------------

        def response_handler(
            response
        ):

            try:

                content_type = response.headers.get(
                    "content-type",
                    ""
                ).lower()

                if "json" not in content_type:

                    return

                text = response.text()

                if not text:

                    return

                try:

                    data = json.loads(
                        text
                    )

                except Exception:

                    return

                captured.append({
                    "url": response.url,
                    "status": response.status,
                    "data": data
                })

            except Exception:
                pass

        page.on(
            "response",
            response_handler
        )

        # ----------------------------------------------------
        # Open BFilmy
        # ----------------------------------------------------

        print(
            "\n3. Opening BFilmy..."
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
        # Wait
        # ----------------------------------------------------

        print(
            "\n4. Waiting for BFilmy data..."
        )

        page.wait_for_timeout(
            10000
        )

        # ----------------------------------------------------
        # Scroll
        # ----------------------------------------------------

        print(
            "\n5. Scrolling..."
        )

        for i in range(15):

            try:

                page.mouse.wheel(
                    0,
                    1400
                )

            except Exception:
                pass

            page.wait_for_timeout(
                700
            )

        page.wait_for_timeout(
            5000
        )

        # ----------------------------------------------------
        # Page text
        # ----------------------------------------------------

        try:

            text = page.locator(
                "body"
            ).inner_text()

            print(
                "\nPage text length:",
                len(text)
            )

            print(
                "Toxic visible:",
                contains_toxic(text)
            )

        except Exception:
            pass

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
    # PROCESS CAPTURED JSON
    # ========================================================

    print(
        "\n6. JSON responses captured:",
        len(captured)
    )

    # --------------------------------------------------------
    # Save raw
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
        "Raw JSON saved:",
        RAW_FILE
    )

    # ========================================================
    # FIND EXACT TOXIC OBJECTS
    # ========================================================

    toxic_objects = []

    for response in captured:

        data = response.get(
            "data"
        )

        for path, obj in walk(
            data
        ):

            if not isinstance(
                obj,
                dict
            ):

                continue

            if is_exact_toxic(
                obj
            ):

                toxic_objects.append({
                    "url":
                        response.get(
                            "url",
                            ""
                        ),
                    "path":
                        path,
                    "object":
                        obj
                })

    print(
        "Exact Toxic objects:",
        len(toxic_objects)
    )

    # ========================================================
    # BUILD ROWS
    # ========================================================

    rows = []

    seen = set()

    for item in toxic_objects:

        obj = item[
            "object"
        ]

        row = build_row(
            obj,
            snapshot
        )

        if row is None:
            continue

        # ----------------------------------------------------
        # Deduplicate
        # ----------------------------------------------------

        key = (
            row[1],   # date
            row[5],   # theatre
            row[8],   # language
            row[9],   # format
            row[10],  # audi
            row[11]   # time
        )

        if key in seen:

            continue

        seen.add(
            key
        )

        rows.append(
            row
        )

    # ========================================================
    # PRINT
    # ========================================================

    print(
        "\n=============================================="
    )

    print(
        "FINAL EXTRACTION"
    )

    print(
        "=============================================="
    )

    print(
        "Exact Toxic objects:",
        len(toxic_objects)
    )

    print(
        "Kurla rows:",
        len(rows)
    )

    for row in rows:

        print(
            "\n" +
            " | ".join(
                str(x)
                for x in row
            )
        )

    # ========================================================
    # WRITE SHEET
    # ========================================================

    if rows:

        print(
            "\n7. Writing to Google Sheet..."
        )

        sheet.append_rows(
            rows,
            value_input_option="USER_ENTERED"
        )

        print(
            "SUCCESS:",
            len(rows),
            "rows written."
        )

    else:

        print(
            "\n7. No Kurla rows extracted."
        )

        print(
            "Raw JSON has been saved as:",
            RAW_FILE
        )

        print(
            "This is intentional:"
        )

        print(
            "the tracker will not invent show/seat numbers."
        )

    # ========================================================
    # FINAL
    # ========================================================

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
        "Target:",
        TARGET_MOVIE
    )

    print(
        "Event:",
        TARGET_EVENT_CODE
    )

    print(
        "Date:",
        TARGET_DATE
    )

    print(
        "Rows written:",
        len(rows)
    )

    print(
        "Raw file:",
        RAW_FILE
    )


if __name__ == "__main__":
    run()
