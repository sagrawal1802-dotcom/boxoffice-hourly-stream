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

# Known sessions for this movie / venue / date.
# These can later be replaced with automatic show discovery.
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

DELAY_BETWEEN_SHOWS = 15
PAGE_TIMEOUT = 60000
RENDER_WAIT = 8000


# ============================================================
# GOOGLE CREDENTIALS
# ============================================================

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
    "BMS State",
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
# UTILITY
# ============================================================

def banner(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


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
        scopes=scopes,
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
            cols=len(HEADERS),
        )

    existing = sheet.get_all_values()

    if not existing:
        sheet.append_row(
            HEADERS,
            value_input_option="USER_ENTERED",
        )
    else:
        current_headers = existing[0]
        if current_headers[:len(HEADERS)] != HEADERS:
            print("WARNING: Existing headers differ from current headers.")
            print("Current:", current_headers)
            print("Expected:", HEADERS)

    print("Google Sheets connected.")
    return sheet


# ============================================================
# SEAT TOKEN PARSER
#
# BMS examples:
# A1052+1   -> AVAILABLE, seat number 1
# A20515+9  -> SOLD, seat number 9
# B1042+2   -> AVAILABLE, seat number 2
# B2049+7   -> SOLD, seat number 7
#
# Important:
# The 1/2 immediately after A/B/C/D/E is the BMS state.
# The number AFTER + is the actual seat number.
# ============================================================

SEAT_TOKEN_RE = re.compile(
    r"^([A-E])([12])(\d+)\+(\d+)$"
)


def parse_seat_token(token):
    if not token:
        return None

    token = str(token).strip()

    # Empty/non-seat placeholders.
    if re.fullmatch(r"[A-E]0\+0", token):
        return None

    match = SEAT_TOKEN_RE.match(token)

    if not match:
        return None

    row_letter = match.group(1)
    state_code = match.group(2)
    seat_code_number = match.group(3)
    seat_number = match.group(4)

    seat_code = f"{row_letter}{state_code}{seat_code_number}"

    status = "AVAILABLE" if state_code == "1" else "SOLD"

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
        print(f"{token:<15} -> {result}")


# ============================================================
# CATEGORY
# ============================================================

def get_category_from_seat_code(seat_code):
    if not seat_code:
        return ""

    return CATEGORY_MAP.get(seat_code[0], "")


# ============================================================
# SEAT TOKEN EXTRACTION
#
# We first capture tokens from BMS network responses.
# HTML/JS scanning remains as a fallback.
# ============================================================

def extract_tokens_from_text(text):
    if not text:
        return []

    matches = re.findall(
        r"\b[A-E][12]\d+\+\d+\b",
        text,
    )

    seen = set()
    tokens = []

    for token in matches:
        if token not in seen:
            seen.add(token)
            tokens.append(token)

    return tokens


def extract_seat_tokens_from_html(page):
    try:
        html = page.content()
    except Exception:
        return []

    return extract_tokens_from_text(html)


# ============================================================
# NETWORK RESPONSE CAPTURE
# ============================================================

def install_response_capture(page, response_store):
    def handle_response(response):
        try:
            url = response.url.lower()

            # We are interested in BMS API / seat-layout responses.
            if (
                "seatlayout" not in url
                and "seat-layout" not in url
                and "movies-data" not in url
            ):
                return

            content_type = (
                response.headers.get("content-type", "").lower()
            )

            # JSON is preferred because it is cleaner than scanning HTML.
            if "json" in content_type:
                try:
                    body = response.text()
                    if body:
                        response_store.append(body)
                        print(
                            f"Captured BMS JSON response: "
                            f"{response.status} | {len(body)} bytes"
                        )
                except Exception:
                    pass
            else:
                # Some BMS responses can be text even when the header
                # is not explicitly JSON.
                try:
                    body = response.text()
                    if body and re.search(
                        r"[A-E][12]\d+\+\d+",
                        body,
                    ):
                        response_store.append(body)
                        print(
                            f"Captured BMS seat response: "
                            f"{response.status} | {len(body)} bytes"
                        )
                except Exception:
                    pass

        except Exception:
            pass

    page.on("response", handle_response)


# ============================================================
# PROCESS JSON / TEXT RESPONSE
#
# We deliberately search the captured response text for the
# exact BMS seat-token format. This avoids depending on an
# undocumented JSON key name.
# ============================================================

def tokens_from_captured_responses(response_store):
    seen = set()
    tokens = []

    for body in response_store:
        for token in extract_tokens_from_text(body):
            if token not in seen:
                seen.add(token)
                tokens.append(token)

    return tokens


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

    captured_responses = []
    install_response_capture(page, captured_responses)

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=PAGE_TIMEOUT,
        )

        if response:
            print(
                f"Initial HTTP status: {response.status}"
            )

    except Exception as error:
        print(f"Page navigation error: {error}")
        return []

    # Allow the BMS page/API calls to finish.
    print("Waiting for BMS seat layout...")
    try:
        page.wait_for_timeout(RENDER_WAIT)
    except Exception:
        pass

    # Give the browser a short opportunity to receive late API calls.
    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=15000,
        )
    except Exception:
        pass

    # Network responses are preferred.
    tokens = tokens_from_captured_responses(
        captured_responses
    )

    print(
        f"Seat tokens captured from network: {len(tokens)}"
    )

    # Fallback only if network capture did not find seats.
    if not tokens:
        print("No network seat tokens found.")
        print("Falling back to rendered page extraction...")
        tokens = extract_seat_tokens_from_html(page)

    print(
        f"Final potential seat tokens: {len(tokens)}"
    )

    parsed_rows = []

    for token in tokens:
        parsed = parse_seat_token(token)

        if not parsed:
            continue

        category = get_category_from_seat_code(
            parsed["seat_code"]
        )

        # The current BMS token contains the A/B/C/D/E seat family.
        # Exact row names/numbers can be enriched later if required.
        row_number = ""
        row_name = parsed["row_letter"]
        category_code = parsed["row_letter"]

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
            category_code,
            category,
            parsed["seat_token"],
            parsed["seat_code"],
            parsed["seat_number"],
            parsed["status"],
        ])

    # ========================================================
    # DEDUPLICATION
    #
    # HEADERS:
    # 0 Timestamp
    # 1 Event
    # 2 Venue
    # 3 Session
    # 4 Show Time
    # 5 Date
    # 6 City
    # 7 Row Number
    # 8 Row Name
    # 9 Category Code
    # 10 Category
    # 11 Seat Token
    # 12 Seat Code
    # 13 Seat Number
    # 14 BMS State
    #
    # Therefore row[11] IS the seat token.
    # ========================================================

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

    banner("SHOW SUMMARY")
    print(f"Session    : {session_id}")
    print(f"Show       : {show_time}")
    print(f"Available  : {available}")
    print(f"Sold       : {sold}")
    print(f"Total      : {len(parsed_rows)}")

    return parsed_rows


# ============================================================
# WRITE ALL SHOWS IN ONE BATCH
# ============================================================

def write_rows(sheet, rows):
    if not rows:
        print("No rows to write.")
        return

    banner("WRITING ALL SHOWS TO GOOGLE SHEETS")

    try:
        sheet.append_rows(
            rows,
            value_input_option="USER_ENTERED",
        )

        print(
            f"Written {len(rows)} rows in one batch."
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

    print(f"Timestamp : {get_ist_timestamp()}")
    print(f"Event     : {EVENT_CODE}")
    print(f"Venue     : {VENUE_CODE}")
    print(f"Date      : {SHOW_DATE}")
    print(f"City      : {CITY}")
    print(f"Shows     : {len(KNOWN_SHOWS)}")

    test_parser()

    sheet = init_google_sheet()

    all_rows = []
    successful_shows = 0
    failed_shows = 0

    with sync_playwright() as p:

        print()
        print("Launching Chromium...")

        # Do NOT force a synthetic Chrome version.
        # Playwright uses the installed browser's real UA.
        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        for index, (show_time, session_id) in enumerate(
            KNOWN_SHOWS,
            start=1,
        ):

            print()
            print(
                f"SHOW {index}/{len(KNOWN_SHOWS)}"
            )

            try:
                rows = process_show(
                    page,
                    show_time,
                    session_id,
                )

                if rows:
                    all_rows.extend(rows)
                    successful_shows += 1
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

            if index < len(KNOWN_SHOWS):
                print()
                print(
                    f"Waiting {DELAY_BETWEEN_SHOWS} seconds "
                    f"before next show..."
                )
                time.sleep(DELAY_BETWEEN_SHOWS)

        context.close()
        browser.close()

    # One Google Sheets write after all shows.
    if all_rows:
        write_rows(sheet, all_rows)

    banner("TRACKING COMPLETED")

    print(
        f"Successful shows : {successful_shows}"
    )
    print(
        f"Failed shows     : {failed_shows}"
    )
    print(
        f"Total seat rows   : {len(all_rows)}"
    )
    print(
        f"Timestamp         : {get_ist_timestamp()}"
    )


if __name__ == "__main__":
    main()
