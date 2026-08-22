import os
import json
import base64
import re
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

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)

# No proxy for this test.
PROXY_URL = None


# ============================================================
# TOXIC TEST SESSION
# ============================================================

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
SHOW_DATE = "20260826"
CITY = "mumbai"


# ============================================================
# GOOGLE SHEET
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
    "BMS State",
    "Raw Row"
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

    if raw_key.startswith("{"):
        service_account_info = json.loads(raw_key)
    else:
        service_account_info = json.loads(
            base64.b64decode(raw_key).decode("utf-8")
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
        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=10000,
            cols=len(HEADERS)
        )

    # Add headers if sheet is empty
    existing = sheet.get_all_values()

    if not existing:
        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

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
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://in.bookmyshow.com",
        "Referer": (
            f"https://in.bookmyshow.com/"
            f"buytickets/toxic-{CITY}/movie-mumbai-"
            f"ET00379311-MT/"
        )
    }

    print("=" * 70)
    print("TOXIC BMS DIRECT SEAT TEST")
    print("=" * 70)
    print(f"Event:   {EVENT_CODE}")
    print(f"Venue:   {VENUE_CODE}")
    print(f"Session: {SESSION_ID}")
    print(f"Date:    {SHOW_DATE}")
    print(f"City:    {CITY}")
    print("=" * 70)
    print("BMS GETSEATLAYOUT")
    print("=" * 70)
    print("URL:")
    print(url)
    print()
    print("PAYLOAD:")
    print(payload)
    print()
    print("PROXY: DISABLED")
    print("=" * 70)

    try:

        response = requests.post(
            url,
            data=payload,
            headers=headers,
            impersonate="chrome120",
            timeout=30
        )

        print("HTTP STATUS:")
        print(response.status_code)

        print("RESPONSE SIZE:")
        print(len(response.content))

        print("=" * 70)
        print("RESPONSE HEADERS")
        print("=" * 70)

        for key, value in response.headers.items():
            print(f"{key}: {value}")

        if response.status_code != 200:
            print()
            print("BMS REQUEST FAILED")
            print(response.text[:2000])
            return None

        try:
            data = response.json()
        except Exception:
            print()
            print("Could not decode JSON.")
            print(response.text[:3000])
            return None

        print("=" * 70)
        print("JSON RESPONSE RECEIVED")
        print("=" * 70)

        bookmyshow = data.get("BookMyShow", {})

        success = bookmyshow.get("blnSuccess")

        print(f"blnSuccess: {success}")
        print(f"intException: {bookmyshow.get('intException')}")
        print(f"strException: {bookmyshow.get('strException')}")

        str_data = bookmyshow.get("strData")

        if not str_data:
            print()
            print("No strData field found.")
            return None

        print()
        print("strData length:")
        print(len(str_data))

        print()
        print("strData preview:")
        print(str_data[:2000])

        return str_data

    except Exception as error:

        print()
        print("REQUEST ERROR:")
        print(repr(error))

        return None


# ============================================================
# CATEGORY INFORMATION
# ============================================================

def parse_categories(category_section):

    """
    Example:

    RECLINER:A:0000000005:5:N:0|
    PREMIUM:B:0000000002:4:N:0|
    EXECUTIVE XL:C:0000000006:3:N:0|
    EXECUTIVE:D:0000000003:2:N:0|
    NORMAL:E:0000000001:1:N:0

    Returns:

    {
        "A": "RECLINER",
        "B": "PREMIUM",
        "C": "EXECUTIVE XL",
        "D": "EXECUTIVE",
        "E": "NORMAL"
    }
    """

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
# SEAT ROW PARSER
# ============================================================

def parse_seat_rows(str_data):

    """
    BMS strData structure:

    CATEGORY SECTION
    ||
    ROW DATA
    |
    ROW DATA
    |
    ROW DATA

    Example:

    1:M:A000:A0+0:A1052+1:A1053+2:A0+0...
    """

    timestamp = datetime.now(
        pytz.timezone("Asia/Kolkata")
    ).strftime("%Y-%m-%d %H:%M:%S")

    # --------------------------------------------------------
    # Split category section from seat section
    # --------------------------------------------------------

    sections = str_data.split("||", 1)

    if len(sections) != 2:
        print("Could not split category section from seat data.")
        return []

    category_section = sections[0]
    seat_section = sections[1]

    categories = parse_categories(category_section)

    print()
    print("CATEGORY MAP:")
    print(categories)

    # --------------------------------------------------------
    # Split rows
    # --------------------------------------------------------

    raw_rows = seat_section.split("|")

    results = []

    for raw_row in raw_rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        # ----------------------------------------------------
        # Row format:
        #
        # 1:M:A000:A0+0:A1052+1:A1053...
        #
        # ----------------------------------------------------

        row_parts = raw_row.split(":", 3)

        if len(row_parts) < 4:
            continue

        row_number = row_parts[0]
        row_name = row_parts[1]
        category_code = row_parts[2]
        seat_data = row_parts[3]

        category = categories.get(
            category_code,
            category_code
        )

        # ----------------------------------------------------
        # Split individual seats
        #
        # Example:
        #
        # A0+0
        # A1052+1
        # A1053+2
        #
        # ----------------------------------------------------

        seat_tokens = seat_data.split("+")

        for i in range(0, len(seat_tokens) - 1, 2):

            seat_code = seat_tokens[i].strip()
            state_text = seat_tokens[i + 1].strip()

            if not seat_code:
                continue

            # -----------------------------------------------
            # Ignore special row markers
            # -----------------------------------------------

            if seat_code == "A000":
                continue

            # -----------------------------------------------
            # State should be numeric
            # -----------------------------------------------

            try:
                bms_state = int(state_text)
            except ValueError:
                bms_state = state_text

            # -----------------------------------------------
            # Seat number
            #
            # A1052 -> 1052
            # B1043 -> 1043
            # D10216 -> 10216
            #
            # -----------------------------------------------

            seat_match = re.search(
                r"^[A-Za-z]+(.+)$",
                seat_code
            )

            if seat_match:
                seat_number = seat_match.group(1)
            else:
                seat_number = ""

            # -----------------------------------------------
            # Seat token
            # -----------------------------------------------

            seat_token = f"{state_text}:{seat_code}"

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
                seat_token,
                seat_code,
                seat_number,
                bms_state,
                raw_row
            ])

    return results


# ============================================================
# PRINT SAMPLE
# ============================================================

def print_sample(rows):

    print()
    print("=" * 70)
    print("PARSED SEAT SAMPLE")
    print("=" * 70)

    print(
        "Timestamp | Row | Category | Seat Token | "
        "Seat Code | Seat Number | BMS State"
    )

    print("-" * 70)

    for row in rows[:30]:

        print(
            f"{row[0]} | "
            f"{row[6]} | "
            f"{row[9]} | "
            f"{row[10]} | "
            f"{row[11]} | "
            f"{row[12]} | "
            f"{row[13]}"
        )

    print()
    print(f"TOTAL PARSED SEATS: {len(rows)}")


# ============================================================
# GOOGLE SHEET WRITE
# ============================================================

def write_to_sheet(sheet, rows):

    if not rows:
        print("No rows to write.")
        return

    print()
    print("=" * 70)
    print("UPDATING GOOGLE SHEET")
    print("=" * 70)

    sheet.append_rows(
        rows,
        value_input_option="USER_ENTERED"
    )

    print(
        f"Google Sheet updated successfully. "
        f"{len(rows)} seats written."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    str_data = get_seat_layout()

    if not str_data:
        print()
        print("=" * 70)
        print("TEST FAILED - NO SEAT DATA")
        print("=" * 70)
        return

    rows = parse_seat_rows(str_data)

    if not rows:

        print()
        print("=" * 70)
        print("NO SEATS PARSED")
        print("=" * 70)

        return

    print_sample(rows)

    sheet = init_google_sheet()

    write_to_sheet(
        sheet,
        rows
    )

    print()
    print("=" * 70)
    print("TEST FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()
