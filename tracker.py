import os
import re
import json
import time
from datetime import datetime

import gspread
import pytz
from google.oauth2.service_account import Credentials
from curl_cffi import requests


# ============================================================
# CONFIGURATION
# ============================================================

EVENT_CODE = os.getenv("EVENT_CODE", "ET00379311")
VENUE_CODE = os.getenv("VENUE_CODE", "CSWO")
SHOW_DATE = os.getenv("SHOW_DATE", "20260826")
CITY = os.getenv("CITY", "mumbai")
REGION_CODE = os.getenv("REGION_CODE", "MUMBAI")

SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "BMS Seats")

IST = pytz.timezone("Asia/Kolkata")


# ============================================================
# GOOGLE SHEET HEADERS
# ============================================================

SEAT_HEADERS = [
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
    "Price",
    "Sold Gross",
]

SUMMARY_HEADERS = [
    "Timestamp IST",
    "Event Code",
    "Venue Code",
    "Session ID",
    "Show Time",
    "Date",
    "City",
    "Category",
    "Price",
    "Available",
    "Sold",
    "Total Seats",
    "Occupancy %",
    "Gross",
]


# ============================================================
# BMS HEADERS
# ============================================================

def build_headers():

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://in.bookmyshow.com",
        "Referer": (
            f"https://in.bookmyshow.com/"
            f"movies/{CITY}/seat-layout/"
            f"{EVENT_CODE}/{VENUE_CODE}/{SHOW_DATE}"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
        "Connection": "keep-alive",
    }


# ============================================================
# BMS PRIMARY SEAT-LAYOUT URL
# ============================================================

def build_url():

    return (
        "https://in.bookmyshow.com/"
        "api/movies-data/seatlayout/v1/primary"
        f"?eventCode={EVENT_CODE}"
        f"&dateCode={SHOW_DATE}"
        f"&regionCode={REGION_CODE}"
        f"&venueCode={VENUE_CODE}"
    )


# ============================================================
# REQUEST BMS
# ============================================================

def request_bms():

    url = build_url()
    headers = build_headers()

    print("=" * 70)
    print("BMS VENUE-LEVEL REQUEST")
    print("=" * 70)
    print(url)

    for attempt in range(1, 4):

        print(f"\nAttempt {attempt}/3")

        try:

            response = requests.get(
                url,
                headers=headers,
                impersonate="chrome120",
                timeout=30,
            )

            print("HTTP status:", response.status_code)
            print("Response size:", len(response.content))

            if response.status_code != 200:

                print("Response preview:")
                print(response.text[:2000])

                if attempt < 3:
                    time.sleep(2 * attempt)

                continue

            try:
                data = response.json()
            except Exception:

                print("Could not decode JSON.")
                print(response.text[:3000])

                if attempt < 3:
                    time.sleep(2 * attempt)

                continue

            return data

        except Exception as e:

            print("REQUEST ERROR:")
            print(repr(e))

            if attempt < 3:
                time.sleep(2 * attempt)

    return None


# ============================================================
# GET BOOKMYSHOW OBJECT
# ============================================================

def get_bookmyshow(data):

    if not isinstance(data, dict):
        return {}

    if "BookMyShow" in data:
        return data["BookMyShow"]

    return data


# ============================================================
# FIND STRDATA RECURSIVELY
# ============================================================

def find_strdata(obj):

    if isinstance(obj, dict):

        if "strData" in obj and isinstance(obj["strData"], str):
            return obj["strData"]

        for value in obj.values():

            result = find_strdata(value)

            if result:
                return result

    elif isinstance(obj, list):

        for value in obj:

            result = find_strdata(value)

            if result:
                return result

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
# B1042+6
#
# B1042 = seat code
# 6     = actual seat number
#
# B1048 = AVAILABLE
# B2049 = SOLD
#
# 10xxx -> AVAILABLE
# 20xxx -> SOLD
# ============================================================

def parse_seat_token(token):

    token = token.strip()

    if not token:
        return None

    match = re.match(
        r"^([A-Z])([12])(\d+)\+(\d+)$",
        token
    )

    if not match:
        return None

    row_letter = match.group(1)
    state_prefix = match.group(2)
    seat_body = match.group(3)
    seat_number = match.group(4)

    seat_code = (
        row_letter +
        state_prefix +
        seat_body
    )

    if state_prefix == "1":
        status = "AVAILABLE"
    elif state_prefix == "2":
        status = "SOLD"
    else:
        status = "UNKNOWN"

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": seat_number,
        "status": status,
        "row_letter": row_letter,
    }


# ============================================================
# PARSE BMS ROWS
#
# Example:
#
# 1:M:A000:
# A0+0:
# A1052+1:
# A1053+2:
# ...
#
# The number after + is the actual seat number.
# ============================================================

def parse_seat_rows(str_data):

    if not str_data:
        return []

    sections = str_data.split("||", 1)

    if len(sections) != 2:

        print("Could not split BMS category section from seat section.")

        return []

    category_section = sections[0]
    seat_section = sections[1]

    categories = parse_categories(category_section)

    print()
    print("CATEGORY MAP")
    print("=" * 70)

    for code, name in categories.items():
        print(f"{code} -> {name}")

    results = []

    raw_rows = seat_section.split("|")

    for raw_row in raw_rows:

        raw_row = raw_row.strip()

        if not raw_row:
            continue

        parts = raw_row.split(":")

        if len(parts) < 4:
            continue

        row_number = parts[0].strip()
        row_name = parts[1].strip()
        category_code = parts[2].strip()

        category_name = categories.get(
            category_code,
            category_code
        )

        # Everything after the first 3 fields is seat data.
        seat_tokens = parts[3:]

        for token in seat_tokens:

            token = token.strip()

            if not token:
                continue

            parsed = parse_seat_token(token)

            if not parsed:
                continue

            results.append({
                "row_number": row_number,
                "row_name": row_name,
                "category_code": category_code,
                "category": category_name,
                "seat_token": parsed["seat_token"],
                "seat_code": parsed["seat_code"],
                "seat_number": parsed["seat_number"],
                "status": parsed["status"],
            })

    return results


# ============================================================
# RECURSIVELY FIND SHOW / SESSION INFORMATION
# ============================================================

def find_sessions(obj):

    sessions = []

    if isinstance(obj, dict):

        # Common BMS naming possibilities
        possible_id_keys = [
            "sessionId",
            "sessionID",
            "session_id",
            "SessionId",
            "SessionID",
            "sessionCode",
            "sessioncode",
        ]

        possible_time_keys = [
            "showTime",
            "showtime",
            "show_time",
            "ShowTime",
            "time",
            "sessionTime",
            "sessiontime",
        ]

        session_id = None
        show_time = None

        for key in possible_id_keys:

            if key in obj and obj[key] not in (None, ""):
                session_id = str(obj[key])
                break

        for key in possible_time_keys:

            if key in obj and obj[key] not in (None, ""):
                show_time = str(obj[key])
                break

        if session_id:

            sessions.append({
                "session_id": session_id,
                "show_time": show_time or "",
            })

        for value in obj.values():

            sessions.extend(find_sessions(value))

    elif isinstance(obj, list):

        for value in obj:
            sessions.extend(find_sessions(value))

    return sessions


# ============================================================
# DEDUPLICATE SESSIONS
# ============================================================

def dedupe_sessions(sessions):

    output = {}

    for session in sessions:

        sid = str(session.get("session_id", "")).strip()

        if not sid:
            continue

        if sid not in output:

            output[sid] = session

        else:

            if (
                not output[sid].get("show_time")
                and session.get("show_time")
            ):
                output[sid]["show_time"] = session["show_time"]

    return list(output.values())


# ============================================================
# EXTRACT SHOWS FROM RESPONSE
# ============================================================

def extract_shows(data):

    sessions = find_sessions(data)

    sessions = dedupe_sessions(sessions)

    return sessions


# ============================================================
# PRICE EXTRACTION
#
# This handles several possible BMS structures.
# ============================================================

def extract_prices(obj):

    prices = {}

    def walk(value):

        if isinstance(value, dict):

            # category + price style objects
            category = None
            price = None

            for key in [
                "category",
                "categoryName",
                "category_name",
                "name",
                "description",
            ]:
                if key in value and isinstance(value[key], str):
                    category = value[key].strip()
                    break

            for key in [
                "price",
                "amount",
                "ticketPrice",
                "ticket_price",
                "basePrice",
            ]:
                if key in value:
                    try:
                        price = float(value[key])
                        break
                    except Exception:
                        pass

            if category and price is not None:

                category_upper = category.upper()

                known_categories = [
                    "RECLINER",
                    "PREMIUM",
                    "EXECUTIVE XL",
                    "EXECUTIVE",
                    "NORMAL",
                ]

                for known in known_categories:

                    if known in category_upper:

                        prices[known] = price

            # Sometimes BMS uses categoryCode
            category_code = value.get("categoryCode")

            if category_code and price is not None:

                code_map = {
                    "A": "RECLINER",
                    "B": "PREMIUM",
                    "C": "EXECUTIVE XL",
                    "D": "EXECUTIVE",
                    "E": "NORMAL",
                }

                if str(category_code) in code_map:

                    prices[
                        code_map[str(category_code)]
                    ] = price

            for child in value.values():
                walk(child)

        elif isinstance(value, list):

            for child in value:
                walk(child)

    walk(obj)

    return prices


# ============================================================
# GOOGLE AUTH
# ============================================================

def get_google_credentials():

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # Preferred GitHub Actions secret
    b64_key = os.getenv("GCP_SA_KEY_B64")

    if b64_key:

        import base64

        try:

            decoded = base64.b64decode(b64_key).decode("utf-8")
            info = json.loads(decoded)

            return Credentials.from_service_account_info(
                info,
                scopes=scopes
            )

        except Exception as e:

            print("GCP_SA_KEY_B64 failed:")
            print(repr(e))

    # JSON secret
    raw_key = os.getenv("GCP_SA_KEY")

    if raw_key:

        try:

            info = json.loads(raw_key)

            return Credentials.from_service_account_info(
                info,
                scopes=scopes
            )

        except Exception as e:

            print("GCP_SA_KEY failed:")
            print(repr(e))

    # Local development
    if os.path.exists("credentials.json"):

        return Credentials.from_service_account_file(
            "credentials.json",
            scopes=scopes
        )

    raise FileNotFoundError(
        "Google credentials not found. "
        "Set GCP_SA_KEY_B64 or GCP_SA_KEY."
    )


# ============================================================
# GOOGLE SHEET
# ============================================================

def connect_google_sheet():

    print()
    print("=" * 70)
    print("CONNECTING TO GOOGLE SHEETS")
    print("=" * 70)

    credentials = get_google_credentials()

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        seat_sheet = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:

        seat_sheet = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME,
            rows=10000,
            cols=30
        )

    try:
        summary_sheet = spreadsheet.worksheet("BMS Summary")
    except gspread.WorksheetNotFound:

        summary_sheet = spreadsheet.add_worksheet(
            title="BMS Summary",
            rows=1000,
            cols=30
        )

    return seat_sheet, summary_sheet


# ============================================================
# ENSURE HEADERS
# ============================================================

def ensure_headers(sheet, headers):

    existing = sheet.row_values(1)

    if existing != headers:

        print()
        print("Updating headers...")

        sheet.update(
            "A1",
            [headers]
        )


# ============================================================
# WRITE SEAT DATA
# ============================================================

def write_seats(sheet, rows):

    if not rows:
        print("No seat rows to write.")
        return

    ensure_headers(
        sheet,
        SEAT_HEADERS
    )

    # Clear old data
    if sheet.row_count > 1:

        sheet.batch_clear([
            f"A2:Q{sheet.row_count}"
        ])

    values = []

    for row in rows:

        values.append([
            row["timestamp"],
            row["event_code"],
            row["venue_code"],
            row["session_id"],
            row["show_time"],
            row["date"],
            row["city"],
            row["row_number"],
            row["row_name"],
            row["category_code"],
            row["category"],
            row["seat_token"],
            row["seat_code"],
            row["seat_number"],
            row["status"],
            row["price"],
            row["sold_gross"],
        ])

    print()
    print("Writing seat data...")
    print(f"Rows: {len(values)}")

    sheet.update(
        "A2",
        values,
        value_input_option="USER_ENTERED"
    )


# ============================================================
# BUILD SUMMARY
# ============================================================

def build_summary(rows):

    grouped = {}

    for row in rows:

        key = (
            row["session_id"],
            row["show_time"],
            row["category"],
            row["price"],
        )

        if key not in grouped:

            grouped[key] = {
                "available": 0,
                "sold": 0,
            }

        if row["status"] == "AVAILABLE":

            grouped[key]["available"] += 1

        elif row["status"] == "SOLD":

            grouped[key]["sold"] += 1

    timestamp = datetime.now(IST).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    summary = []

    for key, stats in grouped.items():

        session_id = key[0]
        show_time = key[1]
        category = key[2]
        price = key[3]

        available = stats["available"]
        sold = stats["sold"]

        total = available + sold

        if total:

            occupancy = (
                sold / total
            ) * 100

        else:

            occupancy = 0

        gross = sold * price

        summary.append([
            timestamp,
            EVENT_CODE,
            VENUE_CODE,
            session_id,
            show_time,
            SHOW_DATE,
            CITY,
            category,
            price,
            available,
            sold,
            total,
            round(occupancy, 2),
            gross,
        ])

    return summary


# ============================================================
# WRITE SUMMARY
# ============================================================

def write_summary(sheet, rows):

    ensure_headers(
        sheet,
        SUMMARY_HEADERS
    )

    if sheet.row_count > 1:

        sheet.batch_clear([
            f"A2:N{sheet.row_count}"
        ])

    if rows:

        sheet.update(
            "A2",
            rows,
            value_input_option="USER_ENTERED"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("BMS VENUE-LEVEL ALL-SHOW TRACKER")
    print("=" * 70)

    print(datetime.now(IST).strftime(
        "%Y-%m-%d %H:%M:%S"
    ))

    print()
    print("Event :", EVENT_CODE)
    print("Venue :", VENUE_CODE)
    print("Date  :", SHOW_DATE)
    print("City  :", CITY)

    # --------------------------------------------------------
    # TEST PARSER
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("TESTING SEAT PARSER")
    print("=" * 70)

    test_tokens = [
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

    for token in test_tokens:

        print(
            f"{token:<15} -> "
            f"{parse_seat_token(token)}"
        )

    # --------------------------------------------------------
    # REQUEST ONCE
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("REQUESTING BMS VENUE SEAT LAYOUT")
    print("=" * 70)

    data = request_bms()

    if not data:

        print("FAILED: No BMS response.")
        return

    bookmyshow = get_bookmyshow(data)

    print()
    print("BMS blnSuccess:")
    print(bookmyshow.get("blnSuccess"))

    print("BMS exception:")
    print(bookmyshow.get("intException"))

    if bookmyshow.get("strException"):
        print("BMS message:")
        print(bookmyshow.get("strException"))

    # --------------------------------------------------------
    # FIND STRDATA
    # --------------------------------------------------------

    str_data = find_strdata(data)

    if not str_data:

        print()
        print("ERROR: strData not found.")

        print()
        print("Top-level response:")
        print(json.dumps(data, indent=2)[:5000])

        return

    print()
    print("strData length:", len(str_data))

    # --------------------------------------------------------
    # PARSE SEATS
    # --------------------------------------------------------

    seats = parse_seat_rows(str_data)

    print()
    print("=" * 70)
    print("SEAT SUMMARY")
    print("=" * 70)

    available = sum(
        1 for x in seats
        if x["status"] == "AVAILABLE"
    )

    sold = sum(
        1 for x in seats
        if x["status"] == "SOLD"
    )

    print("AVAILABLE:", available)
    print("SOLD     :", sold)
    print("TOTAL    :", len(seats))

    if not seats:

        print()
        print("No seats parsed.")
        return

    # --------------------------------------------------------
    # SHOW DISCOVERY
    # --------------------------------------------------------

    sessions = extract_shows(data)

    print()
    print("=" * 70)
    print("SHOWS DISCOVERED")
    print("=" * 70)

    if sessions:

        for i, session in enumerate(
            sessions,
            start=1
        ):

            print(
                f"{i:02d}. "
                f"{session['show_time']:<15} "
                f"Session {session['session_id']}"
            )

    else:

        print(
            "WARNING: No sessions could be extracted "
            "from the response."
        )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # If the response contains session-specific seat blocks,
    # parse them here.
    #
    # For the current BMS strData format, the seat layout itself
    # does not contain a session ID, so we only assign a session
    # when BMS actually supplies a matching session in the data.
    # --------------------------------------------------------

    # If only one seat layout is returned, associate it with
    # the first session only rather than falsely copying the same
    # seats to every show.

    if sessions:

        if len(sessions) == 1:

            session_id = sessions[0]["session_id"]
            show_time = sessions[0]["show_time"]

        else:

            # The venue-level response may expose multiple shows,
            # but if the returned strData has only one seat map,
            # do NOT duplicate it across every session.

            print()
            print(
                "IMPORTANT: BMS returned multiple sessions but "
                "only one seat-layout block."
            )

            print(
                "The tracker will NOT copy one seat map "
                "to every show."
            )

            print(
                "This prevents incorrect box-office calculations."
            )

            # For now, use the first session only.
            session_id = sessions[0]["session_id"]
            show_time = sessions[0]["show_time"]

    else:

        session_id = ""
        show_time = ""

    # --------------------------------------------------------
    # PRICE MAP
    # --------------------------------------------------------

    prices = extract_prices(data)

    print()
    print("=" * 70)
    print("PRICE MAP")
    print("=" * 70)

    if prices:

        for category, price in prices.items():

            print(
                f"{category:<20} ₹{price}"
            )

    else:

        print(
            "No prices were found in the JSON response."
        )

    # --------------------------------------------------------
    # BUILD FINAL SEAT ROWS
    # --------------------------------------------------------

    timestamp = datetime.now(IST).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    final_rows = []

    for seat in seats:

        category = seat["category"]

        price = prices.get(
            category,
            0
        )

        sold_gross = (
            price
            if seat["status"] == "SOLD"
            else 0
        )

        final_rows.append({

            "timestamp": timestamp,

            "event_code": EVENT_CODE,

            "venue_code": VENUE_CODE,

            "session_id": session_id,

            "show_time": show_time,

            "date": SHOW_DATE,

            "city": CITY,

            "row_number": seat["row_number"],

            "row_name": seat["row_name"],

            "category_code": seat["category_code"],

            "category": category,

            "seat_token": seat["seat_token"],

            "seat_code": seat["seat_code"],

            "seat_number": seat["seat_number"],

            "status": seat["status"],

            "price": price,

            "sold_gross": sold_gross,
        })

    # --------------------------------------------------------
    # GOOGLE SHEETS
    # --------------------------------------------------------

    try:

        seat_sheet, summary_sheet = (
            connect_google_sheet()
        )

    except Exception as e:

        print()
        print("ERROR connecting to Google Sheets:")
        print(repr(e))

        return

    # --------------------------------------------------------
    # WRITE SEATS
    # --------------------------------------------------------

    write_seats(
        seat_sheet,
        final_rows
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    summary_rows = build_summary(
        final_rows
    )

    write_summary(
        summary_sheet,
        summary_rows
    )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    total_gross = sum(
        row["sold_gross"]
        for row in final_rows
    )

    print()
    print("=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    print(
        f"Seats written : {len(final_rows)}"
    )

    print(
        f"Available     : {available}"
    )

    print(
        f"Sold          : {sold}"
    )

    print(
        f"Gross         : ₹{total_gross:,.2f}"
    )

    print()
    print("Google Sheet updated successfully.")
    print("=" * 70)


if __name__ == "__main__":
    main()
