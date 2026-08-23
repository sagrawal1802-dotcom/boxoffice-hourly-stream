import os
import re
import json
import time
import datetime
import requests
import gspread

from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"
CITY = "mumbai"
REGION_CODE = "MUMBAI"

VENUE_CODE = "CSWO"
VENUE_NAME = "CSWO"

DATE_CODE = "20260826"

MOVIE_EVENT_CODE = "ET00379311"

# Known Toxic event codes discovered for CSWO
EVENT_CODES = [
    "ET00379311",   # Hindi 2D
    "ET00513458",   # IMAX
    "ET00513506",   # 4DX
]

GOOGLE_SHEET_NAME = "Toxic_CSWO"

# Change this if your environment uses another credential variable
GOOGLE_CREDS_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "credentials.json"
)


# ============================================================
# EXACT GOOGLE SHEET COLUMNS
# ============================================================

HEADERS = [
    "Timestamp",
    "Movie",
    "Event Code",
    "Venue",
    "Session ID",
    "Format",
    "Show Time",
    "Date",
    "City",
    "Row ID",
    "Row Name",
    "Category Code",
    "Category Name",
    "Seat Token",
    "Seat Code",
    "Seat Number",
    "Status",
    "Price",
    "Gross",
    "Source",
]


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://in.bookmyshow.com/",
    "Origin": "https://in.bookmyshow.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
})


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_google_sheet():

    print("=" * 90)
    print("CONNECTING TO GOOGLE SHEETS")
    print("=" * 90)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_file(
        GOOGLE_CREDS_FILE,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

    spreadsheet_id = os.environ.get("SPREADSHEET_ID")

    if not spreadsheet_id:
        raise RuntimeError(
            "SPREADSHEET_ID environment variable is missing."
        )

    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        sheet = spreadsheet.worksheet(GOOGLE_SHEET_NAME)

    except gspread.WorksheetNotFound:

        print(f"Creating worksheet: {GOOGLE_SHEET_NAME}")

        sheet = spreadsheet.add_worksheet(
            title=GOOGLE_SHEET_NAME,
            rows=10000,
            cols=len(HEADERS)
        )

    # Force exact headers
    current_headers = sheet.row_values(1)

    if current_headers != HEADERS:

        print("Updating Google Sheet headers...")

        sheet.update(
            range_name=f"A1:T1",
            values=[HEADERS]
        )

    print("Google Sheets connected.")

    return sheet


# ============================================================
# SHOWTIME API
# ============================================================

def get_showtime_data(event_code):

    url = (
        "https://in.bookmyshow.com/"
        "api/movies-data/v5/showtimes-by-event/primary-dynamic"
    )

    params = {
        "etCodes": "*",
        "dateCode": DATE_CODE,
        "isDesktop": "true",
        "regionCode": REGION_CODE,
        "xLocationShared": "false",
        "memberId": "",
        "lsId": "",
        "subCode": "",
        "appCode": "WEB",
        "language": "hindi",
        "refEventCode": event_code,
    }

    print()
    print("=" * 90)
    print("REQUESTING BMS SHOWTIME DATA")
    print("=" * 90)

    print("Endpoint:")
    print(url)

    for attempt in range(1, 4):

        try:

            print(f"Attempt {attempt}/3")

            response = session.get(
                url,
                params=params,
                timeout=30
            )

            print(
                f"HTTP status: {response.status_code}"
            )

            print(
                f"Response size: {len(response.content)}"
            )

            if response.status_code == 200:

                data = response.json()

                print("BMS showtime JSON received.")

                return data

            time.sleep(2)

        except Exception as e:

            print(f"Request error: {e}")

            time.sleep(2)

    return None


# ============================================================
# GENERIC RECURSIVE SEARCH
# ============================================================

def recursive_find_objects(obj, results=None):

    if results is None:
        results = []

    if isinstance(obj, dict):

        results.append(obj)

        for value in obj.values():

            recursive_find_objects(
                value,
                results
            )

    elif isinstance(obj, list):

        for item in obj:

            recursive_find_objects(
                item,
                results
            )

    return results


# ============================================================
# SHOW DISCOVERY
# ============================================================

def discover_cswo_shows(data):

    shows = []

    if not data:
        return shows

    objects = recursive_find_objects(data)

    seen = set()

    for obj in objects:

        # ----------------------------------------------------
        # Try to identify venue
        # ----------------------------------------------------

        text = json.dumps(
            obj,
            ensure_ascii=False
        ).lower()

        if "cswo" not in text:
            continue

        # ----------------------------------------------------
        # Search for session IDs
        # ----------------------------------------------------

        session_id = None

        possible_session_keys = [
            "sessionId",
            "sessionID",
            "session_id",
            "sessionCode",
            "sessionCodeId",
            "session",
        ]

        for key in possible_session_keys:

            value = obj.get(key)

            if value is not None:

                value_string = str(value)

                if value_string.isdigit():

                    session_id = value_string
                    break

        if not session_id:
            continue

        # ----------------------------------------------------
        # Event code
        # ----------------------------------------------------

        event_code = None

        for key in [
            "eventCode",
            "eventcode",
            "eventId",
            "eventID",
        ]:

            value = obj.get(key)

            if value:

                value = str(value)

                if value.startswith("ET"):

                    event_code = value
                    break

        if not event_code:
            event_code = MOVIE_EVENT_CODE

        # ----------------------------------------------------
        # Venue
        # ----------------------------------------------------

        venue = VENUE_CODE

        # ----------------------------------------------------
        # Showtime
        # ----------------------------------------------------

        show_time = ""

        for key in [
            "showTime",
            "showtime",
            "showTimeLabel",
            "displayTime",
            "time",
            "startTime",
        ]:

            value = obj.get(key)

            if value:

                show_time = str(value)
                break

        # ----------------------------------------------------
        # Format
        # ----------------------------------------------------

        fmt = ""

        for key in [
            "format",
            "formatName",
            "experience",
            "experienceName",
            "languageFormat",
        ]:

            value = obj.get(key)

            if value:

                fmt = str(value)
                break

        # ----------------------------------------------------
        # Venue name
        # ----------------------------------------------------

        venue_text = ""

        for key in [
            "venueName",
            "cinemaName",
            "theatreName",
            "name",
        ]:

            value = obj.get(key)

            if value:

                venue_text = str(value)

                if (
                    "cswo" in venue_text.lower()
                    or venue_text.upper() == VENUE_CODE
                ):

                    break

        # ----------------------------------------------------
        # Dedup
        # ----------------------------------------------------

        key = (
            event_code,
            session_id,
        )

        if key in seen:
            continue

        seen.add(key)

        shows.append({
            "event_code": event_code,
            "venue_code": VENUE_CODE,
            "venue_name": venue_text or VENUE_NAME,
            "session_id": session_id,
            "show_time": show_time,
            "format": fmt,
        })

    return shows


# ============================================================
# FALLBACK SHOW DISCOVERY
# ============================================================

def discover_shows_from_json(data):

    """
    More permissive recursive discovery.

    Used when the first parser doesn't find enough shows.
    """

    found = []

    if not data:
        return found

    objects = recursive_find_objects(data)

    seen = set()

    for obj in objects:

        session_id = None

        for key in [
            "sessionId",
            "sessionID",
            "session_id",
            "sessionCode",
        ]:

            value = obj.get(key)

            if value is not None:

                value = str(value)

                if value.isdigit():

                    session_id = value
                    break

        if not session_id:
            continue

        event_code = None

        for key in [
            "eventCode",
            "eventcode",
        ]:

            value = obj.get(key)

            if value:

                value = str(value)

                if value.startswith("ET"):

                    event_code = value
                    break

        if event_code not in EVENT_CODES:
            continue

        text = json.dumps(
            obj,
            ensure_ascii=False
        ).lower()

        if "cswo" not in text:
            continue

        show_time = ""

        for key in [
            "showTime",
            "showtime",
            "displayTime",
            "time",
        ]:

            value = obj.get(key)

            if value:

                show_time = str(value)
                break

        fmt = ""

        for key in [
            "format",
            "formatName",
            "experience",
            "experienceName",
        ]:

            value = obj.get(key)

            if value:

                fmt = str(value)
                break

        key = (
            event_code,
            session_id
        )

        if key in seen:
            continue

        seen.add(key)

        found.append({
            "event_code": event_code,
            "venue_code": VENUE_CODE,
            "venue_name": VENUE_NAME,
            "session_id": session_id,
            "show_time": show_time,
            "format": fmt,
        })

    return found


# ============================================================
# SEAT API
# ============================================================

def get_seat_layout(event_code, session_id):

    url = (
        "https://in.bookmyshow.com/"
        "api/movies-data/seatlayout/v1/primary"
    )

    params = {
        "eventCode": event_code,
        "dateCode": DATE_CODE,
        "regionCode": REGION_CODE,
        "venueCode": VENUE_CODE,
        "sessionId": session_id,
    }

    for attempt in range(1, 4):

        try:

            response = session.get(
                url,
                params=params,
                timeout=30
            )

            print(
                f"Seat API: {response.status_code} | "
                f"{len(response.content)} bytes"
            )

            if response.status_code == 200:

                try:
                    return response.json()
                except Exception:
                    return response.text

            time.sleep(1)

        except Exception as e:

            print(
                f"Seat API error: {e}"
            )

            time.sleep(2)

    return None


# ============================================================
# SEAT TOKEN PARSER
# ============================================================

SEAT_TOKEN_RE = re.compile(
    r"([A-E])(\d+)(?:\+)(\d+)"
)


def parse_seat_token(token):

    if not token:
        return None

    match = SEAT_TOKEN_RE.search(
        str(token)
    )

    if not match:
        return None

    row_letter = match.group(1)

    seat_code = (
        match.group(1)
        + match.group(2)
    )

    seat_number = match.group(3)

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": seat_number,
        "row_letter": row_letter,
    }


# ============================================================
# RECURSIVE STRING EXTRACTION
# ============================================================

def collect_strings(obj, output=None):

    if output is None:
        output = []

    if isinstance(obj, str):

        output.append(obj)

    elif isinstance(obj, dict):

        for key, value in obj.items():

            # Include key/value combinations where useful
            if isinstance(value, str):

                output.append(value)

            collect_strings(
                value,
                output
            )

    elif isinstance(obj, list):

        for item in obj:

            collect_strings(
                item,
                output
            )

    return output


# ============================================================
# SEAT STATUS DETECTION
# ============================================================

def determine_status(text):

    upper = str(text).upper()

    if "SOLD" in upper:
        return "SOLD"

    if "AVAILABLE" in upper:
        return "AVAILABLE"

    if "BOOKED" in upper:
        return "SOLD"

    if "UNAVAILABLE" in upper:
        return "UNAVAILABLE"

    if "BLOCKED" in upper:
        return "BLOCKED"

    return "AVAILABLE"


# ============================================================
# CATEGORY MAPPING
# ============================================================

CATEGORY_MAP = {
    "A": "RECLINER",
    "B": "PREMIUM",
    "C": "EXECUTIVE XL",
    "D": "EXECUTIVE",
    "E": "NORMAL",
}


def get_category_name(row_letter, category_code):

    if category_code and category_code != "A000":

        return category_code

    return CATEGORY_MAP.get(
        row_letter,
        category_code or ""
    )


# ============================================================
# SEAT EXTRACTION
# ============================================================

def extract_seats(
    seat_data,
    show
):

    seats = []

    if not seat_data:
        return seats

    # --------------------------------------------------------
    # Convert JSON to string for fallback token discovery
    # --------------------------------------------------------

    if isinstance(seat_data, str):

        raw_text = seat_data

    else:

        try:

            raw_text = json.dumps(
                seat_data,
                ensure_ascii=False
            )

        except Exception:

            raw_text = str(
                seat_data
            )

    # --------------------------------------------------------
    # Find every seat token
    # --------------------------------------------------------

    tokens = re.findall(
        r"[A-E][12]\d+\+\d+",
        raw_text
    )

    # Some layouts use other numeric patterns.
    # Keep the more general fallback too.
    if not tokens:

        tokens = re.findall(
            r"[A-E]\d+\+\d+",
            raw_text
        )

    # Preserve order but remove duplicates
    unique_tokens = list(
        dict.fromkeys(tokens)
    )

    # --------------------------------------------------------
    # Build seat records
    # --------------------------------------------------------

    for token in unique_tokens:

        parsed = parse_seat_token(
            token
        )

        if not parsed:
            continue

        row_letter = parsed[
            "row_letter"
        ]

        # ----------------------------------------------------
        # Try to locate status around token
        # ----------------------------------------------------

        token_position = raw_text.find(
            token
        )

        context_start = max(
            0,
            token_position - 300
        )

        context_end = min(
            len(raw_text),
            token_position + 500
        )

        context = raw_text[
            context_start:context_end
        ]

        status = determine_status(
            context
        )

        # ----------------------------------------------------
        # Row name
        # ----------------------------------------------------

        row_name = row_letter

        # ----------------------------------------------------
        # Category
        # ----------------------------------------------------

        category_code = "A000"

        # Search nearby JSON text for category
        category_match = re.search(
            r'"(?:strSeatType|seatType|categoryCode|strCategoryCode)"'
            r'\s*:\s*"([^"]+)"',
            context,
            re.IGNORECASE
        )

        if category_match:

            category_code = (
                category_match.group(1)
            )

        category_name = get_category_name(
            row_letter,
            category_code
        )

        # ----------------------------------------------------
        # Row ID
        # ----------------------------------------------------

        row_id = ""

        # ----------------------------------------------------
        # Price intentionally blank
        # ----------------------------------------------------

        price = ""

        gross = ""

        # ----------------------------------------------------
        # Source
        # ----------------------------------------------------

        source = "BMS_SEAT_API"

        timestamp = datetime.datetime.now(
            datetime.timezone.utc
        ).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        seats.append([
            timestamp,
            MOVIE_NAME,
            show["event_code"],
            show["venue_code"],
            show["session_id"],
            show["format"],
            show["show_time"],
            DATE_CODE,
            CITY,
            row_id,
            row_name,
            category_code,
            category_name,
            parsed["seat_token"],
            parsed["seat_code"],
            parsed["seat_number"],
            status,
            price,
            gross,
            source,
        ])

    return seats


# ============================================================
# WRITE TO GOOGLE SHEETS
# ============================================================

def write_rows(sheet, rows):

    if not rows:

        print("No seat records.")
        return

    print()
    print("=" * 90)
    print("WRITING TO GOOGLE SHEETS")
    print("=" * 90)

    # --------------------------------------------------------
    # Ensure headers are correct
    # --------------------------------------------------------

    sheet.update(
        range_name="A1:T1",
        values=[HEADERS]
    )

    # --------------------------------------------------------
    # Clear old data
    # --------------------------------------------------------

    if sheet.row_count > 1:

        sheet.batch_clear([
            "A2:T100000"
        ])

    # --------------------------------------------------------
    # Deduplicate
    #
    # IMPORTANT:
    # Use session ID + seat token.
    # Seat token is index 13 in the new structure.
    # --------------------------------------------------------

    unique = {}

    for row in rows:

        key = (
            row[4],    # Session ID
            row[13],   # Seat Token
        )

        unique[key] = row

    final_rows = list(
        unique.values()
    )

    print(
        f"Seat records before dedupe : {len(rows)}"
    )

    print(
        f"Seat records after dedupe  : {len(final_rows)}"
    )

    # --------------------------------------------------------
    # One large write
    # --------------------------------------------------------

    chunk_size = 5000

    for start in range(
        0,
        len(final_rows),
        chunk_size
    ):

        chunk = final_rows[
            start:start + chunk_size
        ]

        start_row = start + 2

        end_row = (
            start_row
            + len(chunk)
            - 1
        )

        range_name = (
            f"A{start_row}:T{end_row}"
        )

        sheet.update(
            range_name=range_name,
            values=chunk
        )

        print(
            f"Written rows "
            f"{start_row}-{end_row}"
        )

    print(
        f"Google Sheet updated successfully. "
        f"{len(final_rows)} seats written."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 90)
    print("BMS TOXIC CSWO ALL-FORMAT TRACKER")
    print("=" * 90)

    timestamp = datetime.datetime.now(
        datetime.timezone.utc
    ).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"Timestamp : {timestamp}"
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
        f"Date      : {DATE_CODE}"
    )

    print(
        "Formats   : ALL"
    )

    # --------------------------------------------------------
    # Google Sheet
    # --------------------------------------------------------

    sheet = connect_google_sheet()

    # --------------------------------------------------------
    # Discover shows
    # --------------------------------------------------------

    print()
    print("=" * 90)
    print("DISCOVERING CSWO SHOWS")
    print("=" * 90)

    all_shows = []

    for event_code in EVENT_CODES:

        print()
        print(
            f"Checking event code: {event_code}"
        )

        data = get_showtime_data(
            event_code
        )

        if not data:

            print(
                "No showtime data."
            )

            continue

        shows = discover_cswo_shows(
            data
        )

        if not shows:

            shows = discover_shows_from_json(
                data
            )

        for show in shows:

            key = (
                show["event_code"],
                show["session_id"]
            )

            if not any(
                (
                    x["event_code"],
                    x["session_id"]
                ) == key
                for x in all_shows
            ):

                all_shows.append(show)

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    all_shows.sort(
        key=lambda x: (
            x["format"],
            x["show_time"],
            x["session_id"],
        )
    )

    print()
    print("=" * 90)
    print("DISCOVERED CSWO SHOWS")
    print("=" * 90)

    if not all_shows:

        print("NO CSWO SHOWS DISCOVERED.")
        return

    for show in all_shows:

        print(
            f'{show["format"]:<15} | '
            f'{show["show_time"]:<10} | '
            f'{show["event_code"]} | '
            f'Session {show["session_id"]}'
        )

    print()
    print(
        f"TOTAL CSWO SHOWS: {len(all_shows)}"
    )

    # --------------------------------------------------------
    # Seat extraction
    # --------------------------------------------------------

    all_rows = []

    print()
    print("=" * 90)
    print("PROCESSING SEAT LAYOUTS")
    print("=" * 90)

    for index, show in enumerate(
        all_shows,
        start=1
    ):

        print()
        print(
            f'[{index}/{len(all_shows)}] '
            f'{show["format"]} | '
            f'{show["show_time"]} | '
            f'{show["session_id"]}'
        )

        seat_data = get_seat_layout(
            show["event_code"],
            show["session_id"]
        )

        if not seat_data:

            print(
                "No seat layout response."
            )

            continue

        rows = extract_seats(
            seat_data,
            show
        )

        print(
            f"Seats parsed: {len(rows)}"
        )

        all_rows.extend(rows)

    # --------------------------------------------------------
    # Write
    # --------------------------------------------------------

    write_rows(
        sheet,
        all_rows
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 90)
    print("FINAL SUMMARY")
    print("=" * 90)

    print(
        f"Shows discovered : {len(all_shows)}"
    )

    print(
        f"Seat records      : {len(all_rows)}"
    )

    breakdown = {}

    for show in all_shows:

        key = (
            show["event_code"],
            show["format"]
        )

        breakdown[key] = (
            breakdown.get(key, 0) + 1
        )

    print()
    print("Event / Format breakdown:")

    for (
        event_code,
        fmt
    ), count in sorted(
        breakdown.items()
    ):

        print(
            f"{event_code} | "
            f"{fmt} | "
            f"{count} shows"
        )

    print()
    print(
        "BMS TOXIC CSWO TRACKER COMPLETED"
    )


if __name__ == "__main__":
    main()
