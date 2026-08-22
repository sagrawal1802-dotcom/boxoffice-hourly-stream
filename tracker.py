import os
import re
import json
import base64
import time
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

SHEET_TAB_NAME = "SeatLog"

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SHOW_DATE = "20260826"
CITY = "mumbai"

DELAY_BETWEEN_SHOWS = 3

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)

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

CATEGORY_MAP = {
    "A": "RECLINER",
    "B": "PREMIUM",
    "C": "EXECUTIVE XL",
    "D": "EXECUTIVE",
    "E": "NORMAL",
}


# ============================================================
# UTILITIES
# ============================================================

def banner(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def get_ist_timestamp():
    tz = pytz.timezone("Asia/Kolkata")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def init_google_sheet():
    banner("CONNECTING TO GOOGLE SHEETS")

    if not GCP_SA_KEY:
        raise ValueError("Missing GCP_SA_KEY_B64 or GCP_SA_KEY environment variable.")

    raw_key = GCP_SA_KEY.strip()

    try:
        if raw_key.startswith("{"):
            service_account_info = json.loads(raw_key)
        else:
            decoded = base64.b64decode(raw_key).decode("utf-8")
            service_account_info = json.loads(decoded)
    except Exception as error:
        raise ValueError(f"Could not decode Google credentials: {error}")

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
        sheet = spreadsheet.add_worksheet(title=SHEET_TAB_NAME, rows=50000, cols=len(HEADERS))

    existing = sheet.get_all_values()
    if not existing:
        print("Adding headers...")
        sheet.append_row(HEADERS, value_input_option="USER_ENTERED")

    print("Google Sheets connected.")
    return sheet


def write_rows_in_batches(sheet, rows, batch_size=2500):
    if not rows:
        print("No rows to write.")
        return

    banner("WRITING TO GOOGLE SHEETS")
    total = len(rows)
    for i in range(0, total, batch_size):
        chunk = rows[i:i + batch_size]
        sheet.append_rows(chunk, value_input_option="USER_ENTERED")
        print(f"Appended rows {i + 1} to {min(i + batch_size, total)}")
        time.sleep(1)


# ============================================================
# SHOW PROCESSOR WITH TLS IMPERSONATION
# ============================================================

def process_show(session, show_time, session_id):
    banner(f"PROCESSING SHOW {show_time} | SESSION {session_id}")

    url = (
        f"https://in.bookmyshow.com/movies/"
        f"{CITY}/seat-layout/"
        f"{EVENT_CODE}/"
        f"{VENUE_CODE}/"
        f"{session_id}/"
        f"{SHOW_DATE}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Referer": f"https://in.bookmyshow.com/buytickets/{EVENT_CODE}-{CITY}/movie-{CITY}-{EVENT_CODE}-MT/{SHOW_DATE}",
    }

    try:
        response = session.get(url, headers=headers, impersonate="chrome124", timeout=30)
        print(f"HTTP Status: {response.status_code}")

        if response.status_code != 200:
            print(f"Failed to fetch page. Status: {response.status_code}")
            return []

    except Exception as error:
        print(f"Request error: {error}")
        return []

    # Extract tokens from the server-rendered HTML/state script
    html_content = response.text
    matches = re.findall(r"\b[A-E][12]\d+\+\d+\b", html_content)
    tokens = list(dict.fromkeys(matches))

    print(f"Extracted potential seat tokens: {len(tokens)}")

    timestamp = get_ist_timestamp()
    unique_rows = {}

    for token in tokens:
        if token in ("A0+0", "B0+0", "C0+0", "D0+0", "E0+0"):
            continue

        match = re.match(r"^([A-E])([12])(\d+)\+(\d+)$", token)
        if not match:
            continue

        row_letter, state_code, seat_code_num, seat_num = match.groups()
        seat_code = f"{row_letter}{state_code}{seat_code_num}"
        status = "AVAILABLE" if state_code == "1" else "SOLD"
        category = CATEGORY_MAP.get(row_letter, "")

        row = [
            timestamp,
            EVENT_CODE,
            VENUE_CODE,
            session_id,
            show_time,
            SHOW_DATE,
            CITY,
            "",
            row_letter,
            row_letter,
            category,
            token,
            seat_code,
            seat_num,
            status,
        ]
        unique_rows[(session_id, seat_code)] = row

    parsed_rows = list(unique_rows.values())
    available = sum(1 for r in parsed_rows if r[14] == "AVAILABLE")
    sold = sum(1 for r in parsed_rows if r[14] == "SOLD")

    print("\nSHOW SUMMARY")
    print("-" * 50)
    print(f"Session    : {session_id}")
    print(f"Available  : {available}")
    print(f"Sold       : {sold}")
    print(f"Total Seats: {len(parsed_rows)}")

    return parsed_rows


# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

def main():
    banner("BMS VENUE ALL-SHOW TRACKER")
    sheet = init_google_sheet()
    all_rows = []
    successful_shows = 0
    failed_shows = 0

    session = requests.Session()

    # Pre-warm cookies using browser TLS fingerprint
    try:
        home_url = f"https://in.bookmyshow.com/explore/movies-{CITY}"
        session.get(home_url, impersonate="chrome124", timeout=20)
    except Exception as e:
        print(f"Session warm-up notice: {e}")

    for index, (show_time, session_id) in enumerate(KNOWN_SHOWS, start=1):
        print(f"\nSHOW {index}/{len(KNOWN_SHOWS)}")
        try:
            rows = process_show(session, show_time, session_id)
            if rows:
                all_rows.extend(rows)
                successful_shows += 1
            else:
                failed_shows += 1
        except Exception as error:
            print(f"FAILED SHOW {session_id}: {error}")
            failed_shows += 1

        if index < len(KNOWN_SHOWS):
            time.sleep(DELAY_BETWEEN_SHOWS)

    if all_rows:
        write_rows_in_batches(sheet, all_rows)

    banner("TRACKING COMPLETED")
    print(f"Successful shows : {successful_shows}")
    print(f"Failed shows     : {failed_shows}")
    print(f"Total seat rows  : {len(all_rows)}")
    print(f"Timestamp        : {get_ist_timestamp()}")


if __name__ == "__main__":
    main()
