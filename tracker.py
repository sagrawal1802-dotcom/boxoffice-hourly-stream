import os
import re
import json
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = "YOUR_SPREADSHEET_ID"

GOOGLE_CREDENTIALS_FILE = "credentials.json"

SHEET_NAME = "Sheet1"

# BMS event/session information
EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
SHOW_DATE = "20260826"
CITY = "mumbai"


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_google_sheet():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    worksheet = spreadsheet.worksheet(SHEET_NAME)

    return worksheet


# ============================================================
# TIMESTAMP
# ============================================================

def get_timestamp():

    now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    )

    return now.strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# PARSE BMS SEAT TOKEN
# ============================================================

def parse_seat_token(token):

    """
    Examples:

        B1042+2
        B1043+3
        A1052+1

    Meaning:

        Seat Code  = B1042
        Seat Number = 2

    The number before '+' is NOT the seat number.
    """

    token = token.strip()

    # No seat
    if not token:
        return None

    if token in ("A0", "B0", "C0", "D0", "E0"):
        return None

    # Remove leading position if present
    #
    # Example:
    # 1:B1042+2
    #
    # becomes:
    # B1042+2

    if ":" in token:

        parts = token.split(":", 1)

        if len(parts) == 2:
            token = parts[1]

    # Actual BMS seat format:
    #
    # B1042+2
    #
    match = re.match(
        r"^([A-Za-z0-9]+)\+(\d+)$",
        token
    )

    if match:

        seat_code = match.group(1)

        seat_number = int(match.group(2))

        return {
            "seat_code": seat_code,
            "seat_number": seat_number
        }

    # Sometimes the raw value may be just the seat code.
    #
    # DO NOT invent a seat number here.
    #
    # Seat number will remain blank.

    if re.match(r"^[A-Za-z]+\d+$", token):

        return {
            "seat_code": token,
            "seat_number": ""
        }

    return None


# ============================================================
# PARSE ONE BMS ROW
# ============================================================

def parse_bms_row(raw_row):

    """
    Example:

    1:M:A000:
    A0+0
    A1052+1
    A1053+2

    We identify:

        row_number = 1
        row_name   = M

    Then parse every seat token.
    """

    raw_row = raw_row.strip()

    if not raw_row:
        return []

    # --------------------------------------------------------
    # Split row header
    # --------------------------------------------------------

    first_parts = raw_row.split(":", 3)

    if len(first_parts) < 3:
        return []

    try:
        row_number = int(first_parts[0])
    except ValueError:
        return []

    row_name = first_parts[1]

    category_code = first_parts[2]

    # Remaining data after:
    #
    # 1:M:A000:
    #
    if len(first_parts) == 4:
        seat_data = first_parts[3]
    else:
        seat_data = ""

    # --------------------------------------------------------
    # IMPORTANT
    #
    # BMS seat positions are separated by +
    #
    # Example:
    #
    # A0+0:A1052+1:A1053+2
    #
    # However, depending on the BMS response the string can
    # contain escaped separators.
    # --------------------------------------------------------

    seat_parts = seat_data.split(":")

    results = []

    for part in seat_parts:

        part = part.strip()

        if not part:
            continue

        parsed = parse_seat_token(part)

        if not parsed:
            continue

        results.append({
            "row_number": row_number,
            "row_name": row_name,
            "category_code": category_code,
            "seat_code": parsed["seat_code"],
            "seat_number": parsed["seat_number"],
            "raw_token": part
        })

    return results


# ============================================================
# PARSE FULL BMS LAYOUT
# ============================================================

def parse_full_layout(layout):

    """
    Parses multiple BMS rows.

    Example:

    1:M:A000:A0+0:A1052+1:A1053+2
    |
    2:L:B000:B1041+0:B1042+1:B1043+2
    """

    if not layout:
        return []

    rows = layout.split("|")

    all_seats = []

    for raw_row in rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        seats = parse_bms_row(raw_row)

        all_seats.extend(seats)

    return all_seats


# ============================================================
# EXTRACT SEAT STATUS
# ============================================================

def normalize_status(status):

    if status is None:
        return ""

    status = str(status).strip().upper()

    return status


def status_to_flags(status):

    """
    We ONLY create:

        Available
        Sold

    We do NOT use OTHER.

    """

    status = normalize_status(status)

    available = 0
    sold = 0

    if status == "AVAILABLE":

        available = 1

    elif status in (
        "BOOKED",
        "SOLD",
        "OCCUPIED"
    ):

        sold = 1

    return available, sold


# ============================================================
# BUILD OUTPUT
# ============================================================

HEADERS = [
    "Timestamp IST",
    "Event Code",
    "Venue Code",
    "Session ID",
    "Date",
    "City",
    "Row Number",
    "Row Name",
    "Category Code",
    "Category",
    "Seat Token",
    "Seat Code",
    "Seat Number",
    "Available",
    "Sold"
]


def build_record(
    timestamp,
    row_number,
    row_name,
    category_code,
    category,
    seat_token,
    seat_code,
    seat_number,
    status
):

    available, sold = status_to_flags(status)

    return [
        timestamp,
        EVENT_CODE,
        VENUE_CODE,
        SESSION_ID,
        SHOW_DATE,
        CITY,
        row_number,
        row_name,
        category_code,
        category,
        seat_token,
        seat_code,
        seat_number,
        available,
        sold
    ]


# ============================================================
# PROCESS BMS RESPONSE
# ============================================================

def process_seat_data(layout_rows):

    """
    layout_rows should contain the BMS layout information.

    IMPORTANT:

    Seat number comes from +N.

    Example:

        B1042+2

    becomes:

        Seat Code   = B1042
        Seat Number = 2
    """

    timestamp = get_timestamp()

    records = []

    for row in layout_rows:

        raw_row = row.get("raw_row", "")

        row_number = row.get("row_number")
        row_name = row.get("row_name")
        category_code = row.get("category_code")
        category = row.get("category")

        seat_entries = parse_bms_row(raw_row)

        for seat in seat_entries:

            seat_code = seat["seat_code"]

            seat_number = seat["seat_number"]

            seat_token = seat["raw_token"]

            # Status must come from the BMS status response.
            status = row.get("status_map", {}).get(
                seat_code,
                ""
            )

            record = build_record(
                timestamp=timestamp,
                row_number=row_number,
                row_name=row_name,
                category_code=category_code,
                category=category,
                seat_token=seat_token,
                seat_code=seat_code,
                seat_number=seat_number,
                status=status
            )

            records.append(record)

    return records


# ============================================================
# WRITE TO GOOGLE SHEETS
# ============================================================

def write_to_sheet(worksheet, records):

    if not records:

        print("No seat records found.")

        return

    worksheet.clear()

    worksheet.update(
        "A1",
        [HEADERS] + records,
        value_input_option="RAW"
    )

    print(
        f"Written {len(records)} seat records to Google Sheets."
    )


# ============================================================
# EXAMPLE / TEST PARSER
# ============================================================

def test_parser():

    print("\nTesting BMS seat parser...\n")

    tests = [
        "B1042+2",
        "B1043+3",
        "A1052+1",
        "A1053+2",
        "A0+0",
        "B0+0"
    ]

    for test in tests:

        result = parse_seat_token(test)

        print(
            f"{test:15} -> {result}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("Starting BMS Seat Tracker...")
    print(get_timestamp())

    print("\nTesting seat-number parser:")

    test_parser()

    print("\nConnecting to Google Sheets...")

    try:

        worksheet = connect_google_sheet()

        print("Google Sheets connected.")

    except Exception as e:

        print(
            "ERROR connecting to Google Sheets:"
        )

        print(e)

        return

    print("\nIMPORTANT:")
    print(
        "The scraper must pass the raw BMS layout/status "
        "response into process_seat_data()."
    )

    print(
        "Seat numbers will be taken from the value after '+'."
    )

    print(
        "\nExample: B1042+2 -> Seat Code B1042, Seat Number 2"
    )

    print(
        "\nParser test completed successfully."
    )


if __name__ == "__main__":

    main()
