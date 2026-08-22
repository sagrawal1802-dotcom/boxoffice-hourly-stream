import os
import json
import base64
import re
from datetime import datetime

import pytz
import gspread
from google.oauth2.service_account import Credentials
from curl_cffi import requests


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)

BMS_URL = "https://services-in.bookmyshow.com/doTrans.aspx"

CITY = "mumbai"
EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
SHOW_DATE = "20260826"

# ============================================================
# GOOGLE SHEET TABS
# ============================================================

RAW_TAB = "Toxic_BMS_Raw"
SEATS_TAB = "Toxic_BMS_Seats"
SUMMARY_TAB = "Toxic_BMS_Summary"


# ============================================================
# CATEGORY MAPPING
# ============================================================

CATEGORY_MAP = {
    "A": "RECLINER",
    "B": "PREMIUM",
    "C": "EXECUTIVE XL",
    "D": "EXECUTIVE",
    "E": "NORMAL"
}


# ============================================================
# GOOGLE SHEETS
# ============================================================

def init_google_sheet():

    if not GCP_SA_KEY:
        raise ValueError(
            "Missing GCP_SA_KEY_B64 or GCP_SA_KEY GitHub Secret."
        )

    raw_key = GCP_SA_KEY.strip()

    if raw_key.startswith("{"):
        service_account = json.loads(raw_key)
    else:
        service_account = json.loads(
            base64.b64decode(raw_key).decode("utf-8")
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials = Credentials.from_service_account_info(
        service_account,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    return spreadsheet


def get_or_create_sheet(spreadsheet, tab_name, headers):

    try:
        sheet = spreadsheet.worksheet(tab_name)

    except gspread.WorksheetNotFound:

        sheet = spreadsheet.add_worksheet(
            title=tab_name,
            rows="5000",
            cols=str(len(headers))
        )

    existing = sheet.get_all_values()

    if not existing:

        sheet.append_row(
            headers,
            value_input_option="USER_ENTERED"
        )

    return sheet


# ============================================================
# BMS REQUEST
# ============================================================

def fetch_bms_seat_layout():

    print("=" * 70)
    print("TOXIC BMS DIRECT SEAT TEST")
    print("=" * 70)

    print(f"Event: {EVENT_CODE}")
    print(f"Venue: {VENUE_CODE}")
    print(f"Session: {SESSION_ID}")
    print(f"Date: {SHOW_DATE}")
    print(f"City: {CITY}")

    print("=" * 70)
    print("BMS GETSEATLAYOUT")
    print("=" * 70)

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
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://in.bookmyshow.com",
        "Referer": "https://in.bookmyshow.com/"
    }

    print(f"URL: {BMS_URL}")
    print(f"PAYLOAD: {payload}")
    print("PROXY: DISABLED")

    try:

        response = requests.post(
            BMS_URL,
            data=payload,
            headers=headers,
            impersonate="chrome120",
            timeout=30
        )

    except Exception as e:

        print("=" * 70)
        print("REQUEST ERROR")
        print("=" * 70)
        print(repr(e))

        return None

    print("=" * 70)
    print("BMS RESPONSE")
    print("=" * 70)

    print(f"HTTP STATUS: {response.status_code}")
    print(f"RESPONSE SIZE: {len(response.text)}")

    if response.status_code != 200:

        print(response.text[:1000])

        return None

    try:

        data = response.json()

    except Exception as e:

        print("JSON parsing failed:")
        print(repr(e))
        print(response.text[:1000])

        return None

    print("=" * 70)
    print("JSON RESPONSE RECEIVED")
    print("=" * 70)

    bms = data.get("BookMyShow", {})

    success = str(
        bms.get("blnSuccess", "")
    ).lower() == "true"

    str_data = bms.get("strData", "")

    print(f"SUCCESS: {success}")
    print(f"strData length: {len(str_data)}")

    if not success:

        print("BMS returned unsuccessful response.")
        print(json.dumps(data, indent=2)[:3000])

        return None

    if not str_data:

        print("No strData returned.")

        return None

    return {
        "json": data,
        "str_data": str_data,
        "headers": dict(response.headers)
    }


# ============================================================
# CATEGORY PARSER
# ============================================================

def parse_categories(str_data):

    """
    First section of BMS strData:

    RECLINER:A:0000000005:5:N:0|
    PREMIUM:B:0000000002:4:N:0|
    EXECUTIVE XL:C:0000000006:3:N:0|
    EXECUTIVE:D:0000000003:2:N:0|
    NORMAL:E:0000000001:1:N:0

    """

    category_map = {}

    sections = str_data.split("||", 1)

    if not sections:
        return category_map

    category_section = sections[0]

    for item in category_section.split("|"):

        parts = item.split(":")

        if len(parts) < 2:
            continue

        category_name = parts[0].strip()
        category_code = parts[1].strip()

        if len(category_code) == 1:

            category_map[category_code] = category_name

    return category_map


# ============================================================
# ROW PARSER
# ============================================================

def parse_seat_rows(str_data):

    """
    BMS structure looks like:

    1:M:A000:A0+0:A1052+1:A1053+2:A0+0...

    Important:

    1       = row number
    M       = row name
    A000    = category/layout code
    A1052   = actual seat token
    """

    parts = str_data.split("||", 1)

    if len(parts) != 2:
        print("Could not separate category and seat sections.")
        return []

    seat_section = parts[1]

    rows = seat_section.split("|")

    parsed_rows = []

    for row_raw in rows:

        if not row_raw.strip():
            continue

        row_parts = row_raw.split(":")

        if len(row_parts) < 4:
            continue

        row_number = row_parts[0].strip()
        row_name = row_parts[1].strip()
        category_code = row_parts[2].strip()

        # Everything after the first 3 fields contains seats
        seat_data = ":".join(row_parts[3:])

        parsed_rows.append({
            "row_number": row_number,
            "row_name": row_name,
            "category_code": category_code,
            "seat_data": seat_data,
            "raw_row": row_raw
        })

    return parsed_rows


# ============================================================
# SEAT TOKEN PARSER
# ============================================================

def parse_seats_from_row(row):

    """
    Example:

    A0+0
    A1052+1
    A1053+2
    A0+0

    BMS uses:

    <seat token> + <position/status information>

    We preserve both fields.
    """

    row_number = row["row_number"]
    row_name = row["row_name"]
    category_code = row["category_code"]
    seat_data = row["seat_data"]

    category_letter = ""

    # Category can be A000, B000, etc.
    if category_code:
        category_letter = category_code[0]

    category_name = CATEGORY_MAP.get(
        category_letter,
        category_letter
    )

    seats = []

    # IMPORTANT:
    # Do NOT split on ':' because the BMS seat data
    # itself uses ':'.
    #
    # Each actual seat entry is separated by '+'
    #
    # Example:
    # A0+0:A1052+1:A1053+2
    #
    # However, because BMS may encode separators differently,
    # we first normalize the escaped representation.

    tokens = seat_data.split("+")

    for token in tokens:

        token = token.strip()

        if not token:
            continue

        # Find seat token.
        #
        # Examples:
        # A0
        # A1052
        # B1041
        # C1036
        # D1026
        # E1016

        match = re.search(
            r"([A-E])(\d+)",
            token
        )

        if not match:
            continue

        seat_category = match.group(1)
        seat_digits = match.group(2)

        # A0 / B0 etc. are spacer/non-seat entries.
        if seat_digits == "0":
            continue

        # Position/status number is normally before the colon.
        position_match = re.match(
            r"(\d+):",
            token
        )

        position = ""

        if position_match:
            position = position_match.group(1)

        # ----------------------------------------------------
        # Decode status
        #
        # Based on the BMS response structure we have seen,
        # 1 and 2 appear to represent seat states.
        #
        # We keep the raw status as well so it can be validated.
        # ----------------------------------------------------

        status_raw = position

        if status_raw == "1":
            status = "AVAILABLE"

        elif status_raw == "2":
            status = "BOOKED"

        elif status_raw == "0":
            status = "OTHER"

        else:
            status = "OTHER"

        seats.append({
            "row_number": row_number,
            "row_name": row_name,
            "category_code": seat_category,
            "category": CATEGORY_MAP.get(
                seat_category,
                seat_category
            ),
            "seat_code": match.group(0),
            "seat_number": seat_digits,
            "status_raw": status_raw,
            "status": status,
            "raw_token": token
        })

    return seats


# ============================================================
# PARSE COMPLETE SEAT MAP
# ============================================================

def parse_complete_seat_map(str_data):

    category_map = parse_categories(str_data)

    print("=" * 70)
    print("CATEGORY MAP")
    print("=" * 70)

    print(category_map)

    rows = parse_seat_rows(str_data)

    print("=" * 70)
    print(f"BMS ROWS FOUND: {len(rows)}")
    print("=" * 70)

    all_seats = []

    for row in rows:

        row_seats = parse_seats_from_row(row)

        all_seats.extend(row_seats)

    return all_seats, rows


# ============================================================
# SUMMARY
# ============================================================

def calculate_summary(seats):

    total = len(seats)

    available = sum(
        1 for seat in seats
        if seat["status"] == "AVAILABLE"
    )

    booked = sum(
        1 for seat in seats
        if seat["status"] == "BOOKED"
    )

    other = sum(
        1 for seat in seats
        if seat["status"] == "OTHER"
    )

    counted = available + booked

    if counted > 0:

        occupancy = (
            booked / counted
        ) * 100

    else:

        occupancy = 0

    return {
        "total": total,
        "available": available,
        "booked": booked,
        "other": other,
        "counted": counted,
        "occupancy": occupancy
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("STARTING TOXIC BMS TRACKER")
    print("=" * 70)

    result = fetch_bms_seat_layout()

    if not result:

        print("BMS request failed.")

        return

    str_data = result["str_data"]

    ist = pytz.timezone("Asia/Kolkata")

    now = datetime.now(ist)

    timestamp = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print("=" * 70)
    print("PARSING BMS SEAT MAP")
    print("=" * 70)

    seats, rows = parse_complete_seat_map(
        str_data
    )

    print(f"PARSED SEATS: {len(seats)}")

    summary = calculate_summary(seats)

    print("=" * 70)
    print("SEAT SUMMARY")
    print("=" * 70)

    print(f"TOTAL SEATS : {summary['total']}")
    print(f"AVAILABLE   : {summary['available']}")
    print(f"BOOKED      : {summary['booked']}")
    print(f"OTHER       : {summary['other']}")
    print(
        f"OCCUPANCY   : {summary['occupancy']:.2f}%"
    )

    # ========================================================
    # GOOGLE SHEETS
    # ========================================================

    print("=" * 70)
    print("CONNECTING TO GOOGLE SHEETS")
    print("=" * 70)

    spreadsheet = init_google_sheet()

    # --------------------------------------------------------
    # RAW TAB
    # --------------------------------------------------------

    raw_headers = [
        "Timestamp IST",
        "Event Code",
        "Venue Code",
        "Session ID",
        "Date",
        "City",
        "HTTP Status",
        "BMS Success",
        "strData Length",
        "Raw strData"
    ]

    raw_sheet = get_or_create_sheet(
        spreadsheet,
        RAW_TAB,
        raw_headers
    )

    raw_sheet.append_row(
        [
            timestamp,
            EVENT_CODE,
            VENUE_CODE,
            SESSION_ID,
            SHOW_DATE,
            CITY,
            200,
            True,
            len(str_data),
            str_data
        ],
        value_input_option="USER_ENTERED"
    )

    # --------------------------------------------------------
    # SEATS TAB
    # --------------------------------------------------------

    seat_headers = [
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
        "Seat Code",
        "Seat Number",
        "Status Raw",
        "Status",
        "Raw Token"
    ]

    seats_sheet = get_or_create_sheet(
        spreadsheet,
        SEATS_TAB,
        seat_headers
    )

    seat_rows_to_insert = []

    for seat in seats:

        seat_rows_to_insert.append(
            [
                timestamp,
                EVENT_CODE,
                VENUE_CODE,
                SESSION_ID,
                SHOW_DATE,
                CITY,
                seat["row_number"],
                seat["row_name"],
                seat["category_code"],
                seat["category"],
                seat["seat_code"],
                seat["seat_number"],
                seat["status_raw"],
                seat["status"],
                seat["raw_token"]
            ]
        )

    if seat_rows_to_insert:

        seats_sheet.append_rows(
            seat_rows_to_insert,
            value_input_option="USER_ENTERED"
        )

    # --------------------------------------------------------
    # SUMMARY TAB
    # --------------------------------------------------------

    summary_headers = [
        "Timestamp IST",
        "Event Code",
        "Venue Code",
        "Session ID",
        "Date",
        "City",
        "Total Seats",
        "Available",
        "Booked",
        "Other",
        "Counted Seats",
        "Occupancy %"
    ]

    summary_sheet = get_or_create_sheet(
        spreadsheet,
        SUMMARY_TAB,
        summary_headers
    )

    summary_sheet.append_row(
        [
            timestamp,
            EVENT_CODE,
            VENUE_CODE,
            SESSION_ID,
            SHOW_DATE,
            CITY,
            summary["total"],
            summary["available"],
            summary["booked"],
            summary["other"],
            summary["counted"],
            round(summary["occupancy"], 2)
        ],
        value_input_option="USER_ENTERED"
    )

    print("=" * 70)
    print("GOOGLE SHEETS UPDATED")
    print("=" * 70)

    print(
        f"Raw data added to: {RAW_TAB}"
    )

    print(
        f"Seat data added to: {SEATS_TAB}"
    )

    print(
        f"Summary added to: {SUMMARY_TAB}"
    )

    print("=" * 70)
    print("TRACKER FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()
