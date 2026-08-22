import os
import json
import base64
from datetime import datetime

import pytz
import gspread
from curl_cffi import requests
from google.oauth2.service_account import Credentials


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

RAW_SHEET_NAME = "Toxic_BMS_Raw"
SEAT_SHEET_NAME = "Toxic_BMS_Seats"


# ============================================================
# TEST SHOW
# ============================================================

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
DATE_CODE = "20260826"
CITY = "mumbai"


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def get_spreadsheet():

    if not GCP_SA_KEY:
        raise ValueError(
            "GCP_SA_KEY_B64 or GCP_SA_KEY is missing."
        )

    raw = GCP_SA_KEY.strip()

    if raw.startswith("{"):
        service_account = json.loads(raw)
    else:
        service_account = json.loads(
            base64.b64decode(raw).decode("utf-8")
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

    return client.open_by_key(SPREADSHEET_ID)


def get_or_create_sheet(
    spreadsheet,
    name,
    headers,
    rows=10000,
    cols=20
):

    try:

        sheet = spreadsheet.worksheet(name)

    except gspread.WorksheetNotFound:

        sheet = spreadsheet.add_worksheet(
            title=name,
            rows=rows,
            cols=cols
        )

        sheet.append_row(
            headers,
            value_input_option="USER_ENTERED"
        )

    return sheet


# ============================================================
# BMS REQUEST
# ============================================================

def get_seat_layout():

    url = (
        "https://services-in.bookmyshow.com/"
        "doTrans.aspx"
    )

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
            "Chrome/151.0.0.0 "
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
            "https://in.bookmyshow.com/"
        ),

        "Accept-Language": (
            "en-IN,en;q=0.9"
        )
    }

    print()
    print("=" * 70)
    print("BMS GETSEATLAYOUT")
    print("=" * 70)

    print("Event:", EVENT_CODE)
    print("Venue:", VENUE_CODE)
    print("Session:", SESSION_ID)
    print("Date:", DATE_CODE)

    print()
    print("PROXY: DISABLED")

    try:

        response = requests.post(
            url,
            data=payload,
            headers=headers,
            impersonate="chrome120",
            timeout=30
        )

    except Exception as e:

        print()
        print("REQUEST ERROR:")
        print(repr(e))

        return None

    print()
    print("HTTP STATUS:")
    print(response.status_code)

    print()
    print("RESPONSE SIZE:")
    print(len(response.text))

    print()
    print("SEATLAYOUT ENCRYPTION:")
    print(
        response.headers.get(
            "x-seatlayout-encryption"
        )
    )

    return response


# ============================================================
# EXTRACT BMS STRDATA
# ============================================================

def extract_strdata(response):

    if response is None:
        return None

    try:

        data = response.json()

    except Exception as e:

        print("JSON ERROR:")
        print(repr(e))

        return None

    print()
    print("=" * 70)
    print("BMS JSON STRUCTURE")
    print("=" * 70)

    print(
        "Top-level keys:",
        list(data.keys())
    )

    bms = data.get(
        "BookMyShow",
        {}
    )

    print(
        "BookMyShow keys:",
        list(bms.keys())
    )

    success = str(
        bms.get(
            "blnSuccess",
            ""
        )
    ).lower()

    print()
    print(
        "BMS success:",
        success
    )

    if success != "true":

        print()
        print(
            "BMS exception:",
            bms.get(
                "strException",
                ""
            )
        )

        return None

    strdata = bms.get(
        "strData"
    )

    if not strdata:

        print(
            "strData is empty."
        )

        return None

    print()
    print("=" * 70)
    print("STRDATA FOUND")
    print("=" * 70)

    print(
        "Length:",
        len(strdata)
    )

    print()
    print(
        "Preview:"
    )

    print(
        strdata[:2000]
    )

    return strdata


# ============================================================
# PARSE CATEGORY HEADER
# ============================================================

def parse_categories(strdata):

    categories = {}

    parts = strdata.split("||")

    if not parts:
        return categories

    category_block = parts[0]

    for item in category_block.split("|"):

        if not item:
            continue

        fields = item.split(":")

        if len(fields) < 2:
            continue

        category_name = fields[0]
        category_code = fields[1]

        categories[category_code] = {
            "category": category_name,
            "code": category_code,
            "raw": item
        }

    print()
    print("=" * 70)
    print("SEAT CATEGORIES")
    print("=" * 70)

    for code, value in categories.items():

        print(
            code,
            "=>",
            value["category"]
        )

    return categories


# ============================================================
# PARSE SEAT ROWS
# ============================================================

def parse_seat_rows(
    strdata,
    categories
):

    all_seats = []

    parts = strdata.split("||")

    if len(parts) < 2:

        print(
            "No seat-layout block found."
        )

        return all_seats

    seat_block = parts[1]

    rows = seat_block.split("|")

    print()
    print("=" * 70)
    print("PARSING SEAT ROWS")
    print("=" * 70)

    print(
        "Rows detected:",
        len(rows)
    )

    for row_string in rows:

        if not row_string:
            continue

        fields = row_string.split(":")

        if len(fields) < 4:
            continue

        row_number = fields[0]
        row_name = fields[1]
        category_code = fields[2]
        seat_data = ":".join(
            fields[3:]
        )

        category_name = categories.get(
            category_code,
            {}
        ).get(
            "category",
            category_code
        )

        # ----------------------------------------------------
        # Seat entries are separated by +
        # ----------------------------------------------------

        seat_entries = seat_data.split("+")

        for entry in seat_entries:

            if not entry:
                continue

            # Expected pattern examples:
            #
            # A1052+1
            # A0+0
            # B1041+1
            #
            # We keep the original token rather than
            # making assumptions about BMS status encoding.
            #
            # This is important because we will map the
            # status separately after validating the layout.

            seat_code = entry

            seat_number = ""

            if "+" in entry:

                pieces = entry.split("+")

                seat_code = pieces[0]

                if len(pieces) > 1:
                    seat_number = pieces[1]

            all_seats.append({

                "row_number": row_number,

                "row_name": row_name,

                "category_code": category_code,

                "category_name": category_name,

                "seat_token": entry,

                "seat_code": seat_code,

                "seat_number": seat_number,

                "raw_row": row_string

            })

    return all_seats


# ============================================================
# PRINT PARSED DATA
# ============================================================

def print_seat_summary(seats):

    print()
    print("=" * 70)
    print("PARSED SEAT SUMMARY")
    print("=" * 70)

    print(
        "Total parsed seat tokens:",
        len(seats)
    )

    if not seats:
        print(
            "NO SEATS PARSED"
        )
        return

    print()
    print(
        "First 30 parsed seats:"
    )

    for seat in seats[:30]:

        print(
            seat["row_name"],
            "|",
            seat["category_name"],
            "|",
            seat["seat_token"]
        )


# ============================================================
# SAVE RAW RESPONSE
# ============================================================

def save_raw_response(
    spreadsheet,
    response,
    strdata
):

    headers = [
        "Timestamp IST",
        "Event Code",
        "Venue Code",
        "Session ID",
        "Date",
        "City",
        "HTTP Status",
        "BMS Success",
        "Encryption",
        "strData Length",
        "strData"
    ]

    sheet = get_or_create_sheet(
        spreadsheet,
        RAW_SHEET_NAME,
        headers,
        rows=5000,
        cols=len(headers)
    )

    ist = pytz.timezone(
        "Asia/Kolkata"
    )

    now = datetime.now(
        ist
    )

    try:

        data = response.json()

        bms = data.get(
            "BookMyShow",
            {}
        )

        success = bms.get(
            "blnSuccess",
            ""
        )

    except Exception:

        success = ""

    row = [

        now.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        EVENT_CODE,

        VENUE_CODE,

        SESSION_ID,

        DATE_CODE,

        CITY,

        response.status_code,

        success,

        response.headers.get(
            "x-seatlayout-encryption",
            ""
        ),

        len(strdata),

        strdata

    ]

    sheet.append_row(
        row,
        value_input_option="USER_ENTERED"
    )


# ============================================================
# SAVE PARSED SEATS
# ============================================================

def save_seats(
    spreadsheet,
    seats
):

    headers = [
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
        "Raw Row"
    ]

    sheet = get_or_create_sheet(
        spreadsheet,
        SEAT_SHEET_NAME,
        headers,
        rows=50000,
        cols=len(headers)
    )

    ist = pytz.timezone(
        "Asia/Kolkata"
    )

    now = datetime.now(
        ist
    )

    timestamp = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    rows = []

    for seat in seats:

        rows.append([

            timestamp,

            EVENT_CODE,

            VENUE_CODE,

            SESSION_ID,

            DATE_CODE,

            CITY,

            seat["row_number"],

            seat["row_name"],

            seat["category_code"],

            seat["category_name"],

            seat["seat_token"],

            seat["seat_code"],

            seat["seat_number"],

            seat["raw_row"]

        ])

    if rows:

        sheet.append_rows(
            rows,
            value_input_option="USER_ENTERED"
        )

    print()
    print(
        "Saved",
        len(rows),
        "seat records to Google Sheets."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("TOXIC BMS SEAT PARSER")
    print("=" * 70)

    spreadsheet = get_spreadsheet()

    response = get_seat_layout()

    if response is None:

        print(
            "No BMS response."
        )

        return

    strdata = extract_strdata(
        response
    )

    if not strdata:

        print(
            "Could not extract strData."
        )

        return

    # --------------------------------------------------------
    # Categories
    # --------------------------------------------------------

    categories = parse_categories(
        strdata
    )

    # --------------------------------------------------------
    # Parse seats
    # --------------------------------------------------------

    seats = parse_seat_rows(
        strdata,
        categories
    )

    # --------------------------------------------------------
    # Print summary
    # --------------------------------------------------------

    print_seat_summary(
        seats
    )

    # --------------------------------------------------------
    # Save raw response
    # --------------------------------------------------------

    save_raw_response(
        spreadsheet,
        response,
        strdata
    )

    # --------------------------------------------------------
    # Save parsed seats
    # --------------------------------------------------------

    save_seats(
        spreadsheet,
        seats
    )

    print()
    print("=" * 70)
    print("FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()
