import os
import json
import re
import datetime
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

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

    session = requests.Session(impersonate="safari15_5")
    unique_movies = {}

    print("2. Fetching movie catalogs via BMS App API...")
    for reg in REGIONS:
        url = f"https://in.bookmyshow.com/serv/v2/explore/movies?region={reg}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            "x-bms-platform": "MOBWEB",
            "x-region-code": reg
        }
        
        try:
            res = session.get(url, headers=headers, timeout=12)
            print(f"[{reg}] Response HTTP {res.status_code}")
            
            if res.status_code == 200:
                data = res.json()
                # Parse all variations of movie catalog payloads
                movies_arr = (
                    data.get("movies", []) or 
                    data.get("explore", {}).get("movies", []) or 
                    data.get("data", {}).get("movies", []) or 
                    data.get("cards", [])
                )
                
                for item in movies_arr:
                    code = item.get("code") or item.get("eventCode") or item.get("EventCode")
                    title = item.get("name") or item.get("title") or item.get("EventTitle")
                    if code and title and code not in unique_movies:
                        unique_movies[code] = {
                            "title": title,
                            "code": code,
                            "region": reg
                        }
        except Exception as e:
            print(f"Error for {reg}: {e}")

    print(f"\nTotal unique movies found: {len(unique_movies)}")

    # Fallback to direct explore catalog if mobile payload is restricted
    if len(unique_movies) == 0:
        print("Running public catalog fallback...")
        fallback_url = "https://in.bookmyshow.com/serv/v2/explore/movies"
        try:
            fb_res = session.get(fallback_url, timeout=10)
            if fb_res.status_code == 200:
                for item in fb_res.json().get("movies", []):
                    code = item.get("code") or item.get("eventCode")
                    title = item.get("name") or item.get("title")
                    if code and title:
                        unique_movies[code] = {"title": title, "code": code, "region": "MUMBAI"}
        except Exception as e:
            print(f"Fallback error: {e}")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    print("3. Fetching booking velocity badges...")
    for code, meta in unique_movies.items():
        movie_url = f"https://in.bookmyshow.com/serv/v2/movies/{code}"
        tickets = 0
        raw_text = "No Velocity Badge"

        try:
            m_res = session.get(movie_url, timeout=10)
            if m_res.status_code == 200:
                details = m_res.json().get("movieDetails", {}) or m_res.json().get("data", {})
                raw_text = (
                    details.get("bookingVelocity", {}).get("label") or
                    details.get("recentBookings", {}).get("text") or
                    details.get("trendingCount") or ""
                )
                tickets = parse_tickets(raw_text)
        except Exception as e:
            print(f"Error checking {meta['title']}: {e}")

        rows_to_append.append([
            now_ist, meta["title"], code, tickets, raw_text, "All India"
        ])
        print(f"-> {meta['title']}: {tickets} tickets ({raw_text})")

    # 4. Push to Google Sheets
    if rows_to_append:
        print(f"\nPushing {len(rows_to_append)} rows to Google Sheet...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet updated.")
    else:
        print("No movie rows generated.")

if __name__ == "__main__":
    run()
