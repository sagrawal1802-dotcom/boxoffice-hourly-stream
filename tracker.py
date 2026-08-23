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

SHEET_TAB_NAME = "Toxic_Cinepolis"

CITY = "mumbai"
SHOW_DATE = "20260826"

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"

# ============================================================
# IMPORTANT
#
# ONLY PUT THE 7 CONFIRMED CINEPOLIS VENUE CODES HERE.
#
# DO NOT PUT CSWO HERE.
#
# DO NOT USE THE EARLIER 10 CANDIDATE CODES.
# ============================================================

VENUE_CODES = [
    "CODE_1",
    "CODE_2",
    "CODE_3",
    "CODE_4",
    "CODE_5",
    "CODE_6",
    "CODE_7",
]


# ============================================================
# BMS EVENT CODES
# ============================================================

EVENT_CODES = [
    "ET00379311",   # Hindi 2D
    "ET00513458",   # IMAX
    "ET00513506",   # 4DX
]


# ============================================================
# DELAYS / RETRIES
# ============================================================

DELAY_BETWEEN_SHOWS = 8
DELAY_BETWEEN_VENUES = 5

MAX_ATTEMPTS = 3

GOOGLE_BATCH_SIZE = 500


# ============================================================
# SHOW LIST
#
# Same 23 CSWO shows that were already successfully tracked.
#
# The important difference is that these session IDs are NOT
# reused for Cinepolis.
#
# The code below first attempts to obtain the Cinepolis show
# sessions. If BMS discovery is unavailable, a venue-specific
# session list can be supplied in VENUE_SHOWS.
# ============================================================

VENUE_SHOWS = {
    # Example structure:
    #
    # "VENUE_CODE": [
    #     {
    #         "format": "Hindi 2D",
    #         "show_time": "07:00 AM",
    #         "event_code": "ET00379311",
    #         "session_id": "12345",
    #     },
    # ]
}


# ============================================================
# BANNER
# ============================================================

def banner(text):
    print()
    print("=" * 90)
    print(text)
    print("=" * 90)


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

    print()
    print("=" * 90)
    print("CONNECTING TO GOOGLE SHEETS")
    print("=" * 90)

    credentials_json = os.environ.get("GOOGLE_CREDENTIALS")

    if not credentials_json:
        credentials_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not credentials_json:
        if os.path.exists("credentials.json"):
            with open("credentials.json", "r", encoding="utf-8") as f:
                credentials_json = f.read()

    if not credentials_json:
        raise RuntimeError(
            "Google credentials not found. "
            "Set GOOGLE_CREDENTIALS / GOOGLE_SERVICE_ACCOUNT_JSON "
            "or provide credentials.json."
        )

    try:
        if isinstance(credentials_json, str):
            credentials_data = json.loads(credentials_json)
        else:
            credentials_data = credentials_json
    except Exception:
        credentials_data = json.loads(
            base64.b64decode(credentials_json).decode("utf-8")
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        credentials_data,
        scopes=scopes,
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(SHEET_TAB_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=1000,
            cols=20,
        )

    expected_headers = [
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

    current_headers = worksheet.row_values(1)

    if current_headers != expected_headers:
        print("Setting expected headers...")
        worksheet.update(
            "A1",
            [expected_headers],
        )

    print("Google Sheets connected.")

    return worksheet


# ============================================================
# BMS SEAT TOKEN PARSER
#
# Examples:
#
# B1048+6 = AVAILABLE
# B2049+7 = SOLD
#
# First digit:
# 1 = AVAILABLE
# 2 = SOLD
# ============================================================

def parse_seat_token(token):

    if not token:
        return None

    token = token.strip()

    match = re.match(
        r"^([A-Z]+)(\d+)\+(\d+)$",
        token,
    )

    if not match:
        return None

    row_letter = match.group(1)
    numeric_code = match.group(2)
    seat_number = match.group(3)

    if numeric_code == "0":
        return None

    state_digit = numeric_code[0]

    if state_digit == "1":
        bms_state = "AVAILABLE"
    elif state_digit == "2":
        bms_state = "SOLD"
    else:
        return None

    return {
        "seat_token": token,
        "seat_code": f"{row_letter}{numeric_code}",
        "seat_number": seat_number,
        "bms_state": bms_state,
        "row_letter": row_letter,
    }


# ============================================================
# CATEGORY PARSER
# ============================================================

def parse_categories(category_section):

    categories = {}

    if not category_section:
        return categories

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
# TEST PARSER
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
# BMS SEAT LAYOUT REQUEST
#
# THIS IS THE SAME REQUEST USED BY CSWO.
#
# Only venue_code and session_id change.
# ============================================================

def get_seat_layout(
    event_code,
    venue_code,
    session_id,
    show_time,
):

    url = "https://services-in.bookmyshow.com/doTrans.aspx"

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": venue_code,
        "strParam1": session_id,
        "strParam2": "WEB",
        "strParam5": "Y",
        "strParam6": "Y",
        "strParam7": "N",
        "strFormat": "json",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": (
            "application/x-www-form-urlencoded; charset=UTF-8"
        ),
        "Origin": "https://in.bookmyshow.com",
        "Referer": (
            f"https://in.bookmyshow.com/movies/"
            f"{CITY}/seat-layout/"
            f"{event_code}/{venue_code}/"
            f"{session_id}/{SHOW_DATE}"
        ),
    }

    print()
    print("-" * 90)
    print(
        f"SEAT LAYOUT | {venue_code} | "
        f"{show_time} | Session {session_id}"
    )
    print("-" * 90)

    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:

            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS}"
            )

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                impersonate="chrome120",
                timeout=30,
            )

            print(
                f"HTTP status: {response.status_code}"
            )

            print(
                f"Response size: "
                f"{len(response.content)} bytes"
            )

            if response.status_code != 200:

                print("BMS request failed.")

                if attempt < MAX_ATTEMPTS:
                    time.sleep(4)

                continue

            try:

                data = response.json()

            except Exception:

                text = response.text.strip()

                print("JSON decoding failed.")
                print(text[:1000])

                if attempt < MAX_ATTEMPTS:
                    time.sleep(4)

                continue

            bookmyshow = data.get(
                "BookMyShow",
                {},
            )

            success = bookmyshow.get(
                "blnSuccess"
            )

            print(
                f"blnSuccess : {success}"
            )

            print(
                f"intException : "
                f"{bookmyshow.get('intException')}"
            )

            if bookmyshow.get("strException"):

                print(
                    f"strException : "
                    f"{bookmyshow.get('strException')}"
                )

            str_data = bookmyshow.get(
                "strData"
            )

            if not str_data:

                print(
                    "No strData returned by BMS."
                )

                if attempt < MAX_ATTEMPTS:
                    time.sleep(4)

                continue

            print(
                f"strData length : "
                f"{len(str_data)}"
            )

            return str_data

        except Exception as error:

            print(
                f"Request error: {repr(error)}"
            )

            if attempt < MAX_ATTEMPTS:
                time.sleep(4)

    return None


# ============================================================
# PARSE SEAT LAYOUT RESPONSE
# ============================================================

def parse_seat_layout(
    str_data,
    event_code,
    venue_code,
    session_id,
    show_time,
):

    if not str_data:
        return []

    rows = []

    category_map = {}

    # --------------------------------------------------------
    # CATEGORY INFORMATION
    # --------------------------------------------------------

    category_match = re.search(
        r"(?:CATEGORY|Category)[^|]*\|([^#]+)",
        str_data,
        re.IGNORECASE,
    )

    if category_match:
        category_map = parse_categories(
            category_match.group(1)
        )

    if category_map:

        print()
        print("CATEGORY MAP")
        print("-" * 60)

        for code, name in category_map.items():

            print(
                f"{code} -> {name}"
            )

        print("-" * 60)

    # --------------------------------------------------------
    # FIND SEAT TOKENS
    # --------------------------------------------------------

    tokens = re.findall(
        r"[A-Z]+\d+\+\d+",
        str_data,
    )

    seen = set()

    for token in tokens:

        if token in seen:
            continue

        seen.add(token)

        parsed = parse_seat_token(token)

        if not parsed:
            continue

        row_letter = parsed["row_letter"]

        rows.append(
            {
                "Timestamp IST": get_ist_timestamp(),
                "Event Code": event_code,
                "Venue Code": venue_code,
                "Session ID": session_id,
                "Show Time": show_time,
                "Date": SHOW_DATE,
                "City": CITY,
                "Row Number": "",
                "Row Name": row_letter,
                "Category Code": "",
                "Category": "",
                "Seat Token": parsed["seat_token"],
                "Seat Code": parsed["seat_code"],
                "Seat Number": parsed["seat_number"],
                "BMS State": parsed["bms_state"],
            }
        )

    return rows


# ============================================================
# SHOW DISCOVERY
#
# This function intentionally does NOT attempt the old
# Cinepolis discovery process.
#
# If session data has already been extracted from the HAR,
# put it in VENUE_SHOWS.
# ============================================================

def get_venue_shows(venue_code):

    shows = VENUE_SHOWS.get(
        venue_code,
        []
    )

    if shows:

        return shows

    print()
    print(
        f"WARNING: No show/session list supplied "
        f"for venue {venue_code}"
    )

    print(
        "Seat-layout requests cannot be made "
        "without the venue's actual session IDs."
    )

    return []


# ============================================================
# GOOGLE SHEETS BATCH WRITE
# ============================================================

def write_rows(
    worksheet,
    rows,
):

    if not rows:
        return

    values = []

    for row in rows:

        values.append(
            [
                row["Timestamp IST"],
                row["Event Code"],
                row["Venue Code"],
                row["Session ID"],
                row["Show Time"],
                row["Date"],
                row["City"],
                row["Row Number"],
                row["Row Name"],
                row["Category Code"],
                row["Category"],
                row["Seat Token"],
                row["Seat Code"],
                row["Seat Number"],
                row["BMS State"],
            ]
        )

    for start in range(
        0,
        len(values),
        GOOGLE_BATCH_SIZE,
    ):

        batch = values[
            start:start + GOOGLE_BATCH_SIZE
        ]

        worksheet.append_rows(
            batch,
            value_input_option="RAW",
        )

        print(
            f"Wrote {len(batch)} rows to Google Sheets."
        )


# ============================================================
# MAIN VENUE PROCESSOR
# ============================================================

def process_venue(
    worksheet,
    venue_code,
):

    banner(
        f"CINEPOLIS VENUE {venue_code}"
    )

    print(
        f"Movie     : {MOVIE_NAME}"
    )

    print(
        f"City      : {CITY}"
    )

    print(
        f"Venue     : {venue_code}"
    )

    print(
        f"Date      : {SHOW_DATE}"
    )

    shows = get_venue_shows(
        venue_code
    )

    if not shows:

        print(
            f"No shows available for {venue_code}"
        )

        return {
            "venue": venue_code,
            "shows": 0,
            "successful": 0,
            "failed": 0,
            "available": 0,
            "sold": 0,
            "total": 0,
        }

    print()
    print(
        f"SHOWS FOUND: {len(shows)}"
    )

    all_rows = []

    successful = 0
    failed = 0

    total_available = 0
    total_sold = 0
    total_seats = 0

    for index, show in enumerate(
        shows,
        start=1,
    ):

        print()
        print("#" * 80)

        print(
            f"SHOW {index}/{len(shows)}"
        )

        print("#" * 80)

        show_time = show["show_time"]
        event_code = show["event_code"]
        session_id = str(
            show["session_id"]
        )

        print(
            f"Format     : {show['format']}"
        )

        print(
            f"Show Time  : {show_time}"
        )

        print(
            f"Event      : {event_code}"
        )

        print(
            f"Venue      : {venue_code}"
        )

        print(
            f"Session ID : {session_id}"
        )

        print(
            f"Show Date  : {SHOW_DATE}"
        )

        str_data = get_seat_layout(
            event_code,
            venue_code,
            session_id,
            show_time,
        )

        if not str_data:

            print(
                f"FAILED: No seat layout "
                f"for session {session_id}"
            )

            failed += 1

            time.sleep(
                DELAY_BETWEEN_SHOWS
            )

            continue

        rows = parse_seat_layout(
            str_data,
            event_code,
            venue_code,
            session_id,
            show_time,
        )

        if not rows:

            print(
                "FAILED: No seats parsed."
            )

            failed += 1

            time.sleep(
                DELAY_BETWEEN_SHOWS
            )

            continue

        available = sum(
            1
            for row in rows
            if row["BMS State"] == "AVAILABLE"
        )

        sold = sum(
            1
            for row in rows
            if row["BMS State"] == "SOLD"
        )

        total = available + sold

        total_available += available
        total_sold += sold
        total_seats += total

        successful += 1

        all_rows.extend(rows)

        print()
        print("=" * 70)

        print(
            f"SHOW SUMMARY"
        )

        print("=" * 70)

        print(
            f"Venue     : {venue_code}"
        )

        print(
            f"Show      : {show_time}"
        )

        print(
            f"Session   : {session_id}"
        )

        print(
            f"Available : {available}"
        )

        print(
            f"Sold      : {sold}"
        )

        print(
            f"Total     : {total}"
        )

        print("=" * 70)

        if index < len(shows):

            time.sleep(
                DELAY_BETWEEN_SHOWS
            )

    if all_rows:

        write_rows(
            worksheet,
            all_rows,
        )

    banner(
        f"VENUE {venue_code} COMPLETED"
    )

    print(
        f"Shows       : {len(shows)}"
    )

    print(
        f"Successful  : {successful}"
    )

    print(
        f"Failed      : {failed}"
    )

    print(
        f"Available   : {total_available}"
    )

    print(
        f"Sold        : {total_sold}"
    )

    print(
        f"Total seats : {total_seats}"
    )

    return {
        "venue": venue_code,
        "shows": len(shows),
        "successful": successful,
        "failed": failed,
        "available": total_available,
        "sold": total_sold,
        "total": total_seats,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    banner(
        "BMS TOXIC - CINEPOLIS 7 VENUE SEAT TRACKER"
    )

    print(
        f"Timestamp : {get_ist_timestamp()}"
    )

    print(
        f"Movie     : {MOVIE_NAME}"
    )

    print(
        f"City      : {CITY}"
    )

    print(
        f"Date      : {SHOW_DATE}"
    )

    print()
    print(
        "CINEPOLIS VENUES"
    )

    for index, code in enumerate(
        VENUE_CODES,
        start=1,
    ):

        print(
            f"{index}. {code}"
        )

    print()
    print(
        f"Total Cinepolis venues: "
        f"{len(VENUE_CODES)}"
    )

    if len(VENUE_CODES) != 7:

        raise RuntimeError(
            "VENUE_CODES must contain exactly "
            "the 7 confirmed Cinepolis venue codes."
        )

    # --------------------------------------------------------
    # Safety check
    # --------------------------------------------------------

    if "CSWO" in VENUE_CODES:

        raise RuntimeError(
            "CSWO must not be included in Cinepolis venues."
        )

    if len(set(VENUE_CODES)) != 7:

        raise RuntimeError(
            "Duplicate venue code detected."
        )

    # --------------------------------------------------------
    # Parser test
    # --------------------------------------------------------

    test_parser()

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

    worksheet = init_google_sheet()

    # --------------------------------------------------------
    # Process all 7 venues
    # --------------------------------------------------------

    summaries = []

    for index, venue_code in enumerate(
        VENUE_CODES,
        start=1,
    ):

        banner(
            f"CINEPOLIS VENUE {index}/7 : {venue_code}"
        )

        summary = process_venue(
            worksheet,
            venue_code,
        )

        summaries.append(
            summary
        )

        if index < len(VENUE_CODES):

            time.sleep(
                DELAY_BETWEEN_VENUES
            )

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    banner(
        "FINAL CINEPOLIS SUMMARY"
    )

    grand_shows = 0
    grand_successful = 0
    grand_failed = 0
    grand_available = 0
    grand_sold = 0
    grand_total = 0

    print()

    print(
        "VENUE       SHOWS    SUCCESS    FAILED    AVAILABLE    SOLD    TOTAL"
    )

    print(
        "-" * 80
    )

    for summary in summaries:

        grand_shows += summary["shows"]
        grand_successful += summary["successful"]
        grand_failed += summary["failed"]
        grand_available += summary["available"]
        grand_sold += summary["sold"]
        grand_total += summary["total"]

        print(
            f"{summary['venue']:<10} "
            f"{summary['shows']:>5} "
            f"{summary['successful']:>10} "
            f"{summary['failed']:>9} "
            f"{summary['available']:>12} "
            f"{summary['sold']:>8} "
            f"{summary['total']:>8}"
        )

    print(
        "-" * 80
    )

    print(
        f"{'TOTAL':<10} "
        f"{grand_shows:>5} "
        f"{grand_successful:>10} "
        f"{grand_failed:>9} "
        f"{grand_available:>12} "
        f"{grand_sold:>8} "
        f"{grand_total:>8}"
    )

    banner(
        "BMS TOXIC - CINEPOLIS TRACKER COMPLETED"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print("=" * 90)
        print("TRACKER FAILED")
        print("=" * 90)

        print(
            f"Error: {repr(error)}"
        )

        raise
