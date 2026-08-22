import os
import json
import re
import datetime
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "HourlyLog"

REGIONS = ["mumbai", "national-capital-region-ncr", "bengaluru", "hyderabad", "chennai", "kolkata"]

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
            "Tickets Sold (Last 1 Hr)", "Raw Status Text", "Scope"
        ], value_input_option="USER_ENTERED")

    session = requests.Session(impersonate="chrome120")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "x-bms-platform": "WEB"
    }

    unique_movies = {}

    print("2. Discovering movies from public regional listings...")
    for reg in REGIONS:
        url = f"https://in.bookmyshow.com/explore/movies-{reg}"
        try:
            res = session.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                matches = re.findall(r'/movies/([^/]+)/([a-z0-9-]+)/(ET\d{6,10})', res.text, re.IGNORECASE)
                for city, slug, code in matches:
                    if code not in unique_movies:
                        title = slug.replace("-", " ").title()
                        unique_movies[code] = {
                            "title": title,
                            "slug": slug,
                            "city": city,
                            "code": code
                        }
        except Exception as e:
            print(f"Error checking {reg}: {e}")

    print(f"Discovered {len(unique_movies)} unique movies pan-India.")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    print("3. Querying booking velocity per movie...")
    for code, meta in unique_movies.items():
        # Try both the JSON explore API and direct page regex
        api_url = f"https://in.bookmyshow.com/api/explore/v1/movies/{code}"
        page_url = f"https://in.bookmyshow.com/movies/{meta['city']}/{meta['slug']}/{code}"
        
        tickets = 0
        raw_text = "No Velocity Badge"

        # Attempt 1: Check explore API payload
        try:
            api_res = session.get(api_url, headers=headers, timeout=8)
            if api_res.status_code == 200:
                data = api_res.json()
                movie_data = data.get("movieDetails", {}) or data.get("data", {})
                raw_text = (
                    movie_data.get("bookingVelocity", {}).get("label") or
                    movie_data.get("recentBookings", {}).get("text") or
                    movie_data.get("trendingCount") or ""
                )
                if raw_text:
                    tickets = parse_tickets(raw_text)
        except Exception:
            pass

        # Attempt 2: If API didn't return text, inspect HTML page for velocity badges
        if tickets == 0:
            try:
                p_res = session.get(page_url, headers=headers, timeout=8)
                if p_res.status_code == 200:
                    match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', p_res.text, re.IGNORECASE)
                    if match:
                        raw_text = match.group(0)
                        tickets = parse_tickets(match.group(1))
            except Exception:
                pass

        rows_to_append.append([
            now_ist, meta["title"], code, tickets, raw_text, "All India"
        ])
        print(f"-> {meta['title']}: {tickets} ({raw_text})")

    # 4. Append to Google Sheet
    if rows_to_append:
        print(f"\nWriting {len(rows_to_append)} rows to Google Sheet...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet updated.")

if __name__ == "__main__":
    run()
