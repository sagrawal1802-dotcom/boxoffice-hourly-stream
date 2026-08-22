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

REGIONS = [
    "mumbai", "national-capital-region-ncr", "bengaluru", 
    "hyderabad", "chennai", "kochi", "kolkata"
]

def parse_tickets(raw_str):
    if not raw_str:
        return 0
    clean = re.sub(r"[^\d\.KMkm]", "", raw_str).upper()
    if "K" in clean:
        return int(float(clean.replace("K", "")) * 1000)
    elif "M" in clean:
        return int(float(clean.replace("M", "")) * 1000000)
    try:
        return int(float(clean))
    except ValueError:
        return 0

def run():
    # 1. Authenticate with Google Sheets
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

    # 2. Discover Pan-India Active Movies
    session = requests.Session(impersonate="chrome120")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "x-bms-platform": "WEB"
    }

    unique_movies = {}
    for region in REGIONS:
        url = f"https://in.bookmyshow.com/api/explore/v1/discover/movies/{region}"
        try:
            res = session.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                cards = res.json().get("explore", {}).get("cards", [])
                for card in cards:
                    code = card.get("eventCode") or card.get("code")
                    title = card.get("title") or card.get("name")
                    if code and title and code not in unique_movies:
                        unique_movies[code] = {
                            "title": title,
                            "language": card.get("language", "")
                        }
        except Exception as e:
            print(f"Error checking {region}: {e}")

    print(f"Discovered {len(unique_movies)} active movies pan-India.")

    # 3. Extract Pan-India Hourly Velocity
    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    for code, meta in unique_movies.items():
        movie_url = f"https://in.bookmyshow.com/api/explore/v1/movies/{code}"
        try:
            m_res = session.get(movie_url, headers=headers, timeout=10)
            if m_res.status_code == 200:
                details = m_res.json().get("movieDetails", {})
                raw_text = (
                    details.get("bookingVelocity", {}).get("label") or
                    details.get("recentBookings", {}).get("text") or
                    details.get("trendingCount") or ""
                )
                tickets = parse_tickets(raw_text)
                
                rows_to_append.append([
                    now_ist, meta["title"], code, meta["language"], tickets, raw_text, "All India"
                ])
        except Exception as e:
            print(f"Error fetching {meta['title']}: {e}")

    # 4. Batch append records to Google Sheets
    if rows_to_append:
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print(f"Successfully logged {len(rows_to_append)} records.")

if __name__ == "__main__":
    run()
