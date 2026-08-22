import os
import re
import json
import base64
import datetime
import time

import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

# Change this if your Google Sheet tab has another name
SHEET_NAME = "Sheet1"

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
SHOW_DATE = "20260826"
CITY = "mumbai"


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def connect_google_sheet():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    # --------------------------------------------------------
    # First try Base64 encoded service-account JSON
    # --------------------------------------------------------

    gcp_key_b64 = os.environ.get("GCP_SA_KEY_B64")

    if gcp_key_b64:

        print("Using GCP_SA_KEY_B64 for Google authentication...")

        try:

            decoded = base64.b64decode(
                gcp_key_b64
            ).decode("utf-8")

            service_account_info = json.loads(decoded)

        except Exception as e:

            raise RuntimeError(
                f"Could not decode GCP_SA_KEY_B64: {e}"
            )

    # --------------------------------------------------------
    # Otherwise use raw JSON
    # --------------------------------------------------------

    else:

        gcp_key = os.environ.get("GCP_SA_KEY")

        if not gcp_key:

            raise RuntimeError(
                "Neither GCP_SA_KEY_B64 nor GCP_SA_KEY "
                "was found in GitHub Secrets."
            )

        print("Using GCP_SA_KEY for Google authentication...")

        try:

            service_account_info = json.loads(gcp_key)

        except Exception as e:

            raise RuntimeError(
                f"Could not parse GCP_SA_KEY as JSON: {e}"
            )

    # --------------------------------------------------------
    # Create credentials
    # --------------------------------------------------------

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    worksheet = spreadsheet.worksheet(
        SHEET_NAME
    )

    print("Google Sheets connection successful.")

    return worksheet


# ============================================================
# TIMESTAMP IST
# ============================================================

def get_timestamp_ist():

    ist = datetime.timezone(
        datetime.timedelta(hours=5, minutes=30)
    )

    now = datetime.datetime.now(ist)

    return now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# BMS SEAT TOKEN PARSER
# ============================================================

def parse_seat_token(token):

    """
    BMS examples:

        5:B1048+6
        6:B2049+7

    Interpretation:

        5       = BMS position
        B1048   = seat code
        +6      = actual seat number

    B1xxx = AVAILABLE
    B2xxx = SOLD

    Example:

        B1048+6

        Seat Code   = B1048
        Seat Number = 6
        Available   = 1
        Sold        = 0

    Example:

        B2049+7

        Seat Code   = B2049
        Seat Number = 7
        Available   = 0
        Sold        = 1
    """

    token = token.strip()

    if not token:
        return None

    # --------------------------------------------------------
    # Token format:
    #
    # position:seatcode+seatnumber
    #
    # Example:
    #
    # 5:B1048+6
    # --------------------------------------------------------

    match = re.match(
        r"^(\d+):([A-E])([12])(\d+)\+(\d+)$",
        token
    )

    if not match:

        return None

    position = int(match.group(1))

    row_letter = match.group(2)

    status_digit = match.group(3)

    seat_id = match.group(4)

    seat_number = int(
        match.group(5)
    )

    seat_code = (
        row_letter +
        status_digit +
        seat_id
    )

    # --------------------------------------------------------
    # Status
    #
    # 1 = AVAILABLE
    # 2 = SOLD
    # --------------------------------------------------------

    if status_digit == "1":

        available = 1
        sold = 0

    else:

        available = 0
        sold = 1

    return {
        "position": position,
        "seat_code": seat_code,
        "seat_number": seat_number,
        "available": available,
        "sold": sold
    }


# ============================================================
# PARSE BMS ROW
# ============================================================

def parse_bms_row(raw_row):

    """
    Example:

    2:L:B000:B1041+0+B1042+1+B1043+2
    """

    raw_row = raw_row.strip()

    if not raw_row:

        return []

    # --------------------------------------------------------
    # Row header
    #
    # 2:L:B000:
    #
    # Row Number  = 2
    # Row Name    = L
    # Category    = B000
    # --------------------------------------------------------

    match = re.match(
        r"^(\d+):([^:]+):([^:]+):(.*)$",
        raw_row
    )

    if not match:

        print(
            "Could not parse row header:",
            raw_row[:200]
        )

        return []

    row_number = int(
        match.group(1)
    )

    row_name = match.group(2)

    category_code = match.group(3)

    seat_data = match.group(4)

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Seats are separated by "+"
    #
    # BUT actual seat number also comes after "+"
    #
    # Therefore we cannot simply split on every "+".
    #
    # We use the pattern:
    #
    # position:seatcode+seatnumber
    #
    # and locate each complete token.
    # --------------------------------------------------------

    pattern = re.compile(
        r"(\d+):([A-E][12]\d+)\+(\d+)"
    )

    seats = []

    for m in pattern.finditer(seat_data):

        position = int(
            m.group(1)
        )

        seat_code = m.group(2)

        seat_number = int(
            m.group(3)
        )

        # ----------------------------------------------------
        # Status is determined from seat code:
        #
        # B1xxx = available
        # B2xxx = sold
        #
        # Same principle for A/C/D/E.
        # ----------------------------------------------------

        if len(seat_code) >= 2:

            status_digit = seat_code[1]

        else:

            continue

        if status_digit == "1":

            available = 1
            sold = 0

        elif status_digit == "2":

            available = 0
            sold = 1

        else:

            continue

        seats.append({
            "position": position,
            "seat_code": seat_code,
            "seat_number": seat_number,
            "available": available,
            "sold": sold,
            "raw_token": m.group(0)
        })

    return {
        "row_number": row_number,
        "row_name": row_name,
        "category_code": category_code,
        "seats": seats,
        "raw_row": raw_row
    }


# ============================================================
# PARSE COMPLETE BMS LAYOUT
# ============================================================

def parse_full_layout(layout):

    """
    Complete BMS layout example:

    1:M:A000:...
    |
    2:L:B000:...
    |
    3:K:B000:...
    |
    4:J:B000:...

    Returns all actual seats.
    """

    if not layout:

        return []

    # --------------------------------------------------------
    # Remove escaped pipe representation if necessary
    # --------------------------------------------------------

    layout = layout.replace(
        r"\|",
        "|"
    )

    raw_rows = layout.split("|")

    all_seats = []

    for raw_row in raw_rows:

        raw_row = raw_row.strip()

        if not raw_row:

            continue

        parsed_row = parse_bms_row(
            raw_row
        )

        if not parsed_row:

            continue

        for seat in parsed_row["seats"]:

            all_seats.append({
                "row_number":
                    parsed_row["row_number"],

                "row_name":
                    parsed_row["row_name"],

                "category_code":
                    parsed_row["category_code"],

                "seat_code":
                    seat["seat_code"],

                "seat_number":
                    seat["seat_number"],

                "available":
                    seat["available"],

                "sold":
                    seat["sold"],

                "raw_token":
                    seat["raw_token"],

                "raw_row":
                    parsed_row["raw_row"]
            })

    return all_seats


# ============================================================
# CATEGORY NAME
# ============================================================

def get_category_name(category_code):

    categories = {

        "A000": "RECLINER",

        "B000": "PREMIUM",

        "C000": "EXECUTIVE XL",

        "D000": "EXECUTIVE",

        "E000": "NORMAL"
    }

    return categories.get(
        category_code,
        category_code
    )


# ============================================================
# GOOGLE SHEETS HEADERS
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

    "Sold",

    "Raw Row"
]


# ============================================================
# BUILD GOOGLE SHEETS RECORD
# ============================================================

def build_record(seat):

    timestamp = get_timestamp_ist()

    category = get_category_name(
        seat["category_code"]
    )

    return [

        timestamp,

        EVENT_CODE,

        VENUE_CODE,

        SESSION_ID,

        SHOW_DATE,

        CITY,

        seat["row_number"],

        seat["row_name"],

        seat["category_code"],

        category,

        seat["raw_token"],

        seat["seat_code"],

        seat["seat_number"],

        seat["available"],

        seat["sold"],

        seat["raw_row"]
    ]


# ============================================================
# WRITE DATA TO GOOGLE SHEETS
# ============================================================

def write_to_sheet(
    worksheet,
    records
):

    if not records:

        print(
            "No seats found."
        )

        return

    # --------------------------------------------------------
    # Clear existing data
    # --------------------------------------------------------

    worksheet.clear()

    # --------------------------------------------------------
    # Header + records
    # --------------------------------------------------------

    values = [
        HEADERS
    ]

    values.extend(
        records
    )

    worksheet.update(
        "A1",
        values,
        value_input_option="RAW"
    )

    print(
        f"Successfully wrote "
        f"{len(records)} seats to Google Sheets."
    )


# ============================================================
# TEST BMS PARSER
# ============================================================

def test_parser():

    print(
        "\n========================================"
    )

    print(
        "TESTING BMS SEAT PARSER"
    )

    print(
        "========================================\n"
    )

    test_tokens = [

        "5:B1048+6",

        "6:B2049+7",

        "10:C1036+1",

        "11:C2037+2",

        "5:A10510+5",

        "6:A20510+6"
    ]

    for token in test_tokens:

        # The token parser expects the exact BMS format
        result = parse_seat_token(
            token
        )

        print(
            f"{token} -> {result}"
        )

    print(
        "\n========================================\n"
    )


# ============================================================
# TEST COMPLETE ROW
# ============================================================

def test_row_parser():

    print(
        "Testing complete BMS row..."
    )

    test_row = (
        "2:L:B000:"
        "0:B1041+0"
        "+1:B1042+1"
        "+2:B1043+2"
        "+3:B0+0"
        "+4:B1047+4"
        "+5:B1048+5"
        "+6:B2049+6"
        "+7:B20410+7"
    )

    result = parse_bms_row(
        test_row
    )

    print(
        f"Row number: "
        f"{result['row_number']}"
    )

    print(
        f"Row name: "
        f"{result['row_name']}"
    )

    print(
        f"Category: "
        f"{result['category_code']}"
    )

    print(
        f"Seats detected: "
        f"{len(result['seats'])}"
    )

    for seat in result["seats"]:

        print(
            f"  "
            f"{seat['seat_code']} "
            f"| Seat No: {seat['seat_number']} "
            f"| Available: {seat['available']} "
            f"| Sold: {seat['sold']}"
        )

    print()


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "Starting BMS Seat Tracker..."
    )

    print(
        get_timestamp_ist()
    )

    # --------------------------------------------------------
    # Test parser
    # --------------------------------------------------------

    test_parser()

    test_row_parser()

    # --------------------------------------------------------
    # Connect Google Sheets
    # --------------------------------------------------------

    print(
        "Connecting to Google Sheets..."
    )

    worksheet = connect_google_sheet()

    # --------------------------------------------------------
    # IMPORTANT
    #
    # Replace this variable with the actual BMS layout
    # returned by your scraper/API.
    #
    # The example below is ONLY for testing.
    # --------------------------------------------------------

    example_layout = (
        "1:M:A000:"
        "0:A0+0"
        "+1:A1052+1"
        "+2:A1053+2"
        "+3:A1057+3"
        "+5:A10510+5"
        "+7:A10513+7"
        "+9:A20516+9"
        "|"
        "2:L:B000:"
        "0:B1041+0"
        "+1:B1042+1"
        "+2:B1043+2"
        "+5:B1048+5"
        "+6:B2049+6"
        "+7:B10410+7"
        "|"
        "3:K:B000:"
        "0:B1041+0"
        "+1:B1042+1"
        "+2:B2043+2"
    )

    # --------------------------------------------------------
    # Parse layout
    # --------------------------------------------------------

    seats = parse_full_layout(
        example_layout
    )

    print(
        f"Seats parsed: {len(seats)}"
    )

    # --------------------------------------------------------
    # Print sample
    # --------------------------------------------------------

    for seat in seats[:20]:

        print(
            seat["seat_code"],
            "| Seat:",
            seat["seat_number"],
            "| Available:",
            seat["available"],
            "| Sold:",
            seat["sold"]
        )

    # --------------------------------------------------------
    # Convert records
    # --------------------------------------------------------

    records = []

    for seat in seats:

        records.append(
            build_record(seat)
        )

    # --------------------------------------------------------
    # Write to Google Sheets
    # --------------------------------------------------------

    write_to_sheet(
        worksheet,
        records
    )

    print(
        "\nBMS Seat Tracker completed."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
