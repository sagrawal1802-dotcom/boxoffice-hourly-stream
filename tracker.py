import os
import re
import json
import base64
from datetime import datetime
import pytz
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

# --- Configuration ---
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4")
SHEET_TAB_NAME = "HourlyLog"
PROXY_URL = os.environ.get("PROXY_URL") # Format: http://user:pass@proxy-server.com:port
GCP_SA_KEY_B64 = os.environ.get("GCP_SA_KEY_B64") # Base64-encoded Service Account JSON

# Movies/Events tracking list: add your target movie slugs, codes, and region cities here
TRACKING_LIST = [
    {"slug": "devara-part-1", "code": "ET00310790", "city": "mumbai"},
    {"slug": "stree-2", "code": "ET00364249", "city": "national-capital-region-ncr"},
    {"slug": "pushpa-2-the-rule", "code": "ET00356724", "city": "hyderabad"},
    {"slug": "kalki-2898-ad", "code": "ET00311783", "city": "bengaluru"}
]

def parse_ticket_count(raw_val):
    """Converts strings like '1.5K', '250', '12.4K' or direct integers to clean integer counts."""
    if not raw_val:
        return 0
    if isinstance(raw_val, (int, float)):
        return int(raw_val)
    
    raw_str = str(raw_val).strip().upper()
    multiplier = 1
    if "K" in raw_str:
        multiplier = 1000
        raw_str = raw_str.replace("K", "")
    elif "M" in raw_str:
        multiplier = 1000000
        raw_str = raw_str.replace("M", "")
    
    numbers = re.findall(r"[\d.]+", raw_str)
    if numbers:
        try:
            return int(float(numbers[0]) * multiplier)
        except ValueError:
            return 0
    return 0

def fetch_bms_trending(item):
    """Fetches trending metrics using curl_cffi with proxy and browser TLS impersonation."""
    proxies = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
    
    # BMS Mobile/Web API endpoint for movie metadata & quick-stats
    url = f"https://in.bookmyshow.com/api/explore/v1/discover/movie/{item['city']}/{item['slug']}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Accept": "application/json, text/plain, */*",
        "x-app-code": "MOB_WEB",
        "Referer": f"https://in.bookmyshow.com/explore/movies-{item['city']}",
    }

    try:
        res = requests.get(
            url,
            headers=headers,
            proxies=proxies,
            impersonate="chrome120",
            timeout=15
        )
        if res.status_code == 200:
            data = res.json()
            page_data = data.get("pageData", {})
            analytics = page_data.get("analytics", {})
            trending_badge = page_data.get("trendingBadge", {})
            
            # Extract hourly & daily trending indicators
            hourly_raw = trending_badge.get("hourlyCount") or analytics.get("trending1Hr", "0")
            daily_raw = trending_badge.get("dailyCount") or analytics.get("trending24Hr", "0")
            badge_text = trending_badge.get("text") or trending_badge.get("subText", "")
            movie_title = page_data.get("meta", {}).get("title", item["slug"])
            
            return {
                "movie_name": movie_title,
                "movie_code": item["code"],
                "city": item["city"],
                "hourly_tickets": parse_ticket_count(hourly_raw),
                "daily_tickets": parse_ticket_count(daily_raw),
                "badge_text": badge_text
            }
        else:
            print(f"[{item['slug']}] HTTP Error {res.status_code}: {res.text[:120]}")
    except Exception as e:
        print(f"[{item['slug']}] Request exception: {e}")
        
    return None

def init_google_sheet():
    """Authenticates with Google Sheets API and selects/creates the 'HourlyLog' worksheet."""
    if not GCP_SA_KEY_B64:
        raise ValueError("Missing 'GCP_SA_KEY_B64' in environment variables.")

    sa_json = json.loads(base64.b64decode(GCP_SA_KEY_B64).decode("utf-8"))
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(sa_json, scopes=scopes)
    gc = gspread.authorize(creds)
    
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    
    # Access or create the HourlyLog tab
    try:
        sheet = spreadsheet.worksheet(SHEET_TAB_NAME)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_TAB_NAME, rows="1000", cols="20")
    
    # Add table headers if the worksheet is empty
    if not sheet.get_all_values():
        headers = [
            "Timestamp (IST)", 
            "Date (IST)", 
            "Hour (IST)", 
            "Movie Name", 
            "Movie Code", 
            "City", 
            "Hourly Tickets Sold", 
            "24h Tickets Sold", 
            "Badge Text"
        ]
        sheet.append_row(headers)
        
    return sheet

def main():
    sheet = init_google_sheet()
    
    # Set Indian Standard Time
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    
    timestamp_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now_ist.strftime("%Y-%m-%d")
    hour_str = now_ist.strftime("%H:00")

    rows_to_insert = []

    for item in TRACKING_LIST:
        print(f"Fetching trending stats for '{item['slug']}' in {item['city']}...")
        result = fetch_bms_trending(item)
        if result:
            rows_to_insert.append([
                timestamp_str,
                date_str,
                hour_str,
                result["movie_name"],
                result["movie_code"],
                result["city"],
                result["hourly_tickets"],
                result["daily_tickets"],
                result["badge_text"]
            ])

    if rows_to_insert:
        sheet.append_rows(rows_to_insert, value_input_option="USER_ENTERED")
        print(f"Successfully logged {len(rows_to_insert)} records to '{SHEET_TAB_NAME}' at {timestamp_str} IST.")
    else:
        print("No records collected during this run.")

if __name__ == "__main__":
    main()
