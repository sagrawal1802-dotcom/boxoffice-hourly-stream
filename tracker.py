import os
import re
import json
import base64
import time
from datetime import datetime

import pytz
import gspread
from google.oauth2.service_account import Credentials

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"

CITY = "mumbai"

REGION_CODE = "MUMBAI"

VENUE_CODE = "CSWO"

SHOW_DATE = "20260826"


# ============================================================
# FORMAT FILTER
#
# [] = ALL FORMATS
#
# Examples:
#
# FORMAT_FILTER = ["2D"]
#
# FORMAT_FILTER = ["2D", "IMAX 2D"]
#
# FORMAT_FILTER = ["2D", "IMAX 2D", "4DX"]
# ============================================================

FORMAT_FILTER = []


# ============================================================
# BMS PAGE
#
# The HAR shows BMS using the buytickets page and then calling
# primary-dynamic from that page.
# ============================================================

BUY_TICKETS_URL = (
    "https://in.bookmyshow.com/movies/"
    f"{CITY}/toxic-a-fairy-tale-for-grown-ups/"
    f"buytickets/ET00513506/{SHOW_DATE}"
    "?etCodes=*&language=hindi&refEventCode=ET00513506"
)


# ============================================================
# TIMING
# ============================================================

PAGE_WAIT_SECONDS = 8

BETWEEN_SESSIONS_SECONDS = 2

PAGE_TIMEOUT = 60000


# ============================================================
# GOOGLE SHEET NAMES
# ============================================================

SHOW_SHEET_NAME = "Shows"

SEAT_SHEET_NAME = "SeatLog"


# ============================================================
# HEADERS
# ============================================================

SHOW_HEADERS = [
    "Timestamp IST",
    "Movie",
    "City",
    "Venue",
    "Venue Code",
    "Date",
    "Show Time",
    "Session ID",
    "Event Code",
    "Format",
    "Language",
    "Screen",
    "Source",
]


SEAT_HEADERS = [
    "Timestamp IST",
    "Movie",
    "City",
    "Venue Code",
    "Date",
    "Show Time",
    "Session ID",
    "Event Code",
    "Format",
    "Language",
    "Row Number",
    "Row Name",
    "Category Code",
    "Category",
    "Seat Token",
    "Seat Code",
    "Seat Number",
    "BMS State",
]


# ============================================================
# TIMESTAMP
# ============================================================

def now_ist():

    return datetime.now(
        pytz.timezone("Asia/Kolkata")
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# BANNER
# ============================================================

def banner(text):

    print()
    print("=" * 90)
    print(text)
    print("=" * 90)


# ============================================================
# GOOGLE AUTH
# ============================================================

def get_service_account():

    value = (
        os.environ.get("GCP_SA_KEY_B64")
        or os.environ.get("GCP_SA_KEY")
    )

    if not value:

        raise RuntimeError(
            "Missing GCP_SA_KEY_B64 or GCP_SA_KEY GitHub secret."
        )

    value = value.strip()

    # Direct JSON
    if value.startswith("{"):

        return json.loads(value)

    # Base64 JSON
    decoded = base64.b64decode(
        value
    ).decode(
        "utf-8"
    )

    return json.loads(
        decoded
    )


def connect_google():

    banner(
        "CONNECTING TO GOOGLE SHEETS"
    )

    service_account = (
        get_service_account()
    )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = (
        Credentials.from_service_account_info(
            service_account,
            scopes=scopes
        )
    )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    # --------------------------------------------------------
    # SHOWS
    # --------------------------------------------------------

    try:

        show_sheet = (
            spreadsheet.worksheet(
                SHOW_SHEET_NAME
            )
        )

    except gspread.WorksheetNotFound:

        show_sheet = (
            spreadsheet.add_worksheet(
                title=SHOW_SHEET_NAME,
                rows=5000,
                cols=len(SHOW_HEADERS)
            )
        )

    # --------------------------------------------------------
    # SEATS
    # --------------------------------------------------------

    try:

        seat_sheet = (
            spreadsheet.worksheet(
                SEAT_SHEET_NAME
            )
        )

    except gspread.WorksheetNotFound:

        seat_sheet = (
            spreadsheet.add_worksheet(
                title=SEAT_SHEET_NAME,
                rows=100000,
                cols=len(SEAT_HEADERS)
            )
        )

    # --------------------------------------------------------
    # Headers
    # --------------------------------------------------------

    if not show_sheet.get_all_values():

        show_sheet.append_row(
            SHOW_HEADERS,
            value_input_option="USER_ENTERED"
        )

    if not seat_sheet.get_all_values():

        seat_sheet.append_row(
            SEAT_HEADERS,
            value_input_option="USER_ENTERED"
        )

    print(
        "Google Sheets connected."
    )

    return (
        show_sheet,
        seat_sheet
    )


# ============================================================
# FORMAT NORMALIZATION
# ============================================================

def normalize_format(value):

    if value is None:

        return ""

    value = str(
        value
    ).strip().upper()

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value


def format_allowed(fmt):

    if not FORMAT_FILTER:

        return True

    target = normalize_format(
        fmt
    )

    allowed = [
        normalize_format(x)
        for x in FORMAT_FILTER
    ]

    return target in allowed


# ============================================================
# GENERIC VALUE HELPERS
# ============================================================

def first_value(
    obj,
    keys
):

    if not isinstance(
        obj,
        dict
    ):

        return None

    lower_map = {
        str(k).lower(): v
        for k, v in obj.items()
    }

    for key in keys:

        value = lower_map.get(
            key.lower()
        )

        if value is not None:

            if value != "":

                return value

    return None


def clean_text(value):

    if value is None:

        return ""

    if isinstance(
        value,
        (dict, list)
    ):

        return ""

    return str(
        value
    ).strip()


# ============================================================
# TIME EXTRACTION
# ============================================================

TIME_RE = re.compile(
    r"\b"
    r"(\d{1,2}:\d{2})"
    r"\s*"
    r"(AM|PM)"
    r"\b",
    re.I
)


def extract_time(value):

    if value is None:

        return ""

    text = str(
        value
    )

    match = TIME_RE.search(
        text
    )

    if match:

        return (
            match.group(1)
            + " "
            + match.group(2).upper()
        )

    return ""


# ============================================================
# FORMAT EXTRACTION
# ============================================================

FORMAT_NAMES = [
    "DOLBY CINEMA 2D",
    "IMAX 2D",
    "DOLBY CINEMA",
    "4DX",
    "EPIQ",
    "MX4D",
    "SCREEN X",
    "3D",
    "2D",
]


def extract_format_from_text(
    text
):

    if not text:

        return ""

    upper = str(
        text
    ).upper()

    for fmt in FORMAT_NAMES:

        if fmt in upper:

            return fmt

    return ""


# ============================================================
# LANGUAGE EXTRACTION
# ============================================================

LANGUAGE_NAMES = [
    "HINDI",
    "ENGLISH",
    "KANNADA",
    "TAMIL",
    "TELUGU",
    "MALAYALAM",
    "MARATHI",
    "BENGALI",
    "GUJARATI",
    "PUNJABI",
]


def extract_language_from_text(
    text
):

    if not text:

        return ""

    upper = str(
        text
    ).upper()

    found = []

    for language in LANGUAGE_NAMES:

        if language in upper:

            found.append(
                language.title()
            )

    return ", ".join(
        found
    )


# ============================================================
# SESSION ID
# ============================================================

SESSION_KEYS = [
    "sessionId",
    "sessionID",
    "showSessionId",
    "show_session_id",
    "session_id",
]


def get_session_id(obj):

    value = first_value(
        obj,
        SESSION_KEYS
    )

    if value is None:

        return ""

    text = str(
        value
    ).strip()

    # Session IDs in the BMS data are numeric
    if not re.fullmatch(
        r"\d+",
        text
    ):

        return ""

    return text


# ============================================================
# EVENT CODE
# ============================================================

EVENT_KEYS = [
    "eventCode",
    "event_code",
    "eventcode",
]


def get_event_code(obj):

    value = first_value(
        obj,
        EVENT_KEYS
    )

    if value is None:

        return ""

    text = str(
        value
    ).strip()

    if re.fullmatch(
        r"ET\d+",
        text,
        re.I
    ):

        return text.upper()

    return ""


# ============================================================
# VENUE CODE
# ============================================================

VENUE_KEYS = [
    "venueCode",
    "venue_code",
    "venuecode",
]


def get_venue_code(obj):

    value = first_value(
        obj,
        VENUE_KEYS
    )

    if value is None:

        return ""

    return str(
        value
    ).strip().upper()


# ============================================================
# RECURSIVE SHOW DISCOVERY
#
# This is deliberately generic because BMS can change the
# nesting of showtimesSections/showtimes.
# ============================================================

def walk_bms(
    node,
    context,
    results
):

    if isinstance(
        node,
        dict
    ):

        local = dict(
            context
        )

        # ----------------------------------------------------
        # Update inherited context
        # ----------------------------------------------------

        venue = get_venue_code(
            node
        )

        if venue:

            local["venue"] = venue

        event = get_event_code(
            node
        )

        if event:

            local["event"] = event

        # Format
        fmt_value = first_value(
            node,
            [
                "format",
                "formatName",
                "format_name",
                "experience",
                "screenFormat",
            ]
        )

        fmt = extract_format_from_text(
            clean_text(
                fmt_value
            )
        )

        if not fmt:

            # Search title/name/label/header
            for key in [
                "title",
                "name",
                "label",
                "header",
                "displayName",
                "display_name",
            ]:

                value = first_value(
                    node,
                    [key]
                )

                candidate = (
                    extract_format_from_text(
                        clean_text(value)
                    )
                )

                if candidate:

                    fmt = candidate
                    break

        if fmt:

            local["format"] = fmt

        # Language
        lang_value = first_value(
            node,
            [
                "language",
                "languageName",
                "language_name",
            ]
        )

        lang = clean_text(
            lang_value
        )

        if lang:

            local["language"] = lang

        # Screen
        screen_value = first_value(
            node,
            [
                "screen",
                "screenName",
                "screen_name",
                "screenNumber",
            ]
        )

        screen = clean_text(
            screen_value
        )

        if screen:

            local["screen"] = screen

        # Time
        for key in [
            "showTime",
            "showtime",
            "show_time",
            "startTime",
            "start_time",
            "time",
            "displayTime",
            "display_time",
        ]:

            value = first_value(
                node,
                [key]
            )

            show_time = extract_time(
                value
            )

            if show_time:

                local["time"] = show_time
                break

        # ----------------------------------------------------
        # Session
        # ----------------------------------------------------

        session_id = get_session_id(
            node
        )

        if session_id:

            result = {
                "session_id": session_id,
                "event_code": local.get(
                    "event",
                    ""
                ),
                "venue_code": local.get(
                    "venue",
                    ""
                ),
                "format": local.get(
                    "format",
                    ""
                ),
                "language": local.get(
                    "language",
                    ""
                ),
                "screen": local.get(
                    "screen",
                    ""
                ),
                "show_time": local.get(
                    "time",
                    ""
                ),
            }

            # ------------------------------------------------
            # Search the complete node for additional hints
            # ------------------------------------------------

            serialized = json.dumps(
                node,
                ensure_ascii=False
            )

            if not result["format"]:

                result["format"] = (
                    extract_format_from_text(
                        serialized
                    )
                )

            if not result["language"]:

                result["language"] = (
                    extract_language_from_text(
                        serialized
                    )
                )

            if not result["show_time"]:

                result["show_time"] = (
                    extract_time(
                        serialized
                    )
                )

            # ------------------------------------------------
            # Only CSWO
            # ------------------------------------------------

            if (
                result["venue_code"]
                and
                result["venue_code"]
                != VENUE_CODE
            ):

                pass

            else:

                key = (
                    result["event_code"],
                    result["session_id"]
                )

                # Avoid duplicates
                results[key] = result

        # ----------------------------------------------------
        # Continue recursively
        # ----------------------------------------------------

        for value in node.values():

            if isinstance(
                value,
                (dict, list)
            ):

                walk_bms(
                    value,
                    local,
                    results
                )

    elif isinstance(
        node,
        list
    ):

        for item in node:

            walk_bms(
                item,
                context,
                results
            )


# ============================================================
# DISCOVER SHOWS FROM BMS NETWORK
# ============================================================

def discover_shows(
    page
):

    banner(
        "BMS SHOW DISCOVERY"
    )

    print(
        f"URL:\n{BUY_TICKETS_URL}"
    )

    print()
    print(
        f"Venue filter : {VENUE_CODE}"
    )

    print(
        f"Format filter: "
        f"{FORMAT_FILTER if FORMAT_FILTER else 'ALL FORMATS'}"
    )

    responses = []

    # --------------------------------------------------------
    # Capture the exact BMS endpoint shown in HAR
    # --------------------------------------------------------

    def handle_response(
        response
    ):

        url = response.url

        if (
            "/api/movies-data/v5/"
            "showtimes-by-event/"
            "primary-dynamic"
            in url
        ):

            print()
            print(
                "FOUND BMS SHOWTIME RESPONSE"
            )

            print(
                f"HTTP: {response.status}"
            )

            print(
                f"URL: {url[:500]}"
            )

            try:

                data = response.json()

                responses.append(
                    data
                )

                print(
                    "JSON response captured."
                )

            except Exception as error:

                print(
                    f"Could not parse JSON: "
                    f"{error}"
                )

    page.on(
        "response",
        handle_response
    )

    # --------------------------------------------------------
    # Navigate
    # --------------------------------------------------------

    try:

        response = page.goto(
            BUY_TICKETS_URL,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        if response:

            print(
                f"Page HTTP status: "
                f"{response.status}"
            )

    except Exception as error:

        print(
            f"Navigation error: "
            f"{error}"
        )

        return []

    # --------------------------------------------------------
    # Give BMS time to call API
    # --------------------------------------------------------

    print(
        f"Waiting {PAGE_WAIT_SECONDS} seconds "
        f"for BMS showtime API..."
    )

    page.wait_for_timeout(
        PAGE_WAIT_SECONDS * 1000
    )

    # --------------------------------------------------------
    # Sometimes BMS has not fired the API yet.
    # Wait a little more if required.
    # --------------------------------------------------------

    if not responses:

        print(
            "No showtime response yet."
        )

        print(
            "Waiting additional 8 seconds..."
        )

        page.wait_for_timeout(
            8000
        )

    # --------------------------------------------------------
    # Parse all captured responses
    # --------------------------------------------------------

    results = {}

    for data in responses:

        walk_bms(
            data,
            {},
            results
        )

    shows = list(
        results.values()
    )

    # --------------------------------------------------------
    # Clean/filter
    # --------------------------------------------------------

    final_shows = []

    for show in shows:

        # Require session ID
        if not show["session_id"]:

            continue

        # If venue is known and not CSWO, skip
        if (
            show["venue_code"]
            and
            show["venue_code"]
            != VENUE_CODE
        ):

            continue

        # Format filter
        if not format_allowed(
            show["format"]
        ):

            continue

        final_shows.append(
            show
        )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    final_shows.sort(
        key=lambda x: (
            x.get(
                "format",
                ""
            ),
            x.get(
                "show_time",
                ""
            ),
            x.get(
                "session_id",
                ""
            )
        )
    )

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    banner(
        "DISCOVERED CSWO SHOWS"
    )

    if not final_shows:

        print(
            "NO CSWO SHOWS DISCOVERED."
        )

        print()
        print(
            "Captured BMS responses:"
            f" {len(responses)}"
        )

        return []

    for i, show in enumerate(
        final_shows,
        start=1
    ):

        print(
            f"{i:02d}. "
            f"{show.get('show_time') or 'TIME ?':<10} | "
            f"{show.get('format') or 'FORMAT ?':<20} | "
            f"{show.get('language') or 'LANG ?':<25} | "
            f"{show.get('event_code') or 'EVENT ?':<12} | "
            f"{show['session_id']}"
        )

    print()
    print(
        f"TOTAL CSWO SHOWS: "
        f"{len(final_shows)}"
    )

    return final_shows


# ============================================================
# SEAT TOKEN
#
# BMS convention confirmed from your working data:
#
# A1052+1 = AVAILABLE
# A20515+9 = SOLD
#
# First numeric part:
# 1xxxx = AVAILABLE
# 2xxxx = SOLD
#
# Number after + = actual seat number.
# ============================================================

def parse_seat_token(
    token
):

    if not token:

        return None

    token = (
        str(token)
        .strip()
        .replace(" ", "")
    )

    match = re.fullmatch(
        r"([A-Za-z])(\d+)\+(\d+)",
        token
    )

    if not match:

        return None

    letter = (
        match.group(1)
        .upper()
    )

    code_number = (
        match.group(2)
    )

    seat_number = (
        match.group(3)
    )

    # A0 / B0 etc. are not seats
    if code_number == "0":

        return None

    if code_number.startswith("1"):

        status = "AVAILABLE"

    elif code_number.startswith("2"):

        status = "SOLD"

    else:

        return None

    return {
        "seat_token": token,
        "seat_code": (
            f"{letter}{code_number}"
        ),
        "seat_number": seat_number,
        "status": status,
    }


# ============================================================
# GET SEAT LAYOUT
#
# Use the BMS seat-layout API with the event code belonging
# to each individual format.
# ============================================================

def get_seat_layout(
    page,
    show
):

    event_code = show[
        "event_code"
    ]

    session_id = show[
        "session_id"
    ]

    url = (
        "https://in.bookmyshow.com/"
        "api/movies-data/seatlayout/v1/primary"
        f"?eventCode={event_code}"
        f"&dateCode={SHOW_DATE}"
        f"&regionCode={REGION_CODE}"
        f"&venueCode={VENUE_CODE}"
    )

    # --------------------------------------------------------
    # The session is required by BMS.
    #
    # The working seat-layout flow identifies the session
    # through the selected show/session URL.
    # --------------------------------------------------------

    seat_url = (
        "https://in.bookmyshow.com/"
        f"movies/{CITY}/seat-layout/"
        f"{event_code}/"
        f"{VENUE_CODE}/"
        f"{session_id}/"
        f"{SHOW_DATE}"
    )

    print()
    print(
        f"Seat URL:\n{seat_url}"
    )

    try:

        response = page.goto(
            seat_url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        if response:

            print(
                f"Seat page HTTP: "
                f"{response.status}"
            )

    except Exception as error:

        print(
            f"Seat page navigation error: "
            f"{error}"
        )

        return None

    # --------------------------------------------------------
    # Wait for seat API response
    # --------------------------------------------------------

    seat_response = None

    def capture(
        response
    ):

        nonlocal seat_response

        response_url = (
            response.url
        )

        if (
            "/api/movies-data/"
            "seatlayout/v1/primary"
            in response_url
        ):

            try:

                seat_response = (
                    response.json()
                )

                print(
                    "Seat layout JSON captured."
                )

            except Exception as error:

                print(
                    f"Seat JSON error: "
                    f"{error}"
                )

    page.on(
        "response",
        capture
    )

    # Reload so listener is active before request
    try:

        page.reload(
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

    except Exception:

        pass

    page.wait_for_timeout(
        5000
    )

    if not seat_response:

        print(
            "No seat-layout JSON captured."
        )

        return None

    return seat_response


# ============================================================
# EXTRACT STRDATA FROM SEAT RESPONSE
# ============================================================

def find_strdata(
    obj
):

    if isinstance(
        obj,
        dict
    ):

        for key, value in obj.items():

            if str(
                key
            ).lower() == "strdata":

                if isinstance(
                    value,
                    str
                ):

                    return value

            if isinstance(
                value,
                (dict, list)
            ):

                found = find_strdata(
                    value
                )

                if found:

                    return found

    elif isinstance(
        obj,
        list
    ):

        for item in obj:

            found = find_strdata(
                item
            )

            if found:

                return found

    return None


# ============================================================
# PARSE SEAT LAYOUT
# ============================================================

def parse_seat_layout(
    response_json,
    show
):

    str_data = find_strdata(
        response_json
    )

    if not str_data:

        print(
            "ERROR: strData not found."
        )

        return []

    print(
        f"strData length: "
        f"{len(str_data)}"
    )

    # --------------------------------------------------------
    # Existing working BMS structure:
    #
    # categories || seat rows
    # --------------------------------------------------------

    sections = str_data.split(
        "||",
        1
    )

    if len(sections) != 2:

        print(
            "Could not split BMS seat layout."
        )

        return []

    category_section = (
        sections[0]
    )

    seat_section = (
        sections[1]
    )

    category_map = {}

    # --------------------------------------------------------
    # Categories
    # --------------------------------------------------------

    for item in (
        category_section.split("|")
    ):

        item = item.strip()

        if not item:

            continue

        parts = item.split(
            ":"
        )

        if len(parts) < 2:

            continue

        category_code = (
            parts[0].strip()
        )

        category_name = (
            parts[1].strip()
        )

        category_map[
            category_code
        ] = category_name

    # --------------------------------------------------------
    # Seats
    # --------------------------------------------------------

    rows = []

    available = 0

    sold = 0

    for raw_row in (
        seat_section.split("|")
    ):

        raw_row = (
            raw_row.strip()
        )

        if not raw_row:

            continue

        parts = raw_row.split(
            ":",
            3
        )

        if len(parts) < 4:

            continue

        row_number = (
            parts[0].strip()
        )

        row_name = (
            parts[1].strip()
        )

        category_code = (
            parts[2].strip()
        )

        seat_string = (
            parts[3].strip()
        )

        category_name = (
            category_map.get(
                category_code,
                category_code
            )
        )

        for token in (
            seat_string.split(":")
        ):

            parsed = parse_seat_token(
                token
            )

            if not parsed:

                continue

            if (
                parsed["status"]
                == "AVAILABLE"
            ):

                available += 1

            else:

                sold += 1

            rows.append([
                now_ist(),
                MOVIE_NAME,
                CITY,
                VENUE_CODE,
                SHOW_DATE,
                show.get(
                    "show_time",
                    ""
                ),
                show.get(
                    "session_id",
                    ""
                ),
                show.get(
                    "event_code",
                    ""
                ),
                show.get(
                    "format",
                    ""
                ),
                show.get(
                    "language",
                    ""
                ),
                row_number,
                row_name,
                category_code,
                category_name,
                parsed[
                    "seat_token"
                ],
                parsed[
                    "seat_code"
                ],
                parsed[
                    "seat_number"
                ],
                parsed[
                    "status"
                ],
            ])

    print()
    print(
        f"SEATS: {len(rows)}"
    )

    print(
        f"AVAILABLE: {available}"
    )

    print(
        f"SOLD: {sold}"
    )

    return rows


# ============================================================
# SAVE SHOWS
# ============================================================

def save_shows(
    sheet,
    shows
):

    # Clear previous discovery result
    sheet.clear()

    sheet.update(
        "A1",
        [SHOW_HEADERS]
    )

    if not shows:

        return

    rows = []

    for show in shows:

        rows.append([
            now_ist(),
            MOVIE_NAME,
            CITY,
            "CSWO",
            VENUE_CODE,
            SHOW_DATE,
            show.get(
                "show_time",
                ""
            ),
            show.get(
                "session_id",
                ""
            ),
            show.get(
                "event_code",
                ""
            ),
            show.get(
                "format",
                ""
            ),
            show.get(
                "language",
                ""
            ),
            show.get(
                "screen",
                ""
            ),
            BUY_TICKETS_URL,
        ])

    sheet.append_rows(
        rows,
        value_input_option="USER_ENTERED"
    )

    print(
        f"Saved {len(rows)} shows."
    )


# ============================================================
# SAVE SEATS
# ============================================================

def save_seats(
    sheet,
    rows
):

    if not rows:

        return

    sheet.append_rows(
        rows,
        value_input_option="USER_ENTERED"
    )

    print(
        f"Saved {len(rows)} seat rows."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    banner(
        "BMS TOXIC CSWO ALL-SHOW TRACKER"
    )

    print(
        f"Timestamp : {now_ist()}"
    )

    print(
        f"Movie     : {MOVIE_NAME}"
    )

    print(
        f"City      : {CITY}"
    )

    print(
        f"Venue     : {VENUE_CODE}"
    )

    print(
        f"Date      : {SHOW_DATE}"
    )

    print(
        f"Formats   : "
        f"{FORMAT_FILTER if FORMAT_FILTER else 'ALL'}"
    )

    # --------------------------------------------------------
    # Google
    # --------------------------------------------------------

    try:

        show_sheet, seat_sheet = (
            connect_google()
        )

    except Exception as error:

        print()
        print(
            "GOOGLE SHEETS ERROR:"
        )

        print(error)

        raise

    # --------------------------------------------------------
    # Browser
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = (
            browser.new_context(
                viewport={
                    "width": 1536,
                    "height": 864,
                },
                locale="en-US",
                timezone_id="Asia/Kolkata",
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/151.0.0.0 "
                    "Safari/537.36"
                ),
            )
        )

        page = (
            context.new_page()
        )

        # ----------------------------------------------------
        # STEP 1
        # Discover all shows
        # ----------------------------------------------------

        shows = discover_shows(
            page
        )

        save_shows(
            show_sheet,
            shows
        )

        if not shows:

            browser.close()

            banner(
                "NO SHOWS FOUND - STOPPING"
            )

            return

        # ----------------------------------------------------
        # STEP 2
        # Seat extraction
        # ----------------------------------------------------

        banner(
            "PROCESSING ALL DISCOVERED SHOWS"
        )

        total_seat_rows = 0

        for index, show in enumerate(
            shows,
            start=1
        ):

            print()
            print(
                "-" * 90
            )

            print(
                f"SHOW {index}/{len(shows)}"
            )

            print(
                f"Time    : "
                f"{show.get('show_time', '')}"
            )

            print(
                f"Format  : "
                f"{show.get('format', '')}"
            )

            print(
                f"Event   : "
                f"{show.get('event_code', '')}"
            )

            print(
                f"Session : "
                f"{show.get('session_id', '')}"
            )

            print(
                "-" * 90
            )

            response_json = (
                get_seat_layout(
                    page,
                    show
                )
            )

            if not response_json:

                print(
                    "FAILED: No seat layout."
                )

                continue

            seat_rows = (
                parse_seat_layout(
                    response_json,
                    show
                )
            )

            if seat_rows:

                save_seats(
                    seat_sheet,
                    seat_rows
                )

                total_seat_rows += (
                    len(seat_rows)
                )

            if index < len(shows):

                time.sleep(
                    BETWEEN_SESSIONS_SECONDS
                )

        browser.close()

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    banner(
        "TRACKING COMPLETED"
    )

    print(
        f"Shows discovered : "
        f"{len(shows)}"
    )

    print(
        f"Seat rows saved  : "
        f"{total_seat_rows}"
    )

    print(
        f"Format filter    : "
        f"{FORMAT_FILTER if FORMAT_FILTER else 'ALL'}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
