import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "Palldium_26Aug"
TARGET_DATE = "2026-08-26"
TARGET_MOVIE = "Toxic: A Fairy Tale for Grown-ups"
CINEMA_KEYWORD = "Palladium"

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
    
    shows_data = []
    rows_to_append = []

    print(f"2. Launching District.in browser session for {TARGET_DATE}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        # Intercept District/Zomato API network payloads
        def intercept_response(response):
            if "json" in response.headers.get("content-type", "") and ("shows" in response.url or "movies" in response.url):
                try:
                    data = response.json()
                    # Check for District's cinema schedule arrays
                    cinemas = data.get("cinemas", []) or data.get("data", {}).get("cinemas", [])
                    if cinemas:
                        for cinema in cinemas:
                            if CINEMA_KEYWORD.lower() in cinema.get("name", "").lower():
                                for show in cinema.get("shows", []):
                                    movie_name = show.get("movie_name") or data.get("movies", {}).get(show.get("movie_id"), {}).get("name", "")
                                    if TARGET_MOVIE.lower() in movie_name.lower():
                                        shows_data.append({
                                            "cinema": cinema.get("name"),
                                            "movie": movie_name,
                                            "time": show.get("show_time", ""),
                                            "format": f"{show.get('screen_format', '')} {show.get('language', '')}".strip(),
                                            "audi": show.get("audi_name", "Audi"),
                                            "session_id": show.get("session_id") or show.get("id"),
                                            "areas": show.get("areas", [])
                                        })
                except Exception:
                    pass

        page.on("response", intercept_response)

        try:
            # Navigate to District Mumbai movies page with the target date query parameter
            page.goto(f"https://www.district.in/movies/mumbai-movie-tickets?date={TARGET_DATE}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            
            # Scroll to trigger lazy-loaded inventory
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(2000)
            
        except Exception as e:
            print(f"Page load note: {e}")

        browser.close()

    print(f"Discovered {len(shows_data)} matching shows for '{TARGET_MOVIE}' at {CINEMA_KEYWORD}.")

    # 3. Process Seat Availability
    for show in shows_data:
        total_seats = 0
        booked_seats = 0
        
        # District embeds seat category limits directly in the show array
        for area in show.get("areas", []):
            capacity = int(area.get("total_seats", 0) or area.get("capacity", 0))
            available = int(area.get("avail_seats", 0) or area.get("available", 0))
            total_seats += capacity
            booked_seats += max(0, capacity - available)

        avail_seats = max(0, total_seats - booked_seats)
        occ_pct = calculate_occupancy(booked_seats, total_seats)

        rows_to_append.append([
            now_ist, TARGET_DATE, show["cinema"], show["movie"],
            show["format"], show["audi"], show["time"],
            total_seats, booked_seats, avail_seats, occ_pct
        ])
        print(f"-> {show['movie']} ({show['time']}) | Booked: {booked_seats}/{total_seats} ({occ_pct})")

    # 4. Write to Google Sheets
    if rows_to_append:
        print(f"\n3. Writing {len(rows_to_append)} rows to Google Sheet...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet tab updated.")
    else:
        print("No active advance shows found on District for this date. The theatre may not have pushed the schedule yet.")

if __name__ == "__main__":
    run()
