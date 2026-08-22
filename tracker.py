import os
import re
import json
import time
import datetime
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = "YOUR_SPREADSHEET_ID"

GOOGLE_CREDENTIALS_FILE = "credentials.json"

SHEET_NAME = "BMS_Data"

BMS_URL = "https://in.bookmyshow.com/"

TARGET_DATE = "20260826"
CITY = "mumbai"

# Optional event/session filters
TARGET_EVENT_CODE = "ET00379311"
TARGET_VENUE_CODE = "CSWO"
TARGET_SESSION_ID = "15925"


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

    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=SHEET_NAME,
            rows=10000,
            cols=20
        )

    return worksheet


# ============================================================
# OUTPUT HEADERS
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


# ============================================================
# LAYOUT PARSER
# ============================================================

def parse_layout_row(raw_row):
    """
    Parses a BMS layout row.

    Example:

    2:L:B000:B1041+1:B1042+2:B1043+3:B0+0:B0

    Interpretation:

    2:L
        Row number = 2
        Row name   = L

    B1041+1
        Seat Token  = B1041
        Seat Number = 1

    B1042+2
        Seat Token  = B1042
        Seat Number = 2

    B1043+3
        Seat Token  = B1043
        Seat Number = 3

    B0
        No physical seat
    """

    if not raw_row:
        return []

    # Remove escaped formatting if necessary
    raw_row = raw_row.strip()

    # --------------------------------------------------------
    # Split first-level row structure
    # --------------------------------------------------------

    first_parts = raw_row.split(":", 3)

    if len(first_parts) < 4:
        return []

    row_number = first_parts[0].strip()
    row_name = first_parts[1].strip()
    category_code = first_parts[2].strip()

    seat_string = first_parts[3].strip()

    # --------------------------------------------------------
    # Category can sometimes contain additional layout data.
    # We only care about the actual seat sequence.
    # --------------------------------------------------------

    seats = []

    # Each seat is separated by +
    #
    # Example:
    # B1041+1
    # B1042+2
    # B1043+3
    #
    # However the first seat can sometimes be represented
    # differently, so we process each token carefully.
    parts = seat_string.split("+")

    for part in parts:

        part = part.strip()

        if not part:
            continue

        # ----------------------------------------------------
        # Seat token can contain:
        #
        # B1042+2
        #
        # After splitting by + this becomes:
        #
        # B1042
        # 2
        #
        # Therefore we handle the layout as alternating
        # seat-token / seat-number values.
        # ----------------------------------------------------

    # Reparse using regex because + separates token/number
    #
    # Pattern:
    #
    # TOKEN + NUMBER
    #
    # Example:
    # B1041+1
    # B1042+2
    #
    # We capture the token and number together.

    pattern = re.compile(
        r'(?P<token>[A-Za-z]+\d+)\+(?P<number>\d+)'
    )

    matches = pattern.finditer(seat_string)

    for match in matches:

        seat_token = match.group("token")
        seat_number = match.group("number")

        # Ignore B0 / A0 / etc.
        if seat_token.endswith("0"):
            continue

        seats.append({
            "row_number": row_number,
            "row_name": row_name,
            "category_code": category_code,
            "seat_token": seat_token,
            "seat_code": seat_token,
            "seat_number": seat_number
        })

    return seats


# ============================================================
# PARSE COMPLETE RAW LAYOUT
# ============================================================

def parse_complete_layout(raw_layout):

    all_seats = []

    if not raw_layout:
        return all_seats

    # Rows are separated by |
    rows = raw_layout.split("|")

    for raw_row in rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        parsed = parse_layout_row(raw_row)

        all_seats.extend(parsed)

    return all_seats


# ============================================================
# BUILD SEAT MAP
# ============================================================

def build_seat_map(raw_layout):

    seats = parse_complete_layout(raw_layout)

    seat_map = {}

    for seat in seats:

        token = seat["seat_token"]

        seat_map[token] = seat

    return seat_map


# ============================================================
# STATUS PARSER
# ============================================================

def parse_status_token(status_token):
    """
    Converts status data such as:

        1:B1042

    or

        2:B1043

    into:

        position = 1
        seat_token = B1042

    IMPORTANT:

    The number before ':' is NOT the actual seat number.

    Actual seat number comes from the layout:

        B1042+2

    """

    if not status_token:
        return None

    status_token = status_token.strip()

    match = re.match(
        r'(?P<position>\d+):(?P<token>[A-Za-z]+\d+)$',
        status_token
    )

    if not match:
        return None

    return {
        "position": match.group("position"),
        "seat_token": match.group("token")
    }


# ============================================================
# STATUS CLASSIFICATION
# ============================================================

def classify_status(status):

    if not status:
        return None

    status = status.strip().upper()

    if status == "AVAILABLE":
        return "AVAILABLE"

    if status == "BOOKED":
        return "SOLD"

    # OTHER is deliberately ignored
    return None


# ============================================================
# PROCESS SEAT DATA
# ============================================================

def process_seats(
    raw_layout,
    status_records,
    timestamp,
    event_code,
    venue_code,
    session_id,
    date_value,
    city
):

    # --------------------------------------------------------
    # First create the authoritative physical seat map
    # from the layout.
    # --------------------------------------------------------

    seat_map = build_seat_map(raw_layout)

    results = []

    # --------------------------------------------------------
    # status_records expected format:
    #
    # [
    #   {
    #       "status_token": "1:B1042",
    #       "status": "AVAILABLE"
    #   },
    #   {
    #       "status_token": "2:B1043",
    #       "status": "BOOKED"
    #   }
    # ]
    # --------------------------------------------------------

    for record in status_records:

        status_token = record.get("status_token")
        status = record.get("status")

        parsed_status = parse_status_token(status_token)

        if not parsed_status:
            continue

        seat_token = parsed_status["seat_token"]

        # ----------------------------------------------------
        # Only accept seats that actually exist in layout.
        # ----------------------------------------------------

        if seat_token not in seat_map:
            continue

        seat = seat_map[seat_token]

        classification = classify_status(status)

        # Ignore OTHER and any unknown status
        if classification is None:
            continue

        available = 1 if classification == "AVAILABLE" else 0
        sold = 1 if classification == "SOLD" else 0

        results.append([
            timestamp,
            event_code,
            venue_code,
            session_id,
            date_value,
            city,

            seat["row_number"],
            seat["row_name"],
            seat["category_code"],
            seat["category_code"],

            seat["seat_token"],
            seat["seat_code"],

            # IMPORTANT:
            # Actual seat number comes from:
            #
            # B1042+2
            #
            # therefore = 2
            #
            seat["seat_number"],

            available,
            sold
        ])

    return results


# ============================================================
# DEDUPLICATE
# ============================================================

def deduplicate_rows(rows):

    unique = {}

    for row in rows:

        # Seat uniquely identified by event/session + seat token
        key = (
            row[1],   # Event
            row[2],   # Venue
            row[3],   # Session
            row[10]   # Seat token
        )

        unique[key] = row

    return list(unique.values())


# ============================================================
# WRITE TO GOOGLE SHEETS
# ============================================================

def write_to_sheet(worksheet, rows):

    if not rows:
        print("No rows to write.")
        return

    rows = deduplicate_rows(rows)

    # Clear existing data
    worksheet.clear()

    # Header
    worksheet.update(
        "A1",
        [HEADERS]
    )

    # Data
    worksheet.update(
        "A2",
        rows
    )

    print(f"Written {len(rows)} seat records.")


# ============================================================
# EXAMPLE BMS RESPONSE PROCESSOR
# ============================================================

def process_bms_response(
    raw_layout,
    bms_response,
    event_code,
    venue_code,
    session_id,
    date_value,
    city
):

    """
    bms_response should contain the status for each seat.

    Example:

    [
        {
            "status_token": "1:B1042",
            "status": "AVAILABLE"
        },
        {
            "status_token": "2:B1043",
            "status": "BOOKED"
        },
        {
            "status_token": "3:B1046",
            "status": "OTHER"
        }
    ]

    Result:

    B1042 -> seat number obtained from layout B1042+2
    B1043 -> seat number obtained from layout B1043+3
    B1046 -> ignored because OTHER
    """

    timestamp = datetime.datetime.now(
        datetime.timezone(
            datetime.timedelta(hours=5, minutes=30)
        )
    ).strftime("%Y-%m-%d %H:%M:%S")

    rows = process_seats(
        raw_layout=raw_layout,
        status_records=bms_response,
        timestamp=timestamp,
        event_code=event_code,
        venue_code=venue_code,
        session_id=session_id,
        date_value=date_value,
        city=city
    )

    return rows


# ============================================================
# TEST WITH YOUR BMS DATA
# ============================================================

if __name__ == "__main__":

    # --------------------------------------------------------
    # Example layout from your BMS response
    # --------------------------------------------------------

    RAW_LAYOUT = (
        "2:L:B000:"
        "B1041+1:"
        "B1042+2:"
        "B1043+3:"
        "B0+0:"
        "B0+0:"
        "B1046+4:"
        "B1047+5:"
        "B1048+6:"
        "B1049+7:"
        "B10410+8:"
        "B10411+9:"
        "B10412+10:"
        "B10413+11:"
        "B10414+12:"
        "B10415+13:"
        "B10416+14"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # In your actual BMS raw row, this is normally one
    # continuous string.
    #
    # Example:
    #
    # 2:L:B000:B1041+1:B1042+2:B1043+3:B0...
    #
    # If your actual data uses ':' differently, the parser
    # below should receive the original raw row exactly.
    # --------------------------------------------------------

    STATUS_RECORDS = [
        {
            "status_token": "1:B1042",
            "status": "AVAILABLE"
        },
        {
            "status_token": "2:B1043",
            "status": "BOOKED"
        },
        {
            "status_token": "4:B1046",
            "status": "OTHER"
        }
    ]

    print("Testing BMS seat parser...")

    rows = process_bms_response(
        raw_layout=RAW_LAYOUT,
        bms_response=STATUS_RECORDS,
        event_code=TARGET_EVENT_CODE,
        venue_code=TARGET_VENUE_CODE,
        session_id=TARGET_SESSION_ID,
        date_value=TARGET_DATE,
        city=CITY
    )

    for row in rows:
        print(row)

    print()
    print("Done.")
