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

# BMS standard city codes
REGIONS = ["MUMBAI", "NCR", "BANG", "HYD", "CHEN", "KOCH", "KOLK"]

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

    print("Fetching active movies across India...")
    for region in REGIONS:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "x-bms-platform": "WEB",
            "x-region-code": region
        }
        
        # Primary public explore endpoint
        url = f"https://in.bookmyshow.com/api/explore/v1/discover/movies?regionCode={region}"
        try:
            res = session.get(url, headers=headers, timeout=12)
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
                    if code and title and code not in unique_movies:
                        unique_movies[code] = {
                            "title": title,
                            "language": card.get("language", ""),
                            "region": region
                        }
            else:
                # Fallback: Scrape public region page if API returns restricted
                page_url = f"https://in.bookmyshow.com/explore/movies-{region.lower()}"
                page_res = session.get(page_url, headers=headers, timeout=12)
                if page_res.status_code == 200:
                    matches = re.findall(r'\/movies\/[^\/]+\/([a-z0-9-]+)\/(ET\d{6,10})', page_res.text, re.IGNORECASE)
                    for slug, code in matches:
                        if code not in unique_movies:
                            title = slug.replace("-", " ").title()
                            unique_movies[code] = {
                                "title": title,
                                "language": "",
                                "region": region
                            }
        except Exception as e:
            print(f"Failed checking {region}: {e}")

    print(f"Total unique movies found: {len(unique_movies)}")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    for code, meta in unique_movies.items():
        headers = {
            "Accept": "application/json, text/plain, */*",
            "x-bms-platform": "WEB",
            "x-region-code": meta.get("region", "MUMBAI")
        }
        movie_url = f"https://in.bookmyshow.com/api/explore/v1/movies/{code}"
        
        raw_text = ""
        tickets = 0
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
            else:
                # Fallback: check direct movie HTML page for velocity badge
                m_page = session.get(f"https://in.bookmyshow.com/movies/{code}", headers=headers, timeout=10)
                if m_page.status_code == 200:
                    v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', m_page.text, re.IGNORECASE)
                    if v_match:
                        raw_text = v_match.group(0)
                        tickets = parse_tickets(v_match.group(1))
        except Exception as e:
            print(f"Error checking {meta['title']}: {e}")

        rows_to_append.append([
            now_ist, meta["title"], code, meta["language"], tickets, raw_text, "All India"
        ])

    print(f"Preparing to write {len(rows_to_append)} rows to Google Sheets...")
    if rows_to_append:
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Done! Data written to Google Sheet successfully.")
    else:
        print("No rows generated.")

if __name__ == "__main__":
    run()
