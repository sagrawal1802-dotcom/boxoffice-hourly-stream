import os
import json
import datetime
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "Palldium_26Aug"
TARGET_DATE = "2026-08-26"
VENUE_CODE = "PALL"  # BMS Venue Code for PVR ICON Phoenix Palladium Lower Parel
TARGET_MOVIE = "TOXIC"

def calculate_occupancy(booked, total):
    if total == 0:
        return "0.00%"
    return f"{(booked / total) * 100:.2f}%"

def run():
    print("1. Connecting to Google Sheets...")
    sa_info = json.loads(os.environ["GCP_SA_KEY"])
    creds = Credentials.from_service_account_info(
        sa_info, 
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        sheet = spreadsheet.worksheet(SHEET_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_TAB_NAME, rows=500, cols=12)
        sheet.append_row([
            "Snapshot Timestamp (IST)", "Show Date", "Theatre", "Movie Title",
            "Language & Format", "Screen / Audi", "Show Time", "Total Seats",
            "Sold / Booked Seats", "Available Seats", "Occupancy %"
        ], value_input_option="USER_ENTERED")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    session = requests.Session(impersonate="chrome120")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "x-bms-platform": "WEB",
        "x-region-code": "MUMBAI"
    }

    date_clean = TARGET_DATE.replace("-", "")
    print(f"2. Fetching advance shows for {TARGET_MOVIE} at Palladium on {TARGET_DATE}...")

    # Query public showtime API for Palladium Mumbai
    url = f"https://in.bookmyshow.com/api/explore/v1/shows/by-venue?venueCode={VENUE_CODE}&date={date_clean}"
    rows_to_append = []

    try:
        res = session.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            events = data.get("events", []) or data.get("data", {}).get("events", [])

            for event in events:
                movie_title = event.get("title") or event.get("name", "")
                
                # Check for target movie match (or include all if Toxic is listed under sub-titles)
                lang_format = f"{event.get('dimension', '')} {event.get('language', '')}".strip()
                shows = event.get("shows", []) or event.get("showTimes", [])

                for show in shows:
                    session_id = show.get("sessionId") or show.get("showId")
                    show_time = show.get("showTime") or show.get("time", "")
                    audi = show.get("screenName") or show.get("audi", "Audi")

                    total_seats = 0
                    booked_seats = 0

                    # 1. Parse categories inventory
                    categories = show.get("categories", [])
                    if categories:
                        for cat in categories:
                            cap = int(cat.get("capacity", 0) or cat.get("total", 0))
                            avail = int(cat.get("available", 0) or cat.get("curAvail", 0))
                            total_seats += cap
                            booked_seats += max(0, cap - avail)

                    # 2. Detailed seat-grid fallback if category summary isn't present
                    if total_seats == 0 and session_id:
                        s_url = f"https://in.bookmyshow.com/api/explore/v1/seats?sessionId={session_id}"
                        try:
                            s_res = session.get(s_url, headers=headers, timeout=8)
                            if s_res.status_code == 200:
                                s_data = s_res.json()
                                seats = s_data.get("seatLayout", {}).get("seats", [])
                                total_seats = len(seats)
                                booked_seats = sum(1 for s in seats if str(s.get("status", "")).lower() in ["booked", "sold", "unavailable", "1"])
                        except Exception as e:
                            print(f"Error checking layout for {session_id}: {e}")

                    avail_seats = max(0, total_seats - booked_seats)
                    occ_pct = calculate_occupancy(booked_seats, total_seats)

                    rows_to_append.append([
                        now_ist,
                        TARGET_DATE,
                        "PVR ICON Palladium Lower Parel",
                        movie_title,
                        lang_format,
                        audi,
                        show_time,
                        total_seats,
                        booked_seats,
                        avail_seats,
                        occ_pct
                    ])
                    print(f"-> {movie_title} [{lang_format}] ({show_time}) | Booked: {booked_seats}/{total_seats} ({occ_pct})")

        else:
            print(f"BMS returned status code: {res.status_code}")

    except Exception as e:
        print(f"Error querying schedule: {e}")

    # Fallback to direct PVR chain endpoint if BMS venue grid is currently caching
    if len(rows_to_append) == 0:
        print("Checking PVR direct API for advance shows...")
        pvr_url = f"https://api.pvrcinemas.com/shows/v1/venue/{VENUE_CODE}?date={TARGET_DATE}"
        try:
            pvr_res = session.get(pvr_url, timeout=10)
            if pvr_res.status_code == 200:
                pvr_data = pvr_res.json()
                for s in pvr_data.get("shows", []):
                    title = s.get("movieName", "Toxic")
                    s_time = s.get("showTime", "")
                    t_seats = int(s.get("totalSeats", 0))
                    b_seats = int(s.get("bookedSeats", 0))
                    a_seats = max(0, t_seats - b_seats)
                    rows_to_append.append([
                        now_ist, TARGET_DATE, "PVR ICON Palladium Lower Parel",
                        title, s.get("format", ""), s.get("audi", ""), s_time,
                        t_seats, b_seats, a_seats, calculate_occupancy(b_seats, t_seats)
                    ])
        except Exception as e:
            print(f"PVR direct error: {e}")

    # 3. Write rows to Google Sheets
    if rows_to_append:
        print(f"\n3. Writing {len(rows_to_append)} rows to '{SHEET_TAB_NAME}'...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet tab updated.")
    else:
        print("No shows currently found for the requested date.")

if __name__ == "__main__":
    run()
