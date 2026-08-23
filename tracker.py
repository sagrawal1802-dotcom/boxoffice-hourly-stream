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

CITY = "mumbai"

EVENT_CODE = "ET00379311"

VENUE_CODE = "CSWO"

SHOW_DATE = "20260826"

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"


# ------------------------------------------------------------
# FORMAT FILTER
#
# [] = ALL FORMATS
#
# ["2D"] = only 2D
#
# ["2D", "IMAX 2D"] = both
# ------------------------------------------------------------

FORMAT_FILTER = []


# ------------------------------------------------------------
# Discovery page
# ------------------------------------------------------------

MOVIE_PAGE = (
    "https://in.bookmyshow.com/movies/"
    f"{CITY}/toxic-a-fairy-tale-for-grown-ups/"
    f"{EVENT_CODE}"
)


# ------------------------------------------------------------
# Delays
# ------------------------------------------------------------

DISCOVERY_WAIT = 8

DELAY_BETWEEN_SESSIONS = 2

PAGE_TIMEOUT = 60000


# ============================================================
# GOOGLE AUTH
# ============================================================

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)


# ============================================================
# SHEET NAMES
# ============================================================

SHOW_SHEET = "Shows"

SEAT_SHEET = "SeatLog"


# ============================================================
# HEADERS
# ============================================================

SHOW_HEADERS = [
    "Timestamp IST",
    "Movie",
    "Event Code",
    "City",
    "Venue",
    "Venue Code",
    "Date",
    "Show Time",
    "Session ID",
    "Format",
    "Language",
    "Screen",
    "Source URL",
]


SEAT_HEADERS = [
    "Timestamp IST",
    "Movie",
    "Event Code",
    "City",
    "Venue Code",
    "Date",
    "Show Time",
    "Session ID",
    "Format",
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
# UTILITY
# ============================================================

def banner(text):

    print()
    print("=" * 80)
    print(text)
    print("=" * 80)


def timestamp():

    return datetime.now(
        pytz.timezone("Asia/Kolkata")
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def decode_google_key():

    if not GCP_SA_KEY:

        raise ValueError(
            "Missing GCP_SA_KEY_B64 or GCP_SA_KEY secret."
        )

    value = GCP_SA_KEY.strip()

    # Direct JSON secret
    if value.startswith("{"):

        return json.loads(value)

    # Base64 secret
    try:

        decoded = base64.b64decode(
            value
        ).decode("utf-8")

        return json.loads(decoded)

    except Exception as error:

        raise ValueError(
            f"Could not decode Google service account: {error}"
        )


def connect_google():

    banner("CONNECTING TO GOOGLE SHEETS")

    service_account = decode_google_key()

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        service_account,
        scopes=scopes
    )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    # --------------------------------------------------------
    # Shows sheet
    # --------------------------------------------------------

    try:

        shows = spreadsheet.worksheet(
            SHOW_SHEET
        )

    except gspread.WorksheetNotFound:

        shows = spreadsheet.add_worksheet(
            title=SHOW_SHEET,
            rows=5000,
            cols=len(SHOW_HEADERS)
        )

    # --------------------------------------------------------
    # Seat sheet
    # --------------------------------------------------------

    try:

        seats = spreadsheet.worksheet(
            SEAT_SHEET
        )

    except gspread.WorksheetNotFound:

        seats = spreadsheet.add_worksheet(
            title=SEAT_SHEET,
            rows=50000,
            cols=len(SEAT_HEADERS)
        )

    # --------------------------------------------------------
    # Headers
    # --------------------------------------------------------

    if not shows.get_all_values():

        shows.append_row(
            SHOW_HEADERS,
            value_input_option="USER_ENTERED"
        )

    if not seats.get_all_values():

        seats.append_row(
            SEAT_HEADERS,
            value_input_option="USER_ENTERED"
        )

    print("Google Sheets connected.")

    return shows, seats


# ============================================================
# FORMAT NORMALIZATION
# ============================================================

def normalize_format(value):

    if not value:
        return ""

    value = value.upper().strip()

    value = value.replace(
        "  ",
        " "
    )

    return value


def format_allowed(fmt):

    # Empty filter means ALL formats
    if not FORMAT_FILTER:
        return True

    normalized = normalize_format(
        fmt
    )

    allowed = [
        normalize_format(x)
        for x in FORMAT_FILTER
    ]

    return normalized in allowed


# ============================================================
# TIME EXTRACTION
# ============================================================

TIME_PATTERN = re.compile(
    r"\b("
    r"\d{1,2}:\d{2}\s*(?:AM|PM)"
    r")\b",
    re.I
)


def extract_time(text):

    if not text:
        return None

    match = TIME_PATTERN.search(
        text
    )

    if not match:
        return None

    return match.group(1).upper()


# ============================================================
# SESSION ID EXTRACTION
# ============================================================

SESSION_PATTERNS = [

    re.compile(
        r"/seat-layout/"
        r"ET\d+/"
        r"([A-Z0-9]+)/"
        r"(\d+)/"
        r"(\d{8})",
        re.I
    ),

    re.compile(
        r"[?&]session(?:Id|ID|id)=(\d+)",
        re.I
    ),

    re.compile(
        r"[?&]session=(\d+)",
        re.I
    ),
]


def extract_session_id(text):

    if not text:
        return None

    for pattern in SESSION_PATTERNS:

        match = pattern.search(
            text
        )

        if match:

            # First pattern has venue/session/date
            if len(match.groups()) >= 3:

                return match.group(2)

            return match.group(1)

    return None


# ============================================================
# FORMAT EXTRACTION
# ============================================================

FORMAT_WORDS = [
    "IMAX 2D",
    "DOLBY CINEMA 2D",
    "DOLBY CINEMA",
    "4DX",
    "EPIQ",
    "ICE",
    "MX4D",
    "SCREEN X",
    "2D",
    "3D",
]


def extract_format(text):

    if not text:
        return ""

    upper = text.upper()

    # Longest / most specific first
    for fmt in FORMAT_WORDS:

        if fmt in upper:

            return fmt

    return ""


# ============================================================
# LANGUAGE EXTRACTION
# ============================================================

LANGUAGES = [
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


def extract_language(text):

    if not text:
        return ""

    upper = text.upper()

    found = []

    for language in LANGUAGES:

        if language in upper:

            found.append(
                language.title()
            )

    return ", ".join(found)


# ============================================================
# DISCOVER SHOWS FROM BMS PAGE
# ============================================================

def discover_shows(page):

    banner(
        "DISCOVERING TOXIC SHOWS AT CSWO"
    )

    print(
        f"Movie page:\n{MOVIE_PAGE}"
    )

    print()
    print(
        f"Format filter: "
        f"{FORMAT_FILTER if FORMAT_FILTER else 'ALL FORMATS'}"
    )

    discovered = {}

    # --------------------------------------------------------
    # Capture every navigation/request URL
    # --------------------------------------------------------

    captured_urls = []

    def capture_request(request):

        url = request.url

        if (
            "bookmyshow.com" in url.lower()
            and (
                "seat-layout" in url.lower()
                or "buytickets" in url.lower()
                or "session" in url.lower()
            )
        ):

            captured_urls.append(
                url
            )

    page.on(
        "request",
        capture_request
    )

    # --------------------------------------------------------
    # Open movie page
    # --------------------------------------------------------

    try:

        response = page.goto(
            MOVIE_PAGE,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        if response:

            print(
                f"Movie page HTTP status: "
                f"{response.status}"
            )

    except Exception as error:

        print(
            f"Movie page navigation error: "
            f"{error}"
        )

        return []

    # --------------------------------------------------------
    # Wait for BMS dynamic content
    # --------------------------------------------------------

    print(
        f"Waiting {DISCOVERY_WAIT} seconds "
        f"for BMS show data..."
    )

    page.wait_for_timeout(
        DISCOVERY_WAIT * 1000
    )

    # --------------------------------------------------------
    # Scroll page to trigger lazy loading
    # --------------------------------------------------------

    try:

        for _ in range(5):

            page.mouse.wheel(
                0,
                1500
            )

            page.wait_for_timeout(
                1000
            )

    except Exception:
        pass

    # --------------------------------------------------------
    # Capture DOM links
    # --------------------------------------------------------

    links = page.locator(
        "a"
    )

    link_count = links.count()

    print(
        f"Links found on page: "
        f"{link_count}"
    )

    for i in range(
        min(link_count, 3000)
    ):

        try:

            element = links.nth(i)

            href = element.get_attribute(
                "href"
            )

            if not href:
                continue

            text = element.inner_text(
                timeout=1000
            )

            combined = (
                (text or "")
                + " "
                + href
            )

            # Only care about this venue
            if VENUE_CODE.upper() not in combined.upper():

                # Still retain captured URLs below
                pass

            session_id = extract_session_id(
                href
            )

            if not session_id:
                continue

            show_time = extract_time(
                text
            )

            fmt = extract_format(
                combined
            )

            language = extract_language(
                combined
            )

            if not format_allowed(fmt):

                continue

            key = session_id

            discovered[key] = {
                "show_time": show_time or "",
                "session_id": session_id,
                "format": fmt or "",
                "language": language or "",
                "screen": "",
                "url": href,
            }

        except Exception:

            continue

    # --------------------------------------------------------
    # Process captured network URLs
    # --------------------------------------------------------

    for url in captured_urls:

        session_id = extract_session_id(
            url
        )

        if not session_id:
            continue

        # We don't always get format from URL.
        # Keep the session and let DOM data supply
        # the format where available.

        if session_id not in discovered:

            discovered[session_id] = {
                "show_time": "",
                "session_id": session_id,
                "format": "",
                "language": "",
                "screen": "",
                "url": url,
            }

    # --------------------------------------------------------
    # Filter by venue where possible
    # --------------------------------------------------------

    filtered = []

    for item in discovered.values():

        url = item["url"]

        # If URL explicitly contains another venue,
        # don't include it.

        if (
            "/seat-layout/"
            in url.lower()
        ):

            match = re.search(
                r"/seat-layout/ET\d+/([^/]+)/(\d+)/",
                url,
                re.I
            )

            if match:

                venue_from_url = (
                    match.group(1)
                )

                if (
                    venue_from_url.upper()
                    != VENUE_CODE.upper()
                ):

                    continue

        filtered.append(
            item
        )

    # --------------------------------------------------------
    # Sort by time
    # --------------------------------------------------------

    def sort_key(item):

        time_value = item.get(
            "show_time",
            ""
        )

        return time_value

    filtered.sort(
        key=sort_key
    )

    # --------------------------------------------------------
    # Print discovery
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("DISCOVERED SHOWS")
    print("=" * 80)

    if not filtered:

        print(
            "NO SHOWS DISCOVERED."
        )

    for index, item in enumerate(
        filtered,
        start=1
    ):

        print(
            f"{index:02d}. "
            f"{item['show_time'] or 'TIME UNKNOWN':<10} | "
            f"{item['format'] or 'FORMAT UNKNOWN':<20} | "
            f"Session {item['session_id']}"
        )

    print(
        f"\nTotal discovered: "
        f"{len(filtered)}"
    )

    print("=" * 80)

    return filtered


# ============================================================
# SEAT TOKEN PARSER
# ============================================================

def parse_seat_token(token):

    token = token.strip()

    if not token:
        return None

    token = token.replace(
        " ",
        ""
    )

    match = re.match(
        r"^([A-Za-z])(\d+)\+(\d+)$",
        token
    )

    if not match:
        return None

    letter = match.group(1).upper()

    numeric_code = match.group(2)

    seat_number = match.group(3)

    # No physical seat
    if numeric_code == "0":
        return None

    if numeric_code.startswith("1"):

        status = "AVAILABLE"

    elif numeric_code.startswith("2"):

        status = "SOLD"

    else:

        return None

    return {
        "seat_token": token,
        "seat_code": f"{letter}{numeric_code}",
        "seat_number": seat_number,
        "status": status,
    }


# ============================================================
# BMS SEAT LAYOUT
# ============================================================

def get_seat_layout(
    session_id
):

    # --------------------------------------------------------
    # This is the endpoint that was already working for us.
    # --------------------------------------------------------

    from curl_cffi import requests

    url = (
        "https://services-in.bookmyshow.com/"
        "doTrans.aspx"
    )

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": VENUE_CODE,
        "strParam1": session_id,
        "strParam2": "WEB",
        "strParam5": "Y",
        "strParam6": "Y",
        "strParam7": "N",
        "strFormat": "json",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 "
            "Safari/537.36"
        ),
        "Accept": (
            "application/json, text/plain, */*"
        ),
        "Content-Type": (
            "application/x-www-form-urlencoded; "
            "charset=UTF-8"
        ),
        "Origin": (
            "https://in.bookmyshow.com"
        ),
        "Referer": (
            MOVIE_PAGE
        ),
    }

    for attempt in range(
        1,
        4
    ):

        try:

            print(
                f"Seat layout attempt "
                f"{attempt}/3"
            )

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                impersonate="chrome120",
                timeout=30
            )

            print(
                f"HTTP status: "
                f"{response.status_code}"
            )

            if response.status_code != 200:

                if attempt < 3:
                    time.sleep(3)

                continue

            data = response.json()

            bookmyshow = data.get(
                "BookMyShow",
                {}
            )

            str_data = bookmyshow.get(
                "strData"
            )

            if str_data:

                print(
                    f"Seat layout received: "
                    f"{len(str_data)} bytes"
                )

                return str_data

        except Exception as error:

            print(
                f"Seat request error: "
                f"{error}"
            )

            if attempt < 3:
                time.sleep(3)

    return None


# ============================================================
# PARSE SEAT LAYOUT
# ============================================================

def parse_seat_layout(
    str_data,
    show
):

    if not str_data:

        return []

    sections = str_data.split(
        "||",
        1
    )

    if len(sections) != 2:

        print(
            "Unable to split seat layout."
        )

        return []

    category_section = sections[0]

    seat_section = sections[1]

    categories = {}

    # --------------------------------------------------------
    # Category parser
    # --------------------------------------------------------

    for part in category_section.split("|"):

        part = part.strip()

        if not part:
            continue

        pieces = part.split(":")

        if len(pieces) < 2:
            continue

        categories[
            pieces[1].strip()
        ] = pieces[0].strip()

    rows = []

    available = 0

    sold = 0

    # --------------------------------------------------------
    # Seat rows
    # --------------------------------------------------------

    for raw_row in seat_section.split("|"):

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        parts = raw_row.split(
            ":",
            3
        )

        if len(parts) < 4:
            continue

        row_number = parts[0].strip()

        row_name = parts[1].strip()

        category_code = parts[2].strip()

        seat_data = parts[3].strip()

        category = categories.get(
            category_code,
            category_code
        )

        for token in seat_data.split(":"):

            parsed = parse_seat_token(
                token
            )

            if not parsed:
                continue

            if parsed["status"] == "SOLD":

                sold += 1

            else:

                available += 1

            rows.append([
                timestamp(),
                MOVIE_NAME,
                EVENT_CODE,
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
                    "format",
                    ""
                ),
                row_number,
                row_name,
                category_code,
                category,
                parsed["seat_token"],
                parsed["seat_code"],
                parsed["seat_number"],
                parsed["status"],
            ])

    print(
        f"Seats: {len(rows)} | "
        f"Sold: {sold} | "
        f"Available: {available}"
    )

    return rows


# ============================================================
# SAVE SHOW DISCOVERY
# ============================================================

def save_shows(
    sheet,
    shows
):

    if not shows:
        return

    # --------------------------------------------------------
    # We clear old discovery data so each run reflects
    # current BMS sessions.
    # --------------------------------------------------------

    sheet.clear()

    sheet.update(
        "A1",
        [SHOW_HEADERS]
    )

    rows = []

    for show in shows:

        rows.append([
            timestamp(),
            MOVIE_NAME,
            EVENT_CODE,
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
            show.get(
                "url",
                ""
            ),
        ])

    sheet.append_rows(
        rows,
        value_input_option="USER_ENTERED"
    )

    print(
        f"Saved {len(rows)} discovered shows."
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

    # --------------------------------------------------------
    # One batch write.
    # --------------------------------------------------------

    sheet.append_rows(
        rows,
        value_input_option="USER_ENTERED"
    )

    print(
        f"Saved {len(rows)} seat records."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    banner(
        "BMS TOXIC CSWO SHOW DISCOVERY + SEAT TRACKER"
    )

    print(
        f"Timestamp : {timestamp()}"
    )

    print(
        f"Movie     : {MOVIE_NAME}"
    )

    print(
        f"Event     : {EVENT_CODE}"
    )

    print(
        f"Venue     : {VENUE_CODE}"
    )

    print(
        f"Date      : {SHOW_DATE}"
    )

    print(
        f"City      : {CITY}"
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

        print(
            f"Google Sheets error: {error}"
        )

        return

    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

    all_seats = []

    with sync_playwright() as p:

        print()
        print(
            "Launching Chromium..."
        )

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 900
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        # ----------------------------------------------------
        # DISCOVER
        # ----------------------------------------------------

        shows = discover_shows(
            page
        )

        # Save discovered sessions
        save_shows(
            show_sheet,
            shows
        )

        # ----------------------------------------------------
        # Process every discovered show
        # ----------------------------------------------------

        banner(
            "PROCESSING DISCOVERED SHOWS"
        )

        for index, show in enumerate(
            shows,
            start=1
        ):

            print()
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
                f"Session : "
                f"{show.get('session_id', '')}"
            )

            # ------------------------------------------------
            # Seat layout
            # ------------------------------------------------

            str_data = get_seat_layout(
                show["session_id"]
            )

            if not str_data:

                print(
                    "FAILED: No BMS seat layout."
                )

                continue

            rows = parse_seat_layout(
                str_data,
                show
            )

            all_seats.extend(
                rows
            )

            if index < len(shows):

                time.sleep(
                    DELAY_BETWEEN_SESSIONS
                )

        browser.close()

    # --------------------------------------------------------
    # Write seats once
    # --------------------------------------------------------

    banner(
        "WRITING ALL SEATS"
    )

    save_seats(
        seat_sheet,
        all_seats
    )

    # --------------------------------------------------------
    # Final
    # --------------------------------------------------------

    banner(
        "RUN COMPLETED"
    )

    print(
        f"Shows discovered : {len(shows)}"
    )

    print(
        f"Seat records     : {len(all_seats)}"
    )

    print(
        f"Format filter    : "
        f"{FORMAT_FILTER if FORMAT_FILTER else 'ALL FORMATS'}"
    )


if __name__ == "__main__":

    main()
