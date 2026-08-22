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

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)


# ============================================================
# ALL SHOWS
# ============================================================

SHOWS = [
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
    "BMS State",
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
        "https://www.googleapis.com/auth/drive",
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
            print("Current:", current_headers)
            print("Expected:", HEADERS)

    return sheet


# ============================================================
# BMS REQUEST HEADERS
# ============================================================

def build_headers(session_id):

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),

        "Accept": (
            "application/json, text/plain, */*"
        ),

        "Content-Type": (
            "application/x-www-form-urlencoded; charset=UTF-8"
        ),

        "Origin": (
            "https://in.bookmyshow.com"
        ),

        "Referer": (
            f"https://in.bookmyshow.com/movies/"
            f"{CITY}/seat-layout/"
            f"{EVENT_CODE}/"
            f"{VENUE_CODE}/"
            f"{session_id}/"
            f"{SHOW_DATE}"
        ),

        "Accept-Language": (
            "en-IN,en;q=0.9"
        ),

        "Connection": "keep-alive",
    }


# ============================================================
# GET BMS SEAT LAYOUT
# ============================================================

def get_seat_layout(session_id, show_time):

    url = "https://services-in.bookmyshow.com/doTrans.aspx"

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": VENUE_CODE,
        "strParam1": session_id,
        "strParam2": "WEB",
        "strParam5": "Y",
        "strParam6": "Y",
        "strParam7": "N",
        "strFormat": "json",
    }

    headers = build_headers(session_id)

    print()
    print("=" * 80)
    print(f"PROCESSING SHOW {show_time}")
    print("=" * 80)
    print(f"Session ID : {session_id}")
    print(f"Show Date  : {SHOW_DATE}")
    print()

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

            print(
                f"HTTP status: {response.status_code}"
            )

            print(
                f"Response size: {len(response.content)} bytes"
            )

            if response.status_code != 200:

                print("BMS request failed.")

                print(
                    response.text[:1000]
                )

                if attempt < 3:
                    time.sleep(3)

                continue

            # ------------------------------------------------
            # Decode JSON
            # ------------------------------------------------

            try:

                data = response.json()

            except Exception:

                print("Could not decode JSON.")

                print(
                    response.text[:2000]
                )

                if attempt < 3:
                    time.sleep(3)

                continue

            # ------------------------------------------------
            # BookMyShow response
            # ------------------------------------------------

            bookmyshow = data.get(
                "BookMyShow",
                {}
            )

            success = bookmyshow.get(
                "blnSuccess"
            )

            exception = bookmyshow.get(
                "strException"
            )

            exception_code = bookmyshow.get(
                "intException"
            )

            str_data = bookmyshow.get(
                "strData"
            )

            print(
                f"blnSuccess : {success}"
            )

            print(
                f"intException : {exception_code}"
            )

            if exception:
                print(
                    f"strException : {exception}"
                )

            # ------------------------------------------------
            # Successful response
            # ------------------------------------------------

            if str_data:

                print(
                    f"strData length: {len(str_data)}"
                )

                return str_data

            # ------------------------------------------------
            # Failed response
            # ------------------------------------------------

            print(
                "No strData returned."
            )

            if attempt < 3:

                time.sleep(3)

        except Exception as error:

            print(
                f"Request error: {repr(error)}"
            )

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

    token = token.strip()

    if not token:
        return None

    token = token.replace(" ", "")

    match = re.match(
        r"^([A-Za-z])(\d+)\+(\d+)$",
        token
    )

    if not match:
        return None

    letter = match.group(1).upper()

    numeric_code = match.group(2)

    actual_seat_number = match.group(3)

    # A0+0 / B0+0 = no physical seat
    if numeric_code == "0":
        return None

    seat_code = (
        f"{letter}{numeric_code}"
    )

    # 1xxxx = available
    # 2xxxx = sold

    if numeric_code.startswith("1"):

        bms_state = "AVAILABLE"

    elif numeric_code.startswith("2"):

        bms_state = "SOLD"

    else:

        return None

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": actual_seat_number,
        "bms_state": bms_state,
    }


# ============================================================
# PARSE SEAT ROWS
# ============================================================

def parse_seat_rows(
    str_data,
    session_id,
    show_time
):

    timestamp = datetime.now(
        pytz.timezone("Asia/Kolkata")
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # Separate category information from seat information
    # --------------------------------------------------------

    sections = str_data.split(
        "||",
        1
    )

    if len(sections) != 2:

        print(
            "ERROR: Could not split BMS strData."
        )

        return []

    category_section = sections[0]

    seat_section = sections[1]

    categories = parse_categories(
        category_section
    )

    print()
    print("CATEGORY MAP")
    print("-" * 60)

    for code, name in categories.items():

        print(
            f"{code} -> {name}"
        )

    print("-" * 60)

    results = []

    available_count = 0

    sold_count = 0

    # --------------------------------------------------------
    # Rows
    # --------------------------------------------------------

    raw_rows = seat_section.split("|")

    for raw_row in raw_rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        # Expected:
        #
        # 1:M:A000:A1052+1:A1053+2...

        row_parts = raw_row.split(
            ":",
            3
        )

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
        # Seats separated by :
        #
        # A1052+1:A1053+2:A20515+9
        # ----------------------------------------------------

        seat_tokens = seat_data.split(":")

        for token in seat_tokens:

            token = token.strip()

            if not token:
                continue

            parsed = parse_seat_token(
                token
            )

            if parsed is None:
                continue

            if parsed["bms_state"] == "AVAILABLE":

                available_count += 1

            elif parsed["bms_state"] == "SOLD":

                sold_count += 1

            results.append([
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
                parsed["seat_token"],
                parsed["seat_code"],
                parsed["seat_number"],
                parsed["bms_state"],
            ])

    print()
    print("=" * 70)
    print("SHOW SUMMARY")
    print("=" * 70)

    print(
        f"Show       : {show_time}"
    )

    print(
        f"Session    : {session_id}"
    )

    print(
        f"Available  : {available_count}"
    )

    print(
        f"Sold       : {sold_count}"
    )

    print(
        f"Total      : "
        f"{available_count + sold_count}"
    )

    print("=" * 70)

    return results


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
        "B0+0",
    ]

    for test in tests:

        result = parse_seat_token(
            test
        )

        print(
            f"{test:<15} -> {result}"
        )

    print("=" * 70)


# ============================================================
# PRINT SHOW SUMMARY
# ============================================================

def print_final_summary(
    all_rows,
    successful_shows,
    failed_shows
):

    print()
    print("=" * 80)
    print("FINAL TRACKING SUMMARY")
    print("=" * 80)

    print(
        f"Shows requested : {len(SHOWS)}"
    )

    print(
        f"Shows successful: {len(successful_shows)}"
    )

    print(
        f"Shows failed    : {len(failed_shows)}"
    )

    print(
        f"Total seats     : {len(all_rows)}"
    )

    print()

    if successful_shows:

        print("SUCCESSFUL SHOWS")

        for show_time, session_id, seat_count in successful_shows:

            print(
                f"{show_time} | "
                f"Session {session_id} | "
                f"{seat_count} seats"
            )

    if failed_shows:

        print()
        print("FAILED SHOWS")

        for show_time, session_id in failed_shows:

            print(
                f"{show_time} | "
                f"Session {session_id}"
            )

    print("=" * 80)


# ============================================================
# GOOGLE SHEET WRITE
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

    batch_size = 500

    total = len(rows)

    for start in range(
        0,
        total,
        batch_size
    ):

        batch = rows[
            start:start + batch_size
        ]

        sheet.append_rows(
            batch,
            value_input_option="USER_ENTERED"
        )

        written = min(
            start + batch_size,
            total
        )

        print(
            f"Written {written}/{total} rows"
        )

    print()

    print(
        f"Google Sheet updated successfully. "
        f"{total} seats written."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 80)
    print("BMS ALL-SHOW SEAT TRACKER")
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
        f"Event : {EVENT_CODE}"
    )

    print(
        f"Venue : {VENUE_CODE}"
    )

    print(
        f"Date  : {SHOW_DATE}"
    )

    print(
        f"City  : {CITY}"
    )

    print(
        f"Shows : {len(SHOWS)}"
    )

    print("=" * 80)

    # --------------------------------------------------------
    # Test parser
    # --------------------------------------------------------

    test_parser()

    # --------------------------------------------------------
    # Connect Google Sheets BEFORE processing
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("CONNECTING TO GOOGLE SHEETS")
    print("=" * 80)

    try:

        sheet = init_google_sheet()

        print(
            "Google Sheets connected."
        )

    except Exception as error:

        print()
        print(
            "ERROR CONNECTING TO GOOGLE SHEETS:"
        )

        print(
            repr(error)
        )

        return

    # --------------------------------------------------------
    # Process all shows
    # --------------------------------------------------------

    all_rows = []

    successful_shows = []

    failed_shows = []

    for index, (
        show_time,
        session_id
    ) in enumerate(
        SHOWS,
        start=1
    ):

        print()
        print()
        print(
            "#" * 80
        )

        print(
            f"SHOW {index}/{len(SHOWS)}"
        )

        print(
            "#" * 80
        )

        str_data = get_seat_layout(
            session_id,
            show_time
        )

        if not str_data:

            print()
            print(
                f"FAILED: No seat layout "
                f"for session {session_id}"
            )

            failed_shows.append(
                (
                    show_time,
                    session_id
                )
            )

            # Short delay before next request
            if index < len(SHOWS):

                time.sleep(2)

            continue

        rows = parse_seat_rows(
            str_data,
            session_id,
            show_time
        )

        if not rows:

            print()
            print(
                f"FAILED: No seats parsed "
                f"for session {session_id}"
            )

            failed_shows.append(
                (
                    show_time,
                    session_id
                )
            )

        else:

            all_rows.extend(rows)

            successful_shows.append(
                (
                    show_time,
                    session_id,
                    len(rows)
                )
            )

        # Small delay between shows
        # Avoid hammering BMS unnecessarily

        if index < len(SHOWS):

            time.sleep(2)

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print_final_summary(
        all_rows,
        successful_shows,
        failed_shows
    )

    # --------------------------------------------------------
    # Write everything in batches
    # --------------------------------------------------------

    if all_rows:

        write_to_sheet(
            sheet,
            all_rows
        )

    else:

        print()
        print(
            "NO SEAT DATA WAS RECEIVED "
            "FOR ANY SHOW."
        )

    # --------------------------------------------------------
    # Completed
    # --------------------------------------------------------

    print()
    print("=" * 80)
    print("BMS ALL-SHOW TRACKING RUN COMPLETED")
    print("=" * 80)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
