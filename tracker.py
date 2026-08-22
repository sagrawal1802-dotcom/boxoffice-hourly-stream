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
CITY_NAME = "mumbai"
CINEMA_KEYWORD = "Palladium"
TARGET_MOVIE = "Toxic"

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
        "client": "web"
    }

    rows_to_append = []

    print(f"2. Fetching showtimes from Paytm/District for {CITY_NAME} on {TARGET_DATE}...")
    
    # 1. Query city movies & cinema showtimes
    catalog_url = f"https://apiproxy.paytm.com/v2/movies/shows?city={CITY_NAME}&date={TARGET_DATE}"
    
    try:
        res = session.get(catalog_url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            cinemas = data.get("cinemas", []) or data.get("data", {}).get("cinemas", [])
            movies_dict = {m["id"]: m.get("name", "") for m in data.get("movies", []) if "id" in m}

            # Filter for PVR ICON Phoenix Palladium
            target_cinemas = [c for c in cinemas if CINEMA_KEYWORD.lower() in c.get("name", "").lower()]
            
            if not target_cinemas:
                # If specific date isn't listed yet, check all Palladium shows
                target_cinemas = cinemas

            for cinema in target_cinemas:
                cinema_name = cinema.get("name", "PVR ICON Palladium")
                if CINEMA_KEYWORD.lower() not in cinema_name.lower():
                    continue

                for show in cinema.get("shows", []):
                    movie_id = show.get("movie_id") or show.get("movieId")
                    movie_name = movies_dict.get(movie_id, show.get("movie_name", "Toxic"))
                    
                    # Filter for Toxic (case-insensitive)
                    if TARGET_MOVIE.lower() not in movie_name.lower():
                        continue

                    session_id = show.get("session_id") or show.get("id")
                    show_time = show.get("show_time") or show.get("time", "")
                    format_lang = f"{show.get('screen_format', '')} {show.get('language', '')}".strip()
                    audi = show.get("audi_name", "Audi")

                    total_seats = 0
                    booked_seats = 0

                    # 2. Extract seat inventory layout
                    if session_id:
                        seat_url = f"https://apiproxy.paytm.com/v3/movies/seats?session_id={session_id}&city={CITY_NAME}"
                        try:
                            s_res = session.get(seat_url, headers=headers, timeout=8)
                            if s_res.status_code == 200:
                                s_json = s_res.json()
                                # Calculate available vs occupied seats
                                for row in s_json.get("seatLayout", {}).get("rows", []):
                                    for seat in row.get("seats", []):
                                        if seat.get("type", "").lower() != "space":
                                            total_seats += 1
                                            if seat.get("status", "").lower() in ["booked", "occupied", "unavailable", "sold"]:
                                                booked_seats += 1
                        except Exception as e:
                            print(f"Error reading seat layout: {e}")

                    # Fallback to category level numbers if layout is blocked
                    if total_seats == 0 and "areas" in show:
                        for area in show.get("areas", []):
                            tot = int(area.get("total_seats", 0))
                            avail = int(area.get("avail_seats", 0))
                            total_seats += tot
                            booked_seats += max(0, tot - avail)

                    avail_seats = max(0, total_seats - booked_seats)
                    occ_pct = calculate_occupancy(booked_seats, total_seats)

                    rows_to_append.append([
                        now_ist, TARGET_DATE, cinema_name, movie_name,
                        format_lang, audi, show_time, total_seats,
                        booked_seats, avail_seats, occ_pct
                    ])
                    print(f"-> {movie_name} ({show_time}) | Booked: {booked_seats}/{total_seats} ({occ_pct})")

        else:
            print(f"Paytm API returned status: {res.status_code}")

    except Exception as e:
        print(f"Error querying Paytm/District: {e}")

    # 3. Write rows to Google Sheets
    if rows_to_append:
        print(f"\n3. Writing {len(rows_to_append)} rows to Google Sheet...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet tab updated.")
    else:
        print("No active show sessions found for the specified date and movie.")

if __name__ == "__main__":
    run()
