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

SHEET_TAB_NAME = "Toxic_CSWO"

CITY = "mumbai"
VENUE_CODE = "CSWO"
SHOW_DATE = "20260826"

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"

# Delay between BMS seat-layout requests.
# Keep this reasonably slow.
DELAY_BETWEEN_SHOWS = 8

# Number of attempts for each seat layout
MAX_ATTEMPTS = 3

# Google Sheets batch size
GOOGLE_BATCH_SIZE = 500


# ============================================================
# ALL 23 CSWO SHOWS
#
# Discovered from BMS showtime data.
#
# 14 Hindi 2D
# 5 IMAX
# 4 4DX
# ============================================================

SHOWS = [

    # --------------------------------------------------------
    # Hindi 2D
    # Event: ET00379311
    # --------------------------------------------------------

    {
        "format": "Hindi 2D",
        "show_time": "01:05 PM",
        "event_code": "ET00379311",
        "session_id": "16073",
    },

    {
        "format": "Hindi 2D",
        "show_time": "02:45 PM",
        "event_code": "ET00379311",
        "session_id": "15927",
    },

    {
        "format": "Hindi 2D",
        "show_time": "03:45 PM",
        "event_code": "ET00379311",
        "session_id": "15932",
    },

    {
        "format": "Hindi 2D",
        "show_time": "05:10 PM",
        "event_code": "ET00379311",
        "session_id": "16074",
    },

    {
        "format": "Hindi 2D",
        "show_time": "06:50 PM",
        "event_code": "ET00379311",
        "session_id": "15928",
    },

    {
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "15925",
    },

    {
        "format": "Hindi 2D",
        "show_time": "07:50 PM",
        "event_code": "ET00379311",
        "session_id": "15931",
    },

    {
        "format": "Hindi 2D",
        "show_time": "08:00 AM",
        "event_code": "ET00379311",
        "session_id": "15934",
    },

    {
        "format": "Hindi 2D",
        "show_time": "09:00 AM",
        "event_code": "ET00379311",
        "session_id": "16072",
    },

    {
        "format": "Hindi 2D",
        "show_time": "09:15 PM",
        "event_code": "ET00379311",
        "session_id": "16075",
    },

    {
        "format": "Hindi 2D",
        "show_time": "10:40 AM",
        "event_code": "ET00379311",
        "session_id": "15926",
    },

    {
        "format": "Hindi 2D",
        "show_time": "10:55 PM",
        "event_code": "ET00379311",
        "session_id": "15929",
    },

    {
        "format": "Hindi 2D",
        "show_time": "11:40 AM",
        "event_code": "ET00379311",
        "session_id": "15933",
    },

    {
        "format": "Hindi 2D",
        "show_time": "11:55 PM",
        "event_code": "ET00379311",
        "session_id": "15930",
    },


    # --------------------------------------------------------
    # IMAX
    # Event: ET00513458
    # --------------------------------------------------------

    {
        "format": "IMAX",
        "show_time": "03:15 PM",
        "event_code": "ET00513458",
        "session_id": "16007",
    },

    {
        "format": "IMAX",
        "show_time": "07:20 PM",
        "event_code": "ET00513458",
        "session_id": "16008",
    },

    {
        "format": "IMAX",
        "show_time": "07:30 AM",
        "event_code": "ET00513458",
        "session_id": "16005",
    },

    {
        "format": "IMAX",
        "show_time": "11:10 AM",
        "event_code": "ET00513458",
        "session_id": "16006",
    },

    {
        "format": "IMAX",
        "show_time": "11:25 PM",
        "event_code": "ET00513458",
        "session_id": "16009",
    },


    # --------------------------------------------------------
    # 4DX
    # Event: ET00513506
    # --------------------------------------------------------

    {
        "format": "4DX",
        "show_time": "03:30 PM",
        "event_code": "ET00513506",
        "session_id": "16021",
    },

    {
        "format": "4DX",
        "show_time": "07:35 PM",
        "event_code": "ET00513506",
        "session_id": "16024",
    },

    {
        "format": "4DX",
        "show_time": "07:45 AM",
        "event_code": "ET00513506",
        "session_id": "16020",
    },

    {
        "format": "4DX",
        "show_time": "11:40 PM",
        "event_code": "ET00513506",
        "session_id": "16023",
    },
]


# ============================================================
# GOOGLE SHEET HEADERS
# ============================================================

HEADERS = [
    "Timestamp IST",
    "Movie",
    "Event Code",
    "Venue Code",
    "Session ID",
    "Format",
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
# GOOGLE CREDENTIALS
# ============================================================

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)


# ============================================================
# CATEGORY FALLBACK
# ============================================================

CATEGORY_FALLBACK = {
    "A": "RECLINER",
    "B": "PREMIUM",
    "C": "EXECUTIVE XL",
    "D": "EXECUTIVE",
    "E": "NORMAL",
}


# ============================================================
# PRINT HELPERS
# ============================================================

def banner(title):
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


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

        print(f"Creating worksheet: {SHEET_TAB_NAME}")

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=50000,
            cols=len(HEADERS)
        )

    existing = sheet.get_all_values()

    if not existing:

        print("Sheet empty. Adding headers.")

        sheet.update(
            range_name="A1",
            values=[HEADERS]
        )

    else:

        current_headers = existing[0]

        if current_headers[:len(HEADERS)] != HEADERS:

            print()
            print("WARNING: Existing headers differ.")
            print("Current:")
            print(current_headers)
            print()
            print("Expected:")
            print(HEADERS)
            print()

    print("Google Sheets connected.")

    return sheet


# ============================================================
# BMS SEAT LAYOUT REQUEST
#
# This is the endpoint used by the previously successful
# tracker. It returns BookMyShow.strData.
# ============================================================

def get_seat_layout(show):

    event_code = show["event_code"]
    session_id = show["session_id"]
    show_time = show["show_time"]
    show_format = show["format"]

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
            f"{event_code}/{VENUE_CODE}/"
            f"{session_id}/{SHOW_DATE}"
        ),
    }

    print()
    print("-" * 90)
    print(
        f"SEAT LAYOUT | {show_format} | "
        f"{show_time} | Session {session_id}"
    )
    print("-" * 90)

    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:

            print(f"Attempt {attempt}/{MAX_ATTEMPTS}")

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                impersonate="chrome120",
                timeout=30,
            )

            print(f"HTTP status: {response.status_code}")
            print(f"Response size: {len(response.content)} bytes")

            if response.status_code != 200:

                print("BMS request failed.")

                if attempt < MAX_ATTEMPTS:
                    time.sleep(4)

                continue

            # ------------------------------------------------
            # BMS normally returns JSON.
            # Sometimes the body can have leading whitespace.
            # ------------------------------------------------

            try:

                data = response.json()

            except Exception:

                text = response.text.strip()

                print("JSON decoding failed.")

                print("Response preview:")
                print(text[:1000])

                if attempt < MAX_ATTEMPTS:
                    time.sleep(4)

                continue

            bookmyshow = data.get("BookMyShow", {})

            success = bookmyshow.get("blnSuccess")

            print(f"blnSuccess : {success}")
            print(
                f"intException : "
                f"{bookmyshow.get('intException')}"
            )

            if bookmyshow.get("strException"):
                print(
                    f"strException : "
                    f"{bookmyshow.get('strException')}"
                )

            str_data = bookmyshow.get("strData")

            if not str_data:

                print("No strData returned by BMS.")

                if attempt < MAX_ATTEMPTS:
                    time.sleep(4)

                continue

            print(f"strData length : {len(str_data)}")

            return str_data

        except Exception as error:

            print(f"Request error: {repr(error)}")

            if attempt < MAX_ATTEMPTS:
                time.sleep(4)

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
#
# Examples:
#
# B1048+6  = AVAILABLE
# B2049+7  = SOLD
#
# The first digit of the numeric seat code:
#
# 1 = AVAILABLE
# 2 = SOLD
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

    seat_code = f"{letter}{numeric_code}"

    # A0+0 / B0+0 etc. are not physical seats.
    if numeric_code == "0":
        return None

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
# PARSE BMS strData
# ============================================================

def parse_seat_rows(str_data, show):

    event_code = show["event_code"]
    session_id = show["session_id"]
    show_time = show["show_time"]
    show_format = show["format"]

    timestamp = get_ist_timestamp()

    # --------------------------------------------------------
    # BMS format:
    #
    # category section || seat section
    # --------------------------------------------------------

    sections = str_data.split("||", 1)

    if len(sections) != 2:

        print("ERROR: Could not split BMS strData.")

        print("strData preview:")
        print(str_data[:2000])

        return []

    category_section = sections[0]

    seat_section = sections[1]

    categories = parse_categories(category_section)

    # --------------------------------------------------------
    # If category section does not provide useful names,
    # use known fallback categories.
    # --------------------------------------------------------

    for code, name in CATEGORY_FALLBACK.items():

        if code not in categories:
            categories[code] = name

    print()
    print("CATEGORY MAP")

    for code, name in categories.items():

        print(f"{code} -> {name}")

    print()

    raw_rows = seat_section.split("|")

    results = []

    available_count = 0
    sold_count = 0

    # --------------------------------------------------------
    # Process each physical row
    # --------------------------------------------------------

    for raw_row in raw_rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        # Expected:
        #
        # 1:M:A000:A0+0:A1052+1:A1053+2...
        #
        # Split only first 3 colons.
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

        # Seats are separated by :
        seat_tokens = seat_data.split(":")

        for token in seat_tokens:

            token = token.strip()

            if not token:
                continue

            parsed = parse_seat_token(token)

            if parsed is None:
                continue

            bms_state = parsed["bms_state"]

            if bms_state == "AVAILABLE":

                available_count += 1

            elif bms_state == "SOLD":

                sold_count += 1

            results.append([
                timestamp,
                MOVIE_NAME,
                event_code,
                VENUE_CODE,
                session_id,
                show_format,
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
                bms_state,
            ])

    print()
    print("=" * 90)
    print("SHOW SUMMARY")
    print("=" * 90)

    print(f"Format     : {show_format}")
    print(f"Show       : {show_time}")
    print(f"Event      : {event_code}")
    print(f"Session    : {session_id}")
    print(f"Available  : {available_count}")
    print(f"Sold       : {sold_count}")
    print(f"Total      : {available_count + sold_count}")

    print("=" * 90)

    return results


# ============================================================
# PRINT SAMPLE
# ============================================================

def print_sample(rows):

    if not rows:
        return

    print()
    print("=" * 120)
    print("SEAT SAMPLE")
    print("=" * 120)

    print(
        "Format | Show Time | Session | Row | "
        "Category | Seat Token | Seat Code | Seat No | Status"
    )

    print("-" * 120)

    for row in rows[:20]:

        print(
            f"{row[5]} | "
            f"{row[6]} | "
            f"{row[4]} | "
            f"{row[9]} | "
            f"{row[12]} | "
            f"{row[13]} | "
            f"{row[14]} | "
            f"{row[15]} | "
            f"{row[16]}"
        )

    print("-" * 120)


# ============================================================
# GOOGLE SHEETS BATCH WRITE
# ============================================================

def write_to_sheet(sheet, rows):

    if not rows:

        print()
        print("No seat records to write.")

        return

    banner("WRITING ALL SEATS TO GOOGLE SHEETS")

    total = len(rows)

    print(f"Total seat records: {total}")

    for start in range(0, total, GOOGLE_BATCH_SIZE):

        batch = rows[
            start:start + GOOGLE_BATCH_SIZE
        ]

        end = start + len(batch)

        print(
            f"Writing rows "
            f"{start + 1}-{end} / {total}"
        )

        sheet.append_rows(
            batch,
            value_input_option="USER_ENTERED"
        )

    print()
    print(
        f"Google Sheet updated successfully. "
        f"{total} seat records written."
    )


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
# SHOW DISCOVERY DISPLAY
# ============================================================

def print_show_list():

    banner("CSWO SHOW LIST")

    for index, show in enumerate(SHOWS, start=1):

        print(
            f"{index:02d}. "
            f"{show['format']:<12} | "
            f"{show['show_time']:<9} | "
            f"{show['event_code']} | "
            f"Session {show['session_id']}"
        )

    print()
    print(f"TOTAL SHOWS: {len(SHOWS)}")

    format_counts = {}

    for show in SHOWS:

        fmt = show["format"]

        format_counts[fmt] = (
            format_counts.get(fmt, 0) + 1
        )

    print()

    for fmt, count in format_counts.items():

        print(
            f"{fmt}: {count} shows"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    banner("BMS TOXIC CSWO ALL-SHOW SEAT TRACKER")

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
        f"Venue     : {VENUE_CODE}"
    )

    print(
        f"Date      : {SHOW_DATE}"
    )

    print(
        f"Shows     : {len(SHOWS)}"
    )

    print_show_list()

    test_parser()

    # --------------------------------------------------------
    # Google Sheets
    # --------------------------------------------------------

    sheet = init_google_sheet()

    # --------------------------------------------------------
    # Process every show
    # --------------------------------------------------------

    all_rows = []

    successful_shows = 0

    failed_shows = 0

    show_summaries = []

    for index, show in enumerate(
        SHOWS,
        start=1
    ):

        banner(
            f"SHOW {index}/{len(SHOWS)}"
        )

        print(
            f"Format     : {show['format']}"
        )

        print(
            f"Show Time  : {show['show_time']}"
        )

        print(
            f"Event Code : {show['event_code']}"
        )

        print(
            f"Session ID : {show['session_id']}"
        )

        # ----------------------------------------------------
        # Request BMS seat layout
        # ----------------------------------------------------

        str_data = get_seat_layout(show)

        if not str_data:

            print()
            print(
                f"FAILED: No seat layout for "
                f"session {show['session_id']}"
            )

            failed_shows += 1

            show_summaries.append({
                "format": show["format"],
                "show_time": show["show_time"],
                "session_id": show["session_id"],
                "available": 0,
                "sold": 0,
                "total": 0,
                "status": "FAILED",
            })

        else:

            # ------------------------------------------------
            # Parse seats
            # ------------------------------------------------

            rows = parse_seat_rows(
                str_data,
                show
            )

            if rows:

                successful_shows += 1

                all_rows.extend(rows)

                available = sum(
                    1
                    for row in rows
                    if row[16] == "AVAILABLE"
                )

                sold = sum(
                    1
                    for row in rows
                    if row[16] == "SOLD"
                )

                show_summaries.append({
                    "format": show["format"],
                    "show_time": show["show_time"],
                    "session_id": show["session_id"],
                    "available": available,
                    "sold": sold,
                    "total": len(rows),
                    "status": "OK",
                })

                print_sample(rows)

            else:

                print(
                    "WARNING: BMS returned strData "
                    "but no seats were parsed."
                )

                failed_shows += 1

                show_summaries.append({
                    "format": show["format"],
                    "show_time": show["show_time"],
                    "session_id": show["session_id"],
                    "available": 0,
                    "sold": 0,
                    "total": 0,
                    "status": "NO SEATS",
                })

        # ----------------------------------------------------
        # Delay before next BMS request
        # ----------------------------------------------------

        if index < len(SHOWS):

            print()
            print(
                f"Waiting {DELAY_BETWEEN_SHOWS} seconds "
                f"before next show..."
            )

            time.sleep(DELAY_BETWEEN_SHOWS)

    # --------------------------------------------------------
    # WRITE EVERYTHING AT ONCE
    # --------------------------------------------------------

    write_to_sheet(
        sheet,
        all_rows
    )

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    banner("FINAL CSWO SUMMARY")

    print(
        f"Shows discovered : {len(SHOWS)}"
    )

    print(
        f"Successful shows : {successful_shows}"
    )

    print(
        f"Failed shows     : {failed_shows}"
    )

    print(
        f"Seat records     : {len(all_rows)}"
    )

    print()

    print(
        "FORMAT       SHOWS     AVAILABLE     SOLD      TOTAL"
    )

    print("-" * 70)

    format_totals = {}

    for summary in show_summaries:

        fmt = summary["format"]

        if fmt not in format_totals:

            format_totals[fmt] = {
                "shows": 0,
                "available": 0,
                "sold": 0,
                "total": 0,
            }

        format_totals[fmt]["shows"] += 1

        format_totals[fmt]["available"] += (
            summary["available"]
        )

        format_totals[fmt]["sold"] += (
            summary["sold"]
        )

        format_totals[fmt]["total"] += (
            summary["total"]
        )

    for fmt, values in format_totals.items():

        print(
            f"{fmt:<12} "
            f"{values['shows']:>5} "
            f"{values['available']:>13} "
            f"{values['sold']:>9} "
            f"{values['total']:>10}"
        )

    print()

    print(
        "SHOW-BY-SHOW"
    )

    print("-" * 90)

    for summary in show_summaries:

        print(
            f"{summary['format']:<12} | "
            f"{summary['show_time']:<9} | "
            f"{summary['session_id']:<6} | "
            f"Available {summary['available']:<4} | "
            f"Sold {summary['sold']:<4} | "
            f"Total {summary['total']:<4} | "
            f"{summary['status']}"
        )

    banner(
        "BMS TOXIC CSWO ALL-SHOW TRACKER COMPLETED"
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
