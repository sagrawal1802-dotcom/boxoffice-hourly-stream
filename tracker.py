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

REGIONS = ["mumbai", "national-capital-region-ncr", "bengaluru", "hyderabad", "chennai", "kochi", "kolkata"]

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

def extract_state_json(html_text):
    """Extracts preloaded React/Next state embedded inside BMS HTML."""
    # Look for window.__INITIAL_STATE__ or __NEXT_DATA__
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});\s*</script>', html_text, re.DOTALL)
    if not match:
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html_text, re.DOTALL)
    
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None

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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    unique_movies = {}

    print("1. Discovering active movies across top Indian hubs...")
    for region in REGIONS:
        url = f"https://in.bookmyshow.com/explore/movies-{region}"
        try:
            res = session.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                # Extract all movie URLs: /movies/<city>/<slug>/<event_code>
                matches = re.findall(r'/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})', res.text, re.IGNORECASE)
                for slug, code in matches:
                    if code not in unique_movies:
                        clean_title = slug.replace("-", " ").title()
                        unique_movies[code] = {
                            "title": clean_title,
                            "slug": slug,
                            "region": region
                        }
        except Exception as e:
            print(f"Error discovering region {region}: {e}")

    print(f"Total unique movies found: {len(unique_movies)}")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    print("2. Fetching hourly ticket velocity for each movie...")
    for code, meta in unique_movies.items():
        movie_url = f"https://in.bookmyshow.com/movies/{meta['region']}/{meta['slug']}/{code}"
        tickets = 0
        raw_text = "No Velocity Badge"
        language = ""

        try:
            m_res = session.get(movie_url, headers=headers, timeout=12)
            if m_res.status_code == 200:
                html = m_res.text
                
                # Check for regex pattern across HTML: e.g., "14.5K tickets booked in last 1 hour"
                v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)\s*(?:in\s+last|in\s+the\s+last)?\s*1\s*(?:hour|hr)', html, re.IGNORECASE)
                if not v_match:
                    # Generic 24hr or rolling activity match
                    v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', html, re.IGNORECASE)

                if v_match:
                    raw_text = v_match.group(0)
                    tickets = parse_tickets(v_match.group(1))
                
                # Inspect embedded state JSON for exact structured keys
                state = extract_state_json(html)
                if state:
                    # Recursive search for velocity/counter keys inside state
                    state_str = json.dumps(state)
                    v_state_match = re.search(r'\"(?:bookingVelocity|recentBookings|trendingLabel)\"\s*:\s*\"([^\"]+)\"', state_str)
                    if v_state_match:
                        raw_text = v_state_match.group(1)
                        tickets = parse_tickets(raw_text)

        except Exception as e:
            print(f"Failed fetching {meta['title']}: {e}")

        rows_to_append.append([
            now_ist, meta["title"], code, language, tickets, raw_text, "All India"
        ])
        print(f"-> {meta['title']}: {tickets} tickets ({raw_text})")

    # Write to Google Sheets
    if rows_to_append:
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print(f"\nSuccessfully wrote {len(rows_to_append)} rows to Google Sheet.")
    else:
        print("\nNo rows generated.")

if __name__ == "__main__":
    run()
