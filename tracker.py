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
    # Match Movie Name / Hashtag
    movie_match = re.search(r'#([A-Za-z0-9_]+)', text)
    movie = movie_match.group(1) if movie_match else "Toxic"

    # Match Time Window (e.g., 9-10am, 12-1pm, 6-7 PM)
    time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', text)
    time_slot = time_match.group(1) if time_match else "Hourly Update"

    # Match Hourly BMS Sold Tickets
    hourly_match = re.search(r'(?:tickets\s*sold\s*on\s*bms|hourly|bms)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    if not hourly_match:
        hourly_match = re.search(r'(?:sold|booked)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    hourly_tickets = parse_num(hourly_match.group(1)) if hourly_match else 0

    # Match Cumulative Total Tickets
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

    print(f"2. Fetching recent tweets from @{TARGET_HANDLE}...")
    
    # Public mirror gateways that serve raw timeline XML/JSON
    sources = [
        f"https://nitter.poast.org/{TARGET_HANDLE}/rss",
        f"https://nitter.privacydev.net/{TARGET_HANDLE}/rss",
        f"https://nitter.catsarch.com/{TARGET_HANDLE}/rss",
        f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{TARGET_HANDLE}"
    ]

    raw_posts = []

    for url in sources:
        try:
            print(f"Trying source: {url}")
            res = session.get(url, timeout=10)
            if res.status_code == 200 and len(res.text) > 200:
                # RSS XML parser
                if "rss" in url or "xml" in res.text[:100]:
                    soup = BeautifulSoup(res.text, "xml")
                    items = soup.find_all("item")
                    for item in items:
                        desc = item.find("description")
                        title = item.find("title")
                        txt = (desc.text if desc else "") or (title.text if title else "")
                        if txt:
                            # Strip HTML inside RSS descriptions
                            clean_t = BeautifulSoup(txt, "html.parser").get_text(separator=" ")
                            raw_posts.append(clean_t)
                else:
                    # HTML fallback parser
                    soup = BeautifulSoup(res.text, "html.parser")
                    for tag in soup.find_all(["p", "div", "article"]):
                        t = tag.get_text(separator=" ").strip()
                        if len(t) > 30:
                            raw_posts.append(t)

                if len(raw_posts) > 0:
                    print(f"Successfully collected {len(raw_posts)} posts from {url}")
                    break
        except Exception as e:
            print(f"Source {url} failed: {e}")

    # Read existing entries to prevent duplicates
    existing_records = sheet.col_values(6)
    rows_to_append = []

    for post in raw_posts:
        clean_text = " ".join(post.split())
        # Filter for BMS tracking or movie metrics
        if any(w in clean_text.lower() for w in ["bms", "tickets", "booked", "sold", "toxic", "6am"]):
            movie, time_slot, hourly, total = extract_bms_metrics(clean_text)
            
            # Duplicate prevention check
            snippet = clean_text[:45]
            if not any(snippet in str(r) for r in existing_records):
                rows_to_append.append([
                    now_ist,
                    movie,
                    time_slot,
                    hourly,
                    total,
                    clean_text
                ])
                print(f"-> Logged: [{movie}] {time_slot} | Hourly: {hourly} | Cumulative: {total}")

    # 3. Append to Sheet
    if rows_to_append:
        print(f"\n3. Writing {len(rows_to_append)} rows to '{SHEET_TAB_NAME}'...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet tab updated.")
    else:
        print("No new hourly BMS updates found in this run.")

if __name__ == "__main__":
    run()
