import os
import re
import json
import base64
import time
from datetime import datetime

import pytz
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


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

# Delay between shows.
# Keep this reasonably slow.
DELAY_BETWEEN_SHOWS = 15

# Maximum time to wait for a seat-layout page.
PAGE_TIMEOUT = 60000


# ============================================================
# GOOGLE CREDENTIALS
# ============================================================

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)


# ============================================================
# SHEET HEADERS
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
# KNOWN SHOW LIST
#
# These are the sessions already discovered from BMS for
# ET00379311 / CSWO / 20260826.
#
# Once browser discovery is confirmed, we can remove this
# fallback and make discovery completely automatic.
# ============================================================

KNOWN_SHOWS = [
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
# PRINT
# ============================================================

def banner(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ============================================================
# IST TIMESTAMP
# ============================================================

def get_ist_timestamp():
    tz = pytz.timezone("Asia/Kolkata")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# GOOGLE SHEETS
# ============================================================

def init_google_sheet():

    banner("CONNECTING TO GOOGLE SHEETS")

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
            f"Could not decode Google credentials: {error}"
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

        print(f"Creating worksheet: {SHEET_TAB_NAME}")

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=50000,
            cols=len(HEADERS)
        )

    existing = sheet.get_all_values()

    if not existing:

        print("Adding headers...")

        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED"
        )

    else:

        current_headers = existing[0]

        if current_headers[:len(HEADERS)] != HEADERS:

            print("WARNING: Existing headers differ from current headers.")

    print("Google Sheets connected.")

    return sheet


# ============================================================
# SEAT TOKEN PARSER
#
# Examples:
#
# A1052+1
# A20515+9
# B1042+2
# B2049+7
#
# The digit immediately before the seat code determines state:
#
# A1... / B1... / C1... / D1... / E1... = AVAILABLE
# A2... / B2... / C2... / D2... / E2... = SOLD
#
# Seat number is the value AFTER +
# ============================================================

def parse_seat_token(token):

    if not token:
        return None

    token = str(token).strip()

    if token in ("A0+0", "B0+0", "C0+0", "D0+0", "E0+0"):
        return None

    match = re.match(
        r"^([A-E])([12])(\d+)\+(\d+)$",
        token
    )

    if not match:
        return None

    row_letter = match.group(1)
    state_code = match.group(2)
    seat_code_number = match.group(3)
    seat_number = match.group(4)

    seat_code = f"{row_letter}{state_code}{seat_code_number}"

    status = (
        "AVAILABLE"
        if state_code == "1"
        else "SOLD"
    )

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": seat_number,
        "status": status,
        "row_letter": row_letter,
    }


# ============================================================
# PARSER TEST
# ============================================================

def test_parser():

    banner("TESTING BMS SEAT PARSER")

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


# ============================================================
# EXTRACT SEAT TOKENS FROM PAGE
#
# We inspect the rendered HTML/JS text from the actual BMS page.
#
# We are looking for strings such as:
#
# A1052+1
# A20515+9
# B1042+2
# B2049+7
#
# ============================================================

def extract_seat_tokens(page):

    html = page.content()

    # Find every potential BMS seat token.
    matches = re.findall(
        r"\b[A-E][12]\d+\+\d+\b",
        html
    )

    # Preserve order and remove duplicates.
    seen = set()
    tokens = []

    for token in matches:

        if token not in seen:

            seen.add(token)
            tokens.append(token)

    return tokens


# ============================================================
# EXTRACT ROW INFORMATION
#
# BMS row layout contains information similar to:
#
# 1:M:
# 2:L:
# 3:K:
#
# The seat token itself tells us the A/B/C/D/E row category
# family, while the rendered page provides the row name.
#
# For this first browser version we use the seat row letter
# and map it to the category.
# ============================================================

def get_category_from_seat_code(seat_code):

    if not seat_code:
        return ""

    row_letter = seat_code[0]

    return CATEGORY_MAP.get(
        row_letter,
        ""
    )


# ============================================================
# PROCESS ONE SHOW
# ============================================================

def process_show(page, show_time, session_id):

    banner(
        f"PROCESSING SHOW {show_time} | SESSION {session_id}"
    )

    url = (
        f"https://in.bookmyshow.com/movies/"
        f"{CITY}/seat-layout/"
        f"{EVENT_CODE}/"
        f"{VENUE_CODE}/"
        f"{session_id}/"
        f"{SHOW_DATE}"
    )

    print("Opening:")
    print(url)

    try:

        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT
        )

        if response:

            print(
                f"Initial HTTP status: {response.status}"
            )

    except Exception as error:

        print(
            f"Page navigation error: {error}"
        )

        return []

    # Give BMS time to render the seat layout.
    print("Waiting for BMS seat layout...")

    page.wait_for_timeout(12000)

    # Try to wait for network activity to settle.
    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=20000
        )

    except Exception:

        pass

    print("Extracting seat tokens...")

    tokens = extract_seat_tokens(page)

    print(
        f"Potential seat tokens found: {len(tokens)}"
    )

    parsed_rows = []

    for token in tokens:

        parsed = parse_seat_token(token)

        if not parsed:
            continue

        category = get_category_from_seat_code(
            parsed["seat_code"]
        )

        row_number = ""
        row_name = parsed["row_letter"]

        # We retain the category row letter here.
        # We can enrich row-name mapping later from the
        # exact BMS layout payload.

        parsed_rows.append([
            get_ist_timestamp(),
            EVENT_CODE,
            VENUE_CODE,
            session_id,
            show_time,
            SHOW_DATE,
            CITY,
            row_number,
            row_name,
            parsed["row_letter"],
            category,
            parsed["seat_token"],
            parsed["seat_code"],
            parsed["seat_number"],
            parsed["status"],
        ])

    # Deduplicate seats.
    unique = {}

    for row in parsed_rows:

        key = (
            row[3],   # session
            row[11],  # seat token
        )

        unique[key] = row

    parsed_rows = list(unique.values())

    available = sum(
        1 for row in parsed_rows
        if row[14] == "AVAILABLE"
    )

    sold = sum(
        1 for row in parsed_rows
        if row[14] == "SOLD"
    )

    print()
    print("SHOW SUMMARY")
    print("-" * 50)
    print(f"Session    : {session_id}")
    print(f"Show       : {show_time}")
    print(f"Available  : {available}")
    print(f"Sold       : {sold}")
    print(f"Total      : {len(parsed_rows)}")

    return parsed_rows


# ============================================================
# WRITE TO GOOGLE SHEETS
# ============================================================

def write_rows(sheet, rows):

    if not rows:

        print("No rows to write.")

        return

    print()
    print("=" * 70)
    print("WRITING TO GOOGLE SHEETS")
    print("=" * 70)

    try:

        sheet.append_rows(
            rows,
            value_input_option="USER_ENTERED"
        )

        print(
            f"Written {len(rows)} rows."
        )

    except Exception as error:

        print(
            f"Google Sheets write failed: {error}"
        )

        raise


# ============================================================
# MAIN
# ============================================================

def main():

    banner("BMS VENUE ALL-SHOW BROWSER TRACKER")

    print(
        f"Timestamp : {get_ist_timestamp()}"
    )

    print(
        f"Event     : {EVENT_CODE}"
    )

    print(
        f"Venue     : {VENUE_CODE}"
    )

    print(
        f"Date      : {SHOW_DATE}"
    )

    print(
        f"City      : {CITY}"
    )

    print(
        f"Shows     : {len(KNOWN_SHOWS)}"
    )

    test_parser()

    sheet = init_google_sheet()

    successful_shows = 0
    failed_shows = 0
    total_seats = 0

    with sync_playwright() as p:

        print()
        print(
            "Launching Chromium..."
        )

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        for index, (show_time, session_id) in enumerate(
            KNOWN_SHOWS,
            start=1
        ):

            print()
            print(
                f"SHOW {index}/{len(KNOWN_SHOWS)}"
            )

            try:

                rows = process_show(
                    page,
                    show_time,
                    session_id
                )

                if rows:

                    write_rows(
                        sheet,
                        rows
                    )

                    successful_shows += 1
                    total_seats += len(rows)

                else:

                    print(
                        "No seats extracted for this show."
                    )

                    failed_shows += 1

            except Exception as error:

                print(
                    f"FAILED SHOW {session_id}: {error}"
                )

                failed_shows += 1

            # Do not hammer BMS.
            if index < len(KNOWN_SHOWS):

                print()
                print(
                    f"Waiting {DELAY_BETWEEN_SHOWS} seconds "
                    f"before next show..."
                )

                time.sleep(
                    DELAY_BETWEEN_SHOWS
                )

        context.close()
        browser.close()

    banner("TRACKING COMPLETED")

    print(
        f"Successful shows : {successful_shows}"
    )

    print(
        f"Failed shows     : {failed_shows}"
    )

    print(
        f"Total seat rows   : {total_seats}"
    )

    print(
        f"Timestamp         : {get_ist_timestamp()}"
    )


if __name__ == "__main__":
    main()
