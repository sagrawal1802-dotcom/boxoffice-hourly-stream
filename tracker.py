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
SHOW_DATE = "20260826"
CITY = "mumbai"

# ------------------------------------------------------------
# IMPORTANT
# These are the shows currently identified for Toxic at CSWO.
#
# We are keeping them here initially because the BMS primary
# endpoint seen in the HAR returned 403.
#
# Once this works, we can make show discovery automatic.
# ------------------------------------------------------------

SHOWS = [
    {"session_id": "15925", "show_time": "07:00 AM"},
    {"session_id": "15934", "show_time": "08:00 AM"},
    {"session_id": "16072", "show_time": "09:00 AM"},
    {"session_id": "15926", "show_time": "10:40 AM"},
    {"session_id": "15933", "show_time": "11:40 AM"},
    {"session_id": "16073", "show_time": "01:05 PM"},
    {"session_id": "15927", "show_time": "02:45 PM"},
    {"session_id": "15932", "show_time": "03:45 PM"},
    {"session_id": "16074", "show_time": "05:10 PM"},
    {"session_id": "15928", "show_time": "06:50 PM"},
    {"session_id": "15931", "show_time": "07:50 PM"},
    {"session_id": "16075", "show_time": "09:15 PM"},
    {"session_id": "15929", "show_time": "10:55 PM"},
    {"session_id": "15930", "show_time": "11:55 PM"},
]


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
            rows=50000,
            cols=len(HEADERS)
        )

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
            print("Current headers:")
            print(current_headers)
            print()
            print("Expected headers:")
            print(HEADERS)

    return sheet


# ============================================================
# IST TIMESTAMP
# ============================================================

def get_timestamp_ist():

    tz = pytz.timezone("Asia/Kolkata")

    return datetime.now(tz).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# BMS REQUEST
# ============================================================

def get_seat_layout(session_id):

    url = "https://services-in.bookmyshow.com/doTrans.aspx"

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": VENUE_CODE,
        "strParam1": session_id,
        "strParam2": "",
        "strParam3": "",
        "strParam4": "",
        "strParam5": "",
        "strParam6": "",
        "strParam7": "",
        "strParam8": "",
        "strParam9": "",
        "strParam10": ""
    }

    headers = {

        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),

        "Accept": "application/json, text/plain, */*",

        "Content-Type":
            "application/x-www-form-urlencoded; charset=UTF-8",

        "Origin":
            "https://in.bookmyshow.com",

        "Referer":
            f"https://in.bookmyshow.com/"
            f"buytickets/toxic-{CITY}/movie-mumbai-"
            f"{EVENT_CODE}-MT/"
    }

    for attempt in range(1, 4):

        print(f"Attempt {attempt}/3")

        try:

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                impersonate="chrome120",
                timeout=30
            )

            print(
                f"HTTP status: {response.status_code}"
            )

            print(
                f"Response size: {len(response.content)} bytes"
            )

            if response.status_code != 200:

                print(
                    response.text[:1000]
                )

                time.sleep(2)

                continue

            try:

                data = response.json()

            except Exception:

                print(
                    "Could not decode JSON."
                )

                print(
                    response.text[:2000]
                )

                time.sleep(2)

                continue

            bookmyshow = data.get(
                "BookMyShow",
                {}
            )

            success = bookmyshow.get(
                "blnSuccess"
            )

            print(
                f"blnSuccess: {success}"
            )

            if not success:

                print(
                    f"intException: "
                    f"{bookmyshow.get('intException')}"
                )

                print(
                    f"strException: "
                    f"{bookmyshow.get('strException')}"
                )

                time.sleep(2)

                continue

            str_data = bookmyshow.get(
                "strData"
            )

            if not str_data:

                print(
                    "No strData received."
                )

                time.sleep(2)

                continue

            print(
                f"strData length: {len(str_data)}"
            )

            return str_data

        except Exception as error:

            print(
                f"Request error: {repr(error)}"
            )

            time.sleep(2)

    return None


# ============================================================
# CATEGORY PARSER
# ============================================================

def parse_categories(str_data):

    categories = {}

    parts = str_data.split("|")

    for part in parts:

        if ":" not in part:
            continue

        match = re.match(
            r"^(.+?):([A-Z]):",
            part
        )

        if not match:
            continue

        category_name = match.group(1)
        category_code = match.group(2)

        categories[
            category_code
        ] = category_name

    return categories


# ============================================================
# SEAT TOKEN PARSER
#
# IMPORTANT BMS FORMAT:
#
# B1048+6
#
# B1048 = seat code
# +6    = actual seat number
#
# B1048 = AVAILABLE
# B2049 = SOLD
#
# 10xxx = AVAILABLE
# 20xxx = SOLD
# ============================================================

def parse_seat_token(token):

    token = token.strip()

    if not token:
        return None

    match = re.match(
        r"^([A-Z])([0-9]+)\+([0-9]+)$",
        token
    )

    if not match:
        return None

    row_letter = match.group(1)

    numeric_part = match.group(2)

    seat_number = match.group(3)

    if numeric_part.startswith("10"):

        bms_state = "AVAILABLE"

    elif numeric_part.startswith("20"):

        bms_state = "SOLD"

    else:

        return None

    seat_code = (
        row_letter +
        numeric_part
    )

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": seat_number,
        "bms_state": bms_state
    }


# ============================================================
# ROW PARSER
# ============================================================

def parse_rows(
    str_data,
    session_id,
    show_time
):

    timestamp = get_timestamp_ist()

    categories = parse_categories(
        str_data
    )

    print()
    print("=" * 100)
    print("CATEGORY MAP")
    print("=" * 100)

    for code, name in categories.items():

        print(
            f"{code} -> {name}"
        )

    print()

    seats = []

    sections = str_data.split("|")

    for section in sections:

        section = section.strip()

        if not section:
            continue

        # ----------------------------------------------------
        # Row format:
        #
        # 1:M:A000:...
        #
        # 2:L:B000:...
        #
        # 10:D:C000:...
        # ----------------------------------------------------

        row_match = re.match(
            r"^(\d+):([A-Za-z]):([A-Z]000):(.*)$",
            section
        )

        if not row_match:
            continue

        row_number = row_match.group(1)

        row_name = row_match.group(2)

        category_code = row_match.group(3)[0]

        seat_data = row_match.group(4)

        category = categories.get(
            category_code,
            category_code
        )

        # ----------------------------------------------------
        # The seat entries are separated by +
        #
        # Example:
        #
        # A1052+1
        # A1053+2
        # A20515+9
        #
        # But BMS also has:
        #
        # A0+0
        #
        # which means no seat.
        # ----------------------------------------------------

        # First normalize the row data.
        #
        # BMS row data can contain positional prefixes.
        #
        # Example:
        #
        # 0:A1052+1
        # 1:A1053+2
        #
        # We extract actual seat tokens from the
        # entire row instead of trusting the positional
        # number.

        matches = re.findall(
            r"(?:^|[+:])"
            r"([A-Z])"
            r"(10|20)"
            r"([0-9]+)"
            r"\+([0-9]+)",
            seat_data
        )

        for match in matches:

            letter = match[0]

            state_prefix = match[1]

            seat_suffix = match[2]

            seat_number = match[3]

            seat_code = (
                letter +
                state_prefix +
                seat_suffix
            )

            seat_token = (
                seat_code +
                "+" +
                seat_number
            )

            if state_prefix == "10":

                state = "AVAILABLE"

            elif state_prefix == "20":

                state = "SOLD"

            else:

                continue

            seats.append([
                timestamp,
                EVENT_CODE,
                VENUE_CODE,
                session_id,
                show_time,
                SHOW_DATE,
                CITY,
                row_number,
                row_name,
                category_code,
                category,
                seat_token,
                seat_code,
                seat_number,
                state
            ])

    return seats


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

    for token in tests:

        result = parse_seat_token(token)

        print(
            f"{token:<15} -> {result}"
        )

    print("=" * 70)


# ============================================================
# WRITE TO GOOGLE SHEETS
# ============================================================

def write_to_sheet(
    sheet,
    rows
):

    if not rows:

        print(
            "No rows to write."
        )

        return

    print()
    print("=" * 70)
    print("WRITING TO GOOGLE SHEET")
    print("=" * 70)

    # Append in batches.
    #
    # This avoids thousands of individual API calls.

    batch_size = 500

    written = 0

    for i in range(
        0,
        len(rows),
        batch_size
    ):

        batch = rows[
            i:i + batch_size
        ]

        sheet.append_rows(
            batch,
            value_input_option="USER_ENTERED"
        )

        written += len(batch)

        print(
            f"Written "
            f"{written}/{len(rows)} rows"
        )

    print()
    print(
        f"Google Sheet updated successfully. "
        f"{written} seats written."
    )


# ============================================================
# SUMMARY
# ============================================================

def print_summary(
    show_time,
    session_id,
    seats
):

    available = sum(
        1
        for row in seats
        if row[-1] == "AVAILABLE"
    )

    sold = sum(
        1
        for row in seats
        if row[-1] == "SOLD"
    )

    total = available + sold

    print()
    print(
        "=" * 70
    )

    print(
        f"SHOW: {show_time} "
        f"| SESSION: {session_id}"
    )

    print(
        "=" * 70
    )

    print(
        f"AVAILABLE : {available}"
    )

    print(
        f"SOLD      : {sold}"
    )

    print(
        f"TOTAL     : {total}"
    )


# ============================================================
# PROCESS ONE SHOW
# ============================================================

def process_show(
    show
):

    session_id = show["session_id"]

    show_time = show["show_time"]

    print()
    print(
        "#" * 80
    )

    print(
        f"PROCESSING SHOW "
        f"{show_time}"
    )

    print(
        f"Session ID: {session_id}"
    )

    print(
        "#" * 80
    )

    str_data = get_seat_layout(
        session_id
    )

    if not str_data:

        print(
            f"FAILED: No seat layout "
            f"for session {session_id}"
        )

        return []

    seats = parse_rows(
        str_data,
        session_id,
        show_time
    )

    print_summary(
        show_time,
        session_id,
        seats
    )

    return seats


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 80)
    print("TOXIC BMS ALL-SHOW SEAT TRACKER")
    print("=" * 80)

    print(
        datetime.now(
            pytz.timezone("Asia/Kolkata")
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print()

    print(
        f"Event: {EVENT_CODE}"
    )

    print(
        f"Venue: {VENUE_CODE}"
    )

    print(
        f"Date:  {SHOW_DATE}"
    )

    print(
        f"City:  {CITY}"
    )

    print(
        f"Shows: {len(SHOWS)}"
    )

    print(
        "=" * 80
    )

    # --------------------------------------------------------
    # Parser test
    # --------------------------------------------------------

    test_parser()

    # --------------------------------------------------------
    # Google Sheet
    # --------------------------------------------------------

    print()
    print(
        "Connecting to Google Sheets..."
    )

    try:

        sheet = init_google_sheet()

        print(
            "Google Sheets connected."
        )

    except Exception as error:

        print(
            "ERROR connecting to Google Sheets:"
        )

        print(
            repr(error)
        )

        raise

    # --------------------------------------------------------
    # Process all shows
    # --------------------------------------------------------

    all_rows = []

    show_summaries = []

    for index, show in enumerate(
        SHOWS,
        start=1
    ):

        print()
        print(
            f"SHOW {index}/{len(SHOWS)}"
        )

        rows = process_show(
            show
        )

        all_rows.extend(
            rows
        )

        available = sum(
            1
            for row in rows
            if row[-1] == "AVAILABLE"
        )

        sold = sum(
            1
            for row in rows
            if row[-1] == "SOLD"
        )

        show_summaries.append({
            "session_id":
                show["session_id"],

            "show_time":
                show["show_time"],

            "available":
                available,

            "sold":
                sold,

            "total":
                available + sold
        })

        # Small delay between BMS requests.

        if index < len(SHOWS):

            time.sleep(1)

    # --------------------------------------------------------
    # Overall summary
    # --------------------------------------------------------

    print()
    print()
    print(
        "=" * 90
    )

    print(
        "ALL SHOW SUMMARY"
    )

    print(
        "=" * 90
    )

    print(
        f"{'TIME':<12}"
        f"{'SESSION':<10}"
        f"{'AVAILABLE':<12}"
        f"{'SOLD':<10}"
        f"{'TOTAL':<10}"
    )

    print(
        "-" * 90
    )

    total_available = 0

    total_sold = 0

    total_seats = 0

    for summary in show_summaries:

        print(
            f"{summary['show_time']:<12}"
            f"{summary['session_id']:<10}"
            f"{summary['available']:<12}"
            f"{summary['sold']:<10}"
            f"{summary['total']:<10}"
        )

        total_available += (
            summary["available"]
        )

        total_sold += (
            summary["sold"]
        )

        total_seats += (
            summary["total"]
        )

    print(
        "-" * 90
    )

    print(
        f"{'TOTAL':<12}"
        f"{'':<10}"
        f"{total_available:<12}"
        f"{total_sold:<10}"
        f"{total_seats:<10}"
    )

    print(
        "=" * 90
    )

    # --------------------------------------------------------
    # Google Sheet
    # --------------------------------------------------------

    write_to_sheet(
        sheet,
        all_rows
    )

    print()
    print(
        "=" * 80
    )

    print(
        "BMS ALL-SHOW TRACKING COMPLETED"
    )

    print(
        f"Shows processed: {len(SHOWS)}"
    )

    print(
        f"Total seats:     {total_seats}"
    )

    print(
        f"Available:       {total_available}"
    )

    print(
        f"Sold:            {total_sold}"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":

    main()
