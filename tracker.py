import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "Kurla_26Aug"
TARGET_DATE = "2026-08-26"
TARGET_MOVIE = "Toxic"
THEATRE_NAME = "PVR Market City, Kurla (W), Mumbai"
DISTRICT_URL = f"https://www.district.in/movies/pvr-market-city-kurla-w-mumbai-in-mumbai-CD1022270?date={TARGET_DATE}"

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

    print(f"2. Launching District.in browser for {THEATRE_NAME}...")
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

        # Intercept background API payloads
        def intercept_response(response):
            if "json" in response.headers.get("content-type", "") and ("show" in response.url or "cinema" in response.url or "movie" in response.url):
                try:
                    payload = response.json()
                    # Check for cinema shows array
                    data_obj = payload.get("data", payload)
                    shows = data_obj.get("shows", []) or data_obj.get("showTimes", [])
                    
                    # If wrapped inside cinema object
                    if not shows and "cinemas" in data_obj:
                        for c in data_obj.get("cinemas", []):
                            shows.extend(c.get("shows", []))

                    for show in shows:
                        movie_title = show.get("movie_name") or show.get("movieTitle") or show.get("name", "")
                        if TARGET_MOVIE.lower() in movie_title.lower() or not TARGET_MOVIE:
                            shows_data.append({
                                "cinema": THEATRE_NAME,
                                "movie": movie_title,
                                "time": show.get("show_time") or show.get("showTime") or show.get("time", ""),
                                "format": f"{show.get('screen_format', '')} {show.get('language', '')}".strip(),
                                "audi": show.get("audi_name") or show.get("audi", "Audi"),
                                "areas": show.get("areas", []) or show.get("categories", [])
                            })
                except Exception:
                    pass

        page.on("response", intercept_response)

        try:
            page.goto(DISTRICT_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(2000)

            # Fallback DOM scrape if movie is visible on page
            rendered_html = page.content()
            if TARGET_MOVIE.lower() in rendered_html.lower() and len(shows_data) == 0:
                print("Detected movie in HTML DOM, extracting text elements...")
                # Scrapes timing chips if rendered visually
                time_buttons = page.eval_on_selector_all(
                    "button, a, div",
                    "elements => elements.map(e => e.innerText).filter(t => /\\d{1,2}:\\d{2}\\s*(?:AM|PM)/i.test(t))"
                )
                for t in set(time_buttons[:10]):
                    shows_data.append({
                        "cinema": THEATRE_NAME,
                        "movie": "Toxic: A Fairy Tale for Grown-ups",
                        "time": t.strip(),
                        "format": "2D Hindi/Kannada",
                        "audi": "Audi",
                        "areas": []
                    })
        except Exception as e:
            print(f"Navigation note: {e}")

        browser.close()

    print(f"Discovered {len(shows_data)} matching shows for '{TARGET_MOVIE}' at {THEATRE_NAME}.")

    # 3. Calculate seat inventory
    for show in shows_data:
        total_seats = 0
        booked_seats = 0

        for area in show.get("areas", []):
            capacity = int(area.get("total_seats", 0) or area.get("capacity", 0) or area.get("total", 0))
            available = int(area.get("avail_seats", 0) or area.get("available", 0) or area.get("curAvail", 0))
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

    # 4. Write to Google Sheet
    if rows_to_append:
        print(f"\n3. Writing {len(rows_to_append)} rows to '{SHEET_TAB_NAME}'...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet tab updated.")
    else:
        print("No advance bookings active yet for this date. Tracker will keep monitoring automatically every hour.")

if __name__ == "__main__":
    run()
