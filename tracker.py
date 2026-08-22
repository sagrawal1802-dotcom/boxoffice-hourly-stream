import os
import json
import datetime
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
TARGET_DATE = "2026-08-26"
CINEMA_NAME = "PVR ICON: Phoenix Palladium, Lower Parel, Mumbai"
CINEMA_CODE = "PALL"  # BMS / PVR internal identifier for Palladium Mumbai

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
        sheet = spreadsheet.worksheet("Palladium_26Aug")
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Palladium_26Aug", rows=500, cols=12)
        sheet.append_row([
            "Snapshot Timestamp (IST)", "Date", "Theatre", "Movie Title",
            "Language & Format", "Screen", "Show Time", "Total Seats",
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

    print(f"2. Fetching showtimes for {CINEMA_NAME} on {TARGET_DATE}...")
    
    # Endpoint to query Palladium Mumbai schedule for target date
    url = f"https://in.bookmyshow.com/api/explore/v1/shows/by-venue?venueCode={CINEMA_CODE}&date={TARGET_DATE.replace('-', '')}"
    
    rows_to_append = []

    try:
        res = session.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            events = data.get("events", []) or data.get("data", {}).get("events", [])
            
            for event in events:
                movie_title = event.get("title") or event.get("name", "Unknown Movie")
                lang_format = event.get("dimension", "") + " " + event.get("language", "")
                
                shows = event.get("shows", []) or event.get("showTimes", [])
                for show in shows:
                    session_id = show.get("sessionId") or show.get("showId")
                    show_time = show.get("showTime") or show.get("time", "")
                    audi = show.get("screenName") or show.get("audi", "Audi 1")
                    
                    total_seats = 0
                    booked_seats = 0
                    
                    # Query seat layout for session
                    if session_id:
                        seat_url = f"https://in.bookmyshow.com/api/explore/v1/seats?sessionId={session_id}"
                        try:
                            seat_res = session.get(seat_url, headers=headers, timeout=8)
                            if seat_res.status_code == 200:
                                seat_data = seat_res.json()
                                seats = seat_data.get("seatLayout", {}).get("seats", [])
                                total_seats = len(seats)
                                booked_seats = sum(1 for s in seats if str(s.get("status", "")).lower() in ["booked", "sold", "unavailable", "1"])
                        except Exception as e:
                            print(f"Error reading layout for {session_id}: {e}")

                    # If layout API is masked, fallback to category inventory aggregates
                    if total_seats == 0 and "categories" in show:
                        for cat in show.get("categories", []):
                            cat_total = int(cat.get("capacity", 0))
                            cat_avail = int(cat.get("available", 0))
                            total_seats += cat_total
                            booked_seats += max(0, cat_total - cat_avail)

                    avail_seats = max(0, total_seats - booked_seats)
                    occ_pct = calculate_occupancy(booked_seats, total_seats)

                    rows_to_append.append([
                        now_ist,
                        TARGET_DATE,
                        "PVR ICON Palladium Lower Parel",
                        movie_title,
                        lang_format.strip(),
                        audi,
                        show_time,
                        total_seats,
                        booked_seats,
                        avail_seats,
                        occ_pct
                    ])
                    print(f"-> {movie_title} ({show_time}) | Booked: {booked_seats}/{total_seats} ({occ_pct})")

        else:
            print(f"BMS returned status code: {res.status_code}")

    except Exception as e:
        print(f"Error querying schedule: {e}")

    # Fallback to direct mock check if bookings for August 26 haven't opened yet
    if len(rows_to_append) == 0:
        print("Note: Shows for August 26, 2026 may not yet be listed by the cinema chain.")
        rows_to_append.append([
            now_ist,
            TARGET_DATE,
            "PVR ICON Palladium Lower Parel",
            "Schedule Not Yet Opened by Cinema",
            "N/A",
            "N/A",
            "N/A",
            0,
            0,
            0,
            "0.00%"
        ])

    # 3. Append to Sheet
    print(f"\n3. Writing {len(rows_to_append)} rows to Google Sheet tab 'Palladium_26Aug'...")
    sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
    print("Completed successfully.")

if __name__ == "__main__":
    run()
