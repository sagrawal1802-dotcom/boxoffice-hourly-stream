import os
import json
import re
import datetime
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "HourlyLog"

def parse_tickets(raw_str):
    if not raw_str:
        return 0
    clean = re.sub(r"[^\d\.KMkm]", "", str(raw_str)).upper()
    if "K" in clean:
        try:
            return int(float(clean.replace("K", "")) * 1000)
        except ValueError:
            return 0
    elif "M" in clean:
        try:
            return int(float(clean.replace("M", "")) * 1000000)
        except ValueError:
            return 0
    try:
        return int(float(clean))
    except ValueError:
        return 0

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
        sheet = spreadsheet.add_worksheet(title=SHEET_TAB_NAME, rows=1000, cols=10)
        sheet.append_row([
            "Timestamp (IST)", "Movie Title", "Event Code", 
            "Language", "Tickets Sold (Last 1 Hr)", "Raw Status Text", "Scope"
        ], value_input_option="USER_ENTERED")

    session = requests.Session(impersonate="chrome120")
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://in.bookmyshow.com/explore/movies-mumbai",
        "Origin": "https://in.bookmyshow.com",
        "x-bms-platform": "WEB",
        "x-region-code": "MUMBAI",
        "x-region-slug": "mumbai"
    }

    print("2. Fetching Pan-India movie catalog from BookMyShow...")
    
    # Establish cookie session
    try:
        session.get("https://in.bookmyshow.com/explore/movies-mumbai", headers=headers, timeout=10)
    except Exception:
        pass

    # Discover national movies
    url = "https://in.bookmyshow.com/api/explore/v1/discover/movies?regionCode=MUMBAI"
    movies = []
    
    try:
        res = session.get(url, headers=headers, timeout=15)
        print(f"Catalog API HTTP Status: {res.status_code}")
        
        if res.status_code == 200:
            data = res.json()
            cards = (
                data.get("explore", {}).get("cards", []) or 
                data.get("cards", []) or 
                data.get("movies", [])
            )
            for card in cards:
                code = card.get("eventCode") or card.get("code") or card.get("event_code")
                title = card.get("title") or card.get("name") or card.get("event_name")
                lang = card.get("language") or card.get("lang") or ""
                if code and title:
                    movies.append({
                        "title": title,
                        "code": code,
                        "language": lang
                    })
    except Exception as e:
        print(f"Error during catalog fetch: {e}")

    print(f"Discovered {len(movies)} active movies.")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    print("3. Fetching hourly ticket velocity for each movie...")
    for movie in movies:
        code = movie["code"]
        movie_url = f"https://in.bookmyshow.com/api/explore/v1/movies/{code}"
        
        tickets = 0
        raw_text = "No Trending Badge"

        try:
            m_res = session.get(movie_url, headers=headers, timeout=8)
            if m_res.status_code == 200:
                m_json = m_res.json()
                details = m_json.get("movieDetails", {}) or m_json.get("data", {})
                
                label = (
                    details.get("bookingVelocity", {}).get("label") or
                    details.get("recentBookings", {}).get("text") or
                    details.get("trendingCount") or ""
                )
                if label:
                    raw_text = str(label)
                    tickets = parse_tickets(raw_text)
        except Exception:
            pass

        rows_to_append.append([
            now_ist, movie["title"], code, movie["language"], tickets, raw_text, "All India"
        ])
        print(f"-> {movie['title']}: {tickets} tickets ({raw_text})")

    # 4. Push to Google Sheets
    if rows_to_append:
        print(f"\nWriting {len(rows_to_append)} rows to Google Sheet...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet updated successfully.")
    else:
        print("No rows generated.")

if __name__ == "__main__":
    run()
