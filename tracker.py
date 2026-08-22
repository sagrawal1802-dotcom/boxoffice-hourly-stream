import os
import json
import base64
import re
import time
from datetime import datetime

import pytz
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

SHEET_TAB_NAME = "SeatLog"

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
SHOW_DATE = "20260826"
CITY = "mumbai"

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)


# ============================================================
# GOOGLE SHEET HEADERS
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
    "BMS State"
]


# ============================================================
# GOOGLE AUTHENTICATION
# ============================================================

def init_google_sheet():

    if not GCP_SA_KEY:
        raise ValueError(
            "Missing GCP_SA_KEY_B64 or GCP_SA_KEY GitHub Secret."
        )

    raw_key = GCP_SA_KEY.strip()

    try:

        # Secret can either be:
        # 1. Normal JSON service-account credentials
        # 2. Base64 encoded JSON

        if raw_key.startswith("{"):
            service_account_info = json.loads(raw_key)

        else:
            decoded = base64.b64decode(raw_key).decode("utf-8")
            service_account_info = json.loads(decoded)

    except Exception as error:

        raise ValueError(
            f"Could not decode Google service account secret: {error}"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:

        sheet = spreadsheet.worksheet(SHEET_TAB_NAME)

    except gspread.WorksheetNotFound:

        print(f"Worksheet '{SHEET_TAB_NAME}' not found.")
        print("Creating worksheet...")

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=10000,
            cols=len(HEADERS)
        )

    # Check headers
    existing = sheet.get_all_values()

    if not existing:

        print("Sheet is empty. Adding headers...")

        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

    else:

        current_headers = existing[0]

        if current_headers[:len(HEADERS)] != HEADERS:

            print("WARNING: Existing headers do not exactly match.")

    return sheet


# ============================================================
# BMS REQUEST
# ============================================================

def get_seat_layout():

    url = "https://services-in.bookmyshow.com/doTrans.aspx"

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": VENUE_CODE,
        "strParam1": SESSION_ID,
        "strParam2": "WEB",
        "strParam5": "Y",
        "strParam6": "Y",
        "strParam7": "N",
        "strFormat": "json"
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": (
            "application/x-www-form-urlencoded; charset=UTF-8"
        ),
        "Origin": "https://in.bookmyshow.com",
        "Referer": (
            f"https://in.bookmyshow.com/"
            f"buytickets/toxic-{CITY}/movie-mumbai-"
            f"{EVENT_CODE}-MT/"
        )
    }

    print("=" * 70)
    print("BMS SEAT TRACKER")
    print("=" * 70)

    print(f"Event:   {EVENT_CODE}")
    print(f"Venue:   {VENUE_CODE}")
    print(f"Session: {SESSION_ID}")
    print(f"Date:    {SHOW_DATE}")
    print(f"City:    {CITY}")

    print("=" * 70)
    print("Requesting BMS seat layout...")
    print("=" * 70)

    for attempt in range(1, 4):

        try:

            print(f"Attempt {attempt}/3")

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                impersonate="chrome120",
                timeout=30
            )

            print(f"HTTP status: {response.status_code}")
            print(f"Response size: {len(response.content)} bytes")

            if response.status_code != 200:

                print("BMS request failed.")
                print(response.text[:2000])

                if attempt < 3:
                    time.sleep(3)
                    continue

                return None

            try:

                data = response.json()

            except Exception:

                print("Could not decode BMS JSON.")
                print(response.text[:3000])
                return None

            bookmyshow = data.get("BookMyShow", {})

            success = bookmyshow.get("blnSuccess")

            print(f"blnSuccess: {success}")
            print(
                f"intException: "
                f"{bookmyshow.get('intException')}"
            )
            print(
                f"strException: "
                f"{bookmyshow.get('strException')}"
            )

            str_data = bookmyshow.get("strData")

            if not str_data:

                print("No strData returned by BMS.")
                return None

            print(f"strData length: {len(str_data)}")

            return str_data

        except Exception as error:

            print(f"Request error: {repr(error)}")

            if attempt < 3:
                time.sleep(3)

    return None


# ============================================================
# CATEGORY PARSER
# ============================================================

def parse_categories(category_section):

    categories = {}

    parts = category_section.split("|")

    for part in parts:

        part = part.strip()

        if not part:
            continue

        pieces = part.split(":")

        if len(pieces) < 2:
            continue

        category_name = pieces[0].strip()
        category_code = pieces[1].strip()

        if category_code:
            categories[category_code] = category_name

    return categories


# ============================================================
# SEAT TOKEN PARSER
# ============================================================

def parse_seat_token(token):

    """
    Correct BMS interpretation.

    Examples:

        A1052+1
        A1053+2
        B1048+6
        B2049+7
        D10216+10
        A0+0
        B0+0

    Meaning:

        A1052+1
        ^^^^^  ^ 
        code   actual seat number

    The second digit of the seat code determines status:

        10 = AVAILABLE
        20 = SOLD

    Therefore:

        B1048+6 -> AVAILABLE, seat number 6
        B2049+7 -> SOLD, seat number 7

    """

    token = token.strip()

    if not token:
        return None

    # Remove whitespace
    token = token.replace(" ", "")

    # Match:
    # A1052+1
    # B1048+6
    # D10216+10
    #
    # First character = category/seat row letter
    # Remaining numeric code
    # + actual seat number

    match = re.match(
        r"^([A-Za-z])(\d+)\+(\d+)$",
        token
    )

    if not match:
        return None

    letter = match.group(1).upper()
    numeric_code = match.group(2)
    actual_seat_number = match.group(3)

    seat_code = f"{letter}{numeric_code}"

    # --------------------------------------------------------
    # A0 / B0 etc. = no physical seat
    # --------------------------------------------------------

    if numeric_code == "0":
        return None

    # --------------------------------------------------------
    # Determine status
    #
    # A1052
    #  ^
    #  first numeric digit after letter = 1
    #
    # A2052
    #  ^
    #  first numeric digit after letter = 2
    # --------------------------------------------------------

    if numeric_code.startswith("1"):

        bms_state = "AVAILABLE"

    elif numeric_code.startswith("2"):

        bms_state = "SOLD"

    else:

        # Unknown/non-seat encoding
        return None

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": actual_seat_number,
        "bms_state": bms_state
    }


# ============================================================
# SEAT ROW PARSER
# ============================================================

def parse_seat_rows(str_data):

    """
    Parses BMS strData.

    Example:

    1:M:A000:A0+0:A1052+1:A1053+2:A0+0...

    Row:

        1:M

    means:

        Row Number = 1
        Row Name   = M

    Seat:

        A1052+1

    means:

        Seat Code   = A1052
        Seat Number = 1
        Status      = AVAILABLE

    Seat:

        A20515+9

    means:

        Seat Code   = A20515
        Seat Number = 9
        Status      = SOLD
    """

    timestamp = datetime.now(
        pytz.timezone("Asia/Kolkata")
    ).strftime("%Y-%m-%d %H:%M:%S")

    # --------------------------------------------------------
    # Split category section and seat section
    # --------------------------------------------------------

    sections = str_data.split("||", 1)

    if len(sections) != 2:

        print("ERROR: Could not split category section.")
        return []

    category_section = sections[0]
    seat_section = sections[1]

    categories = parse_categories(category_section)

    print()
    print("CATEGORY MAP")
    print("=" * 70)

    for code, name in categories.items():

        print(f"{code} -> {name}")

    print("=" * 70)

    # --------------------------------------------------------
    # Split individual rows
    # --------------------------------------------------------

    raw_rows = seat_section.split("|")

    results = []

    available_count = 0
    sold_count = 0

    # --------------------------------------------------------
    # Process each row
    # --------------------------------------------------------

    for raw_row in raw_rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        # Expected:
        #
        # 1:M:A000:A0+0:A1052+1:A1053+2...

        row_parts = raw_row.split(":", 3)

        if len(row_parts) < 4:
            continue

        row_number = row_parts[0].strip()
        row_name = row_parts[1].strip()
        category_code = row_parts[2].strip()
        seat_data = row_parts[3].strip()

        category = categories.get(
            category_code,
            category_code
        )

        # ----------------------------------------------------
        # IMPORTANT
        #
        # Seats are separated by :
        #
        # A0+0:A1052+1:A1053+2
        #
        # Each seat itself uses + to separate:
        #
        # SeatCode + ActualSeatNumber
        # ----------------------------------------------------

        seat_tokens = seat_data.split(":")

        for token in seat_tokens:

            token = token.strip()

            if not token:
                continue

            parsed = parse_seat_token(token)

            if parsed is None:
                continue

            seat_code = parsed["seat_code"]
            seat_number = parsed["seat_number"]
            bms_state = parsed["bms_state"]

            if bms_state == "AVAILABLE":
                available_count += 1

            elif bms_state == "SOLD":
                sold_count += 1

            results.append([
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
                parsed["seat_token"],
                seat_code,
                seat_number,
                bms_state
            ])

    print()
    print("=" * 70)
    print("SEAT SUMMARY")
    print("=" * 70)

    print(f"AVAILABLE : {available_count}")
    print(f"SOLD      : {sold_count}")
    print(f"TOTAL     : {available_count + sold_count}")

    print("=" * 70)

    return results


# ============================================================
# PRINT SAMPLE
# ============================================================

def print_sample(rows):

    print()
    print("=" * 100)
    print("PARSED SEAT SAMPLE")
    print("=" * 100)

    print(
        "Row | Row Name | Category | "
        "Seat Token | Seat Code | Seat Number | Status"
    )

    print("-" * 100)

    for row in rows[:50]:

        print(
            f"{row[6]} | "
            f"{row[7]} | "
            f"{row[9]} | "
            f"{row[10]} | "
            f"{row[11]} | "
            f"{row[12]} | "
            f"{row[13]}"
        )

    print("-" * 100)
    print(f"TOTAL PARSED SEATS: {len(rows)}")


# ============================================================
# GOOGLE SHEET WRITE
# ============================================================

def write_to_sheet(sheet, rows):

    if not rows:

        print("No seats to write.")
        return

    print()
    print("=" * 70)
    print("WRITING TO GOOGLE SHEET")
    print("=" * 70)

    # Write in batches to reduce API calls
    batch_size = 500

    total = len(rows)

    for start in range(0, total, batch_size):

        batch = rows[start:start + batch_size]

        sheet.append_rows(
            batch,
            value_input_option="USER_ENTERED"
        )

        print(
            f"Written {min(start + batch_size, total)}"
            f"/{total} rows"
        )

    print()
    print(
        f"Google Sheet updated successfully. "
        f"{total} seats written."
    )


# ============================================================
# TEST PARSER
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
        "B0+0"
    ]

    for test in tests:

        result = parse_seat_token(test)

        print(
            f"{test:<15} -> {result}"
        )

    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("Starting BMS Seat Tracker...")
    print("=" * 70)

    print(
        datetime.now(
            pytz.timezone("Asia/Kolkata")
        ).strftime("%Y-%m-%d %H:%M:%S")
    )

    # --------------------------------------------------------
    # Test parser
    # --------------------------------------------------------

    test_parser()

    # --------------------------------------------------------
    # Get BMS layout
    # --------------------------------------------------------

    str_data = get_seat_layout()

    if not str_data:

        print()
        print("=" * 70)
        print("FAILED: No BMS seat data received.")
        print("=" * 70)

        return

    # --------------------------------------------------------
    # Parse
    # --------------------------------------------------------

    rows = parse_seat_rows(str_data)

    if not rows:

        print()
        print("=" * 70)
        print("FAILED: No seats parsed.")
        print("=" * 70)

        return

    # --------------------------------------------------------
    # Print sample
    # --------------------------------------------------------

    print_sample(rows)

    # --------------------------------------------------------
    # Connect Google Sheet
    # --------------------------------------------------------

    print()
    print("Connecting to Google Sheets...")

    try:

        sheet = init_google_sheet()

    except Exception as error:

        print()
        print("=" * 70)
        print("ERROR CONNECTING TO GOOGLE SHEETS")
        print("=" * 70)

        print(repr(error))

        return

    # --------------------------------------------------------
    # Write
    # --------------------------------------------------------

    write_to_sheet(
        sheet,
        rows
    )

    print()
    print("=" * 70)
    print("BMS TRACKING RUN COMPLETED")
    print("=" * 70)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
