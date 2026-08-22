import os
import json
import re
import datetime
from curl_cffi import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "FilmyView_Hourly"
TARGET_HANDLE = "filmy_view"

def parse_num(s):
    if not s:
        return 0
    clean = re.sub(r"[^\d\.KMkm]", "", str(s)).upper()
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

def extract_bms_metrics(text):
    """
    Extracts movie title, time window, hourly ticket count, and total ticket count
    from @filmy_view post patterns:
    '#Toxic SUPER 9-10am. Tickets sold on BMS- 24020. Total from 6am- 44390'
    """
    # 1. Movie Name / Hashtag
    movie_match = re.search(r'#([A-Za-z0-9_]+)', text)
    movie = movie_match.group(1) if movie_match else "Toxic"

    # 2. Time Slot (e.g., 9-10am, 12-1pm, 6-7 PM)
    time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', text)
    time_slot = time_match.group(1) if time_match else "Latest Update"

    # 3. Tickets sold in current hour
    hourly_match = re.search(r'(?:tickets\s*sold\s*on\s*bms|hourly|bms)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    hourly_tickets = parse_num(hourly_match.group(1)) if hourly_match else 0

    # 4. Cumulative Total from 6am
    total_match = re.search(r'(?:total\s*from\s*6am|total\s*bms|total)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    total_tickets = parse_num(total_match.group(1)) if total_match else 0

    return movie, time_slot, hourly_tickets, total_tickets

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
            "Logged Timestamp (IST)", "Movie / Hashtag", "Time Window",
            "Hourly Tickets (BMS)", "Total Cumulative (BMS)", "Raw Post Text"
        ], value_input_option="USER_ENTERED")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    session = requests.Session(impersonate="chrome120")

    # Fetch directly from Twitter's public syndication feed (No login wall)
    syndication_url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{TARGET_HANDLE}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    print(f"2. Fetching posts from @{TARGET_HANDLE} via Syndication Feed...")
    tweets_raw = []
    
    try:
        res = session.get(syndication_url, headers=headers, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            
            # Find all tweet text blocks
            for article in soup.find_all(["article", "div", "p"]):
                txt = article.get_text(separator=" ").strip()
                if "bms" in txt.lower() or "tickets sold" in txt.lower() or "toxic" in txt.lower():
                    if len(txt) > 25 and txt not in tweets_raw:
                        tweets_raw.append(txt)
                        
            # Also extract embedded raw __NEXT_DATA__ JSON if available
            script_data = soup.find("script", id="__NEXT_DATA__")
            if script_data:
                try:
                    js = json.loads(script_data.string)
                    entries = js.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
                    for e in entries:
                        t_text = e.get("content", {}).get("tweet", {}).get("full_text", "")
                        if t_text and t_text not in tweets_raw:
                            tweets_raw.append(t_text)
                except Exception:
                    pass
                    
        print(f"Found {len(tweets_raw)} relevant tracking posts from @{TARGET_HANDLE}.")

    except Exception as e:
        print(f"Syndication fetch error: {e}")

    # Read existing rows to prevent duplicate inserts
    existing_records = sheet.col_values(6)
    rows_to_append = []

    for text in tweets_raw:
        clean_text = " ".join(text.split())
        movie, time_slot, hourly, total = extract_bms_metrics(clean_text)
        
        # Only log posts with ticket data
        if hourly > 0 or total > 0 or "toxic" in clean_text.lower():
            # Check for duplicate
            snippet = clean_text[:50]
            if not any(snippet in str(r) for r in existing_records):
                rows_to_append.append([
                    now_ist,
                    movie,
                    time_slot,
                    hourly,
                    total,
                    clean_text
                ])
                print(f"-> [{movie}] {time_slot} | Hourly: {hourly} | Total: {total}")

    # 3. Append to Sheet
    if rows_to_append:
        print(f"\n3. Writing {len(rows_to_append)} rows to Google Sheet tab '{SHEET_TAB_NAME}'...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet tab updated.")
    else:
        print("All latest posts are already logged in Google Sheet.")

if __name__ == "__main__":
    run()
