import os
import re
import json
import time
import base64
import datetime
from typing import Optional

import pytz
import gspread
from google.oauth2.service_account import Credentials
from curl_cffi import requests


# ============================================================
# CONFIGURATION
# ============================================================

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
CITY = "mumbai"
SHOW_DATE = "20260826"

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

SHEET_NAME = "BMS Seats"

IST = pytz.timezone("Asia/Kolkata")


# ============================================================
# BMS REQUEST CONFIG
# ============================================================

BMS_BASE = "https://services-in.bookmyshow.com"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-IN,en;q=0.9",
    "origin": "https://in.bookmyshow.com",
    "referer": "https://in.bookmyshow.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
}


# ============================================================
# GOOGLE SHEETS
# ============================================================

HEADERS_SHEET = [
    "Timestamp IST",
    "Event Code",
    "Venue Code",
    "Session ID",
    "Show Time",
    "Date",
    "City",
    "Row Number",
    "Row Name",
    "Category Code",
    "Category",
    "Seat Token",
    "Seat Code",
    "Seat Number",
    "Status",
]


# ============================================================
# CATEGORY MAP
# ============================================================

CATEGORY_MAP = {
    "A": "RECLINER",
    "B": "PREMIUM",
    "C": "EXECUTIVE XL",
    "D": "EXECUTIVE",
    "E": "NORMAL",
}


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def connect_google_sheets():

    print()
    print("=" * 70)
    print("Connecting to Google Sheets...")
    print("=" * 70)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = None

    # --------------------------------------------------------
    # METHOD 1: BASE64 SECRET
    # --------------------------------------------------------

    key_b64 = os.environ.get("GCP_SA_KEY_B64")

    if key_b64:
        try:
            decoded = base64.b64decode(key_b64).decode("utf-8")
            service_account_info = json.loads(decoded)

            credentials = Credentials.from_service_account_info(
                service_account_info,
                scopes=scopes
            )

            print("Google credentials loaded from GCP_SA_KEY_B64")

        except Exception as e:
            print("ERROR decoding GCP_SA_KEY_B64:")
            print(e)

    # --------------------------------------------------------
    # METHOD 2: JSON SECRET
    # --------------------------------------------------------

    if credentials is None:

        key_json = os.environ.get("GCP_SA_KEY")

        if key_json:

            try:
                service_account_info = json.loads(key_json)

                credentials = Credentials.from_service_account_info(
                    service_account_info,
                    scopes=scopes
                )

                print("Google credentials loaded from GCP_SA_KEY")

            except Exception as e:
                print("ERROR loading GCP_SA_KEY:")
                print(e)

    # --------------------------------------------------------
    # METHOD 3: LOCAL credentials.json
    # --------------------------------------------------------

    if credentials is None and os.path.exists("credentials.json"):

        try:

            credentials = Credentials.from_service_account_file(
                "credentials.json",
                scopes=scopes
            )

            print("Google credentials loaded from credentials.json")

        except Exception as e:

            print("ERROR loading credentials.json:")
            print(e)

    if credentials is None:

        raise RuntimeError(
            "Google credentials not found. "
            "Set GCP_SA_KEY_B64 or GCP_SA_KEY in GitHub Secrets."
        )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
        print(f"Using existing sheet: {SHEET_NAME}")

    except gspread.WorksheetNotFound:

        worksheet = spreadsheet.add_worksheet(
            title=SHEET_NAME,
            rows=10000,
            cols=len(HEADERS_SHEET)
        )

        print(f"Created sheet: {SHEET_NAME}")

    return worksheet


# ============================================================
# BMS REQUEST
# ============================================================

def bms_request(url, params=None, retries=3):

    for attempt in range(1, retries + 1):

        print(f"Attempt {attempt}/{retries}")

        try:

            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                impersonate="chrome",
                timeout=30,
            )

            print("HTTP status:", response.status_code)
            print("Response size:", len(response.content), "bytes")

            # ------------------------------------------------
            # CLOUDFLARE RATE LIMIT
            # ------------------------------------------------

            if response.status_code == 429:

                print("BMS/Cloudflare rate limited.")

                if attempt < retries:

                    wait_time = 30 * (2 ** (attempt - 1))

                    print(
                        f"Waiting {wait_time} seconds before retry..."
                    )

                    time.sleep(wait_time)

                    continue

                return None

            if response.status_code != 200:

                print("Unexpected HTTP status.")

                if attempt < retries:
                    time.sleep(5)
                    continue

                return None

            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            try:
                return response.json()

            except Exception:

                text = response.text

                print("Could not decode JSON.")
                print(text[:500])

                if attempt < retries:
                    time.sleep(5)
                    continue

                return None

        except Exception as e:

            print("Request error:")
            print(e)

            if attempt < retries:
                time.sleep(5)

    return None


# ============================================================
# DISCOVER ALL SHOWS
# ============================================================

def discover_shows():

    print()
    print("=" * 70)
    print("DISCOVERING ALL SHOWS")
    print("=" * 70)

    print("Event:", EVENT_CODE)
    print("Venue:", VENUE_CODE)
    print("Date:", SHOW_DATE)

    # --------------------------------------------------------
    # IMPORTANT:
    # This endpoint is the show/session discovery endpoint
    # used by the earlier all-show tracker.
    # --------------------------------------------------------

    url = (
        f"{BMS_BASE}/api/bookings/seatlayout/"
        f"{EVENT_CODE}/{VENUE_CODE}/{SHOW_DATE}"
    )

    print()
    print("Trying BMS show discovery...")

    data = bms_request(url)

    shows = []

    if data:

        shows = extract_show_sessions(data)

    # --------------------------------------------------------
    # FALLBACK:
    # The known sessions from the previous successful
    # discovery are used only if BMS discovery returns the
    # session list in an unexpected format.
    # --------------------------------------------------------

    if not shows:

        print()
        print("WARNING: Could not extract show sessions from response.")

        print(
            "Using previously discovered session list "
            "as fallback."
        )

        shows = [
            ("07:00 AM", "15925"),
            ("08:00 AM", "15934"),
            ("09:00 AM", "16072"),
            ("10:40 AM", "15926"),
            ("11:40 AM", "15933"),
            ("01:05 PM", "16073"),
            ("02:45 PM", "15927"),
            ("03:45 PM", "15932"),
            ("05:10 PM", "16074"),
            ("06:50 PM", "15928"),
            ("07:50 PM", "15931"),
            ("09:15 PM", "16075"),
            ("10:55 PM", "15929"),
            ("11:55 PM", "15930"),
        ]

    # remove duplicates

    unique = []

    seen = set()

    for show_time, session_id in shows:

        session_id = str(session_id)

        if session_id in seen:
            continue

        seen.add(session_id)

        unique.append(
            (show_time, session_id)
        )

    shows = unique

    print()
    print("=" * 70)
    print(f"SHOWS FOUND: {len(shows)}")
    print("=" * 70)

    for i, (show_time, session_id) in enumerate(shows, 1):

        print(
            f"{i:02d}. {show_time:<10} -> Session {session_id}"
        )

    return shows


# ============================================================
# EXTRACT SHOW SESSIONS
# ============================================================

def extract_show_sessions(data):

    shows = []

    def recursive_search(obj):

        if isinstance(obj, dict):

            # Common possible combinations

            session_id = None
            show_time = None

            for key, value in obj.items():

                key_lower = str(key).lower()

                if key_lower in (
                    "sessionid",
                    "session_id",
                    "session",
                    "sessioncode",
                    "sessioncodeid",
                ):

                    if value is not None:
                        session_id = str(value)

                if key_lower in (
                    "showtime",
                    "show_time",
                    "starttime",
                    "start_time",
                    "showtimeformatted",
                    "sessiontime",
                ):

                    if value is not None:
                        show_time = str(value)

            if session_id:

                if not show_time:
                    show_time = ""

                shows.append(
                    (show_time, session_id)
                )

            for value in obj.values():
                recursive_search(value)

        elif isinstance(obj, list):

            for item in obj:
                recursive_search(item)

    recursive_search(data)

    # clean duplicates

    result = []

    seen = set()

    for show_time, session_id in shows:

        if session_id in seen:
            continue

        seen.add(session_id)

        result.append(
            (show_time, session_id)
        )

    return result


# ============================================================
# SEAT TOKEN PARSER
# ============================================================

def parse_seat_token(token):

    """
    BMS examples:

    B1042+2
    B1048+6
    B2049+7

    IMPORTANT:

    The number after + is the actual seat number.

    The 10 / 20 inside the seat code indicates state.

    10 = AVAILABLE
    20 = SOLD

    Therefore:

    B1048+6
        seat code = B1048
        seat number = 6
        status = AVAILABLE

    B2049+7
        seat code = B2049
        seat number = 7
        status = SOLD
    """

    if not token:
        return None

    token = token.strip()

    if "+" not in token:
        return None

    left, seat_number = token.rsplit("+", 1)

    if not seat_number.isdigit():
        return None

    # Ignore placeholders

    if left.endswith("0"):
        return None

    # --------------------------------------------------------
    # BMS STATE:
    #
    # 10 = available
    # 20 = sold
    #
    # Seat codes generally look like:
    #
    # A1052
    # A20515
    # B1048
    # B2049
    # --------------------------------------------------------

    match = re.match(
        r"^([A-Z])([12])0(.+)$",
        left
    )

    if not match:
        return None

    row_letter = match.group(1)
    state_digit = match.group(2)
    seat_part = match.group(3)

    # Reconstruct original seat code

    seat_code = left

    if state_digit == "1":
        status = "AVAILABLE"

    elif state_digit == "2":
        status = "SOLD"

    else:
        return None

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": seat_number,
        "status": status,
        "row_letter": row_letter,
    }


# ============================================================
# PARSE RAW SEAT LAYOUT
# ============================================================

def parse_seat_layout(str_data, show_time, session_id):

    seats = []

    if not str_data:
        return seats

    # --------------------------------------------------------
    # strData contains sections like:
    #
    # 1:M:A000:...
    # 2:L:B000:...
    #
    # Each section represents one physical BMS row.
    # --------------------------------------------------------

    row_sections = re.split(
        r"\|(?=\d+:)",
        str_data
    )

    for section in row_sections:

        section = section.strip()

        if not section:
            continue

        # ----------------------------------------------------
        # ROW HEADER
        #
        # 1:M:A000:
        # 2:L:B000:
        # ----------------------------------------------------

        row_match = re.match(
            r"^(\d+):([^:]+):([^:]+):(.*)$",
            section
        )

        if not row_match:
            continue

        row_number = row_match.group(1)
        row_name = row_match.group(2)
        category_code = row_match.group(3)
        seat_data = row_match.group(4)

        # ----------------------------------------------------
        # Category based on first letter of category code
        # ----------------------------------------------------

        category_letter = category_code[:1]

        category = CATEGORY_MAP.get(
            category_letter,
            category_code
        )

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Seat entries are separated by +
        #
        # Example:
        #
        # A1052+1
        # A1053+2
        #
        # But the raw BMS format can have:
        #
        # A1052+1:A1053+2
        #
        # Therefore we locate seat tokens directly.
        # ----------------------------------------------------

        tokens = re.findall(
            r"[A-Z][12]0[0-9]+?\+[0-9]+",
            seat_data
        )

        # ----------------------------------------------------
        # Also support codes where the state portion is
        # embedded differently.
        # ----------------------------------------------------

        if not tokens:

            tokens = re.findall(
                r"[A-Z][0-9]+\+[0-9]+",
                seat_data
            )

        for token in tokens:

            parsed = parse_seat_token(token)

            if not parsed:
                continue

            seats.append({
                "timestamp": datetime.datetime.now(IST).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "event_code": EVENT_CODE,
                "venue_code": VENUE_CODE,
                "session_id": str(session_id),
                "show_time": show_time,
                "date": SHOW_DATE,
                "city": CITY,
                "row_number": row_number,
                "row_name": row_name,
                "category_code": category_code,
                "category": category,
                "seat_token": parsed["seat_token"],
                "seat_code": parsed["seat_code"],
                "seat_number": parsed["seat_number"],
                "status": parsed["status"],
            })

    return seats


# ============================================================
# GET SEAT LAYOUT FOR SESSION
# ============================================================

def get_seat_layout(session_id, show_time):

    print()
    print("=" * 70)
    print(
        f"PROCESSING SHOW {show_time} "
        f"| SESSION {session_id}"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # This is the seat-layout request used by the working
    # single-show tracker.
    # --------------------------------------------------------

    url = (
        f"{BMS_BASE}/api/seatlayout/"
        f"{EVENT_CODE}/{VENUE_CODE}/{session_id}"
    )

    data = bms_request(url)

    if not data:

        print(
            f"FAILED: No seat layout for session {session_id}"
        )

        return []

    # --------------------------------------------------------
    # BMS normally returns:
    #
    # blnSuccess
    # strData
    # --------------------------------------------------------

    if isinstance(data, dict):

        success = data.get("blnSuccess")

        if success is False:

            exception = data.get(
                "strException",
                ""
            )

            exception_code = data.get(
                "intException",
                ""
            )

            print(
                "BMS returned failure:"
            )

            print(
                "Exception:",
                exception_code
            )

            print(
                exception
            )

            return []

        str_data = data.get(
            "strData",
            ""
        )

    else:

        str_data = ""

    if not str_data:

        print(
            f"FAILED: Empty strData for session {session_id}"
        )

        return []

    seats = parse_seat_layout(
        str_data,
        show_time,
        session_id
    )

    available = sum(
        1 for seat in seats
        if seat["status"] == "AVAILABLE"
    )

    sold = sum(
        1 for seat in seats
        if seat["status"] == "SOLD"
    )

    print()
    print(
        f"SEATS: {len(seats)} | "
        f"AVAILABLE: {available} | "
        f"SOLD: {sold}"
    )

    return seats


# ============================================================
# GOOGLE SHEET WRITE
# ============================================================

def write_to_sheet(worksheet, rows):

    if not rows:

        print()
        print("No rows to write.")

        return

    print()
    print("=" * 70)
    print("WRITING TO GOOGLE SHEET")
    print("=" * 70)

    # --------------------------------------------------------
    # Make sure headers exist
    # --------------------------------------------------------

    existing_headers = worksheet.row_values(1)

    if existing_headers != HEADERS_SHEET:

        print(
            "Updating Google Sheet headers..."
        )

        worksheet.update(
            "A1:O1",
            [HEADERS_SHEET]
        )

    # --------------------------------------------------------
    # Clear old data.
    #
    # This run represents the current snapshot for all shows.
    # --------------------------------------------------------

    if worksheet.row_count > 1:

        worksheet.batch_clear([
            f"A2:O{worksheet.row_count}"
        ])

    values = []

    for seat in rows:

        values.append([
            seat["timestamp"],
            seat["event_code"],
            seat["venue_code"],
            seat["session_id"],
            seat["show_time"],
            seat["date"],
            seat["city"],
            seat["row_number"],
            seat["row_name"],
            seat["category_code"],
            seat["category"],
            seat["seat_token"],
            seat["seat_code"],
            seat["seat_number"],
            seat["status"],
        ])

    # --------------------------------------------------------
    # Google Sheets has API payload limits.
    # Write in chunks.
    # --------------------------------------------------------

    chunk_size = 500

    written = 0

    for i in range(
        0,
        len(values),
        chunk_size
    ):

        chunk = values[
            i:i + chunk_size
        ]

        start_row = written + 2
        end_row = start_row + len(chunk) - 1

        worksheet.update(
            f"A{start_row}:O{end_row}",
            chunk,
            value_input_option="RAW"
        )

        written += len(chunk)

        print(
            f"Written {written}/{len(values)} rows"
        )

    print()
    print(
        f"Google Sheet updated successfully. "
        f"{written} seats written."
    )


# ============================================================
# PRINT SHOW SUMMARY
# ============================================================

def print_summary(show_results):

    print()
    print("=" * 90)
    print("ALL SHOW SUMMARY")
    print("=" * 90)

    print(
        f"{'TIME':<12}"
        f"{'SESSION':<12}"
        f"{'AVAILABLE':<12}"
        f"{'SOLD':<10}"
        f"{'TOTAL':<10}"
    )

    print("-" * 90)

    total_available = 0
    total_sold = 0

    for result in show_results:

        available = result["available"]
        sold = result["sold"]
        total = result["total"]

        total_available += available
        total_sold += sold

        print(
            f"{result['show_time']:<12}"
            f"{result['session_id']:<12}"
            f"{available:<12}"
            f"{sold:<10}"
            f"{total:<10}"
        )

    print("-" * 90)

    print(
        f"{'TOTAL':<24}"
        f"{total_available:<12}"
        f"{total_sold:<10}"
        f"{total_available + total_sold:<10}"
    )

    print("=" * 90)


# ============================================================
# PARSER TEST
# ============================================================

def test_parser():

    print()
    print("=" * 70)
    print("TESTING BMS SEAT PARSER")
    print("=" * 70)

    tests = [
        "B1042+2",
        "B1043+3",
        "A1052+1",
        "A1053+2",
        "B1048+6",
        "B2049+7",
        "D10216+10",
        "A0+0",
        "B0+0",
    ]

    for token in tests:

        result = parse_seat_token(token)

        print(
            f"{token:<15} -> {result}"
        )

    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("Starting BMS ALL-SHOW Seat Tracker...")
    print("=" * 70)

    print(
        datetime.datetime.now(IST).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    test_parser()

    # --------------------------------------------------------
    # Discover all shows
    # --------------------------------------------------------

    shows = discover_shows()

    if not shows:

        print(
            "ERROR: No shows found."
        )

        return

    # --------------------------------------------------------
    # Connect Google Sheets
    # --------------------------------------------------------

    worksheet = connect_google_sheets()

    all_seats = []

    show_results = []

    # --------------------------------------------------------
    # Process every show
    # --------------------------------------------------------

    for index, (
        show_time,
        session_id
    ) in enumerate(shows, 1):

        print()
        print(
            f"SHOW {index}/{len(shows)}"
        )

        seats = get_seat_layout(
            session_id,
            show_time
        )

        if not seats:

            show_results.append({
                "show_time": show_time,
                "session_id": session_id,
                "available": 0,
                "sold": 0,
                "total": 0,
            })

            # Small delay even after failure
            time.sleep(3)

            continue

        available = sum(
            1
            for seat in seats
            if seat["status"] == "AVAILABLE"
        )

        sold = sum(
            1
            for seat in seats
            if seat["status"] == "SOLD"
        )

        show_results.append({
            "show_time": show_time,
            "session_id": session_id,
            "available": available,
            "sold": sold,
            "total": len(seats),
        })

        all_seats.extend(seats)

        # ----------------------------------------------------
        # IMPORTANT:
        # Do not hammer BMS between sessions.
        # ----------------------------------------------------

        time.sleep(5)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print_summary(
        show_results
    )

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

    write_to_sheet(
        worksheet,
        all_seats
    )

    print()
    print("=" * 70)
    print("BMS ALL-SHOW TRACKING COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()
