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

REGIONS = ["MUMBAI", "NCR", "BANG", "HYD", "CHEN", "KOCH", "KOLK", "PUNE"]

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
    print("Connecting to Google Sheets...")
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
    unique_movies = {}

    print("1. Querying active movie catalog across major regions...")
    for reg in REGIONS:
        # Standard BMS mobile web quick-search endpoint
        url = f"https://in.bookmyshow.com/serv/v2/explore/movies?region={reg}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Accept": "application/json, text/plain, */*",
            "x-bms-platform": "MOBWEB",
            "x-region-code": reg
        }
        
        try:
            res = session.get(url, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                # Parse all variations of movie lists returned by BMS
                movie_list = (
                    data.get("movies", []) or 
                    data.get("explore", {}).get("movies", []) or 
                    data.get("data", {}).get("movies", []) or 
                    data.get("cards", [])
                )
                
                for item in movie_list:
                    code = item.get("code") or item.get("eventCode") or item.get("EventCode")
                    title = item.get("name") or item.get("title") or item.get("EventTitle")
                    lang = item.get("lang") or item.get("language") or item.get("EventLanguage") or ""
                    
                    if code and title and code not in unique_movies:
                        unique_movies[code] = {
                            "title": title,
                            "language": lang,
                            "region": reg
                        }
        except Exception as e:
            print(f"Error fetching {reg}: {e}")

    print(f"Discovered {len(unique_movies)} total active movies pan-India.")

    # Fallback to general quick search if mobile endpoint is cached empty
    if not unique_movies:
        print("Running quick fallback search...")
        fallback_url = "https://in.bookmyshow.com/api/explore/v1/discover/regions"
        try:
            fb_res = session.get(fallback_url, timeout=10)
            print(f"Fallback response status: {fb_res.status_code}")
        except Exception as e:
            print(f"Fallback error: {e}")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    print("2. Fetching Pan-India velocity counter for each movie...")
    for code, meta in unique_movies.items():
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "x-bms-platform": "MOBWEB",
            "x-region-code": meta["region"]
        }
        
        detail_url = f"https://in.bookmyshow.com/serv/v2/movies/{code}"
        tickets = 0
        raw_text = "No Velocity Badge"

        try:
            d_res = session.get(detail_url, headers=headers, timeout=10)
            if d_res.status_code == 200:
                d_json = d_res.json()
                # Check for trending metrics
                details = d_json.get("movieDetails", {}) or d_json.get("data", {})
                raw_text = (
                    details.get("bookingVelocity", {}).get("label") or
                    details.get("recentBookings", {}).get("text") or
                    details.get("trendingCount") or ""
                )
                tickets = parse_tickets(raw_text)
        except Exception as e:
            print(f"Error checking {meta['title']}: {e}")

        rows_to_append.append([
            now_ist, meta["title"], code, meta["language"], tickets, raw_text, "All India"
        ])
        print(f"-> {meta['title']}: {tickets} ({raw_text})")

    # 3. Write batch data to Google Sheet
    if rows_to_append:
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print(f"\nSuccess: Appended {len(rows_to_append)} rows to Google Sheet!")
    else:
        print("\nNo rows generated. Check output logs above.")

if __name__ == "__main__":
    run()
