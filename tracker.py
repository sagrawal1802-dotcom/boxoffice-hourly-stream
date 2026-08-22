import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "FilmyView_Hourly"
TARGET_HANDLE = "filmy_view"

def parse_number(raw_str):
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

def parse_tweet_content(text):
    """
    Parses patterns like:
    #Toxic ROCK STEADY
    12-1pm Tickets sold on BMS - 14200
    Total from 6am - 125000
    """
    # 1. Movie name from hashtag or first line
    movie_match = re.search(r'#([A-Za-z0-9_]+)', text)
    movie = movie_match.group(1) if movie_match else "General Update"

    # 2. Time slot (e.g. 7-8am, 12-1pm, 8-9 PM)
    time_slot_match = re.search(r'(\d{1,2}(?::\d{2})?\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)', text)
    time_slot = time_slot_match.group(1) if time_slot_match else "Latest Update"

    # 3. Hourly tickets sold on BMS
    hourly_match = re.search(r'(?:tickets\s*sold\s*on\s*bms|hourly|1\s*hr|in\s*last\s*1\s*hr)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    if not hourly_match:
        hourly_match = re.search(r'(?:sold|booked)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    hourly_tickets = parse_number(hourly_match.group(1)) if hourly_match else 0

    # 4. Total/Cumulative tickets
    total_match = re.search(r'(?:total\s*from\s*6am|total\s*bms|total)[\s:-]*([0-9,KMkm\.]+)', text, re.IGNORECASE)
    total_tickets = parse_number(total_match.group(1)) if total_match else 0

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
            "Hourly Tickets (BMS)", "Total Cumulative (BMS)", "Raw Post Text", "Source Link"
        ], value_input_option="USER_ENTERED")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    parsed_posts = []

    print(f"2. Fetching recent BMS posts from @{TARGET_HANDLE} on X...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        # Check via Nitter / Public Syndication first to avoid login walls
        profile_urls = [
            f"https://nitter.net/{TARGET_HANDLE}",
            f"https://xcancel.com/{TARGET_HANDLE}",
            f"https://x.com/{TARGET_HANDLE}"
        ]

        raw_tweets = []
        for url in profile_urls:
            try:
                print(f"Checking {url}...")
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
                
                # Extract text from tweet cards
                tweets = page.eval_on_selector_all(
                    "article, div.tweet-content, div[data-testid='tweetText']",
                    "elements => elements.map(el => el.innerText)"
                )
                if tweets:
                    raw_tweets = tweets
                    print(f"Successfully retrieved {len(tweets)} recent posts.")
                    break
            except Exception as e:
                print(f"Error accessing {url}: {e}")

        browser.close()

    # Process and filter BMS tracking posts
    existing_records = sheet.col_values(6)  # Check raw text column to prevent duplicates

    for text in raw_tweets:
        if any(k in text.lower() for k in ["bms", "tickets sold", "booked", "hourly", "from 6am", "advance"]):
            movie, time_slot, hourly, total = parse_tweet_content(text)
            
            # Avoid duplicate inserts
            clean_snippet = text[:60].strip()
            if not any(clean_snippet in str(r) for r in existing_records):
                parsed_posts.append([
                    now_ist,
                    movie,
                    time_slot,
                    hourly,
                    total,
                    text.replace("\n", " ").strip(),
                    f"https://x.com/{TARGET_HANDLE}"
                ])
                print(f"-> [{movie}] {time_slot} | Hourly: {hourly} | Total: {total}")

    # 3. Write rows to Google Sheet
    if parsed_posts:
        print(f"\n3. Writing {len(parsed_posts)} updates to tab '{SHEET_TAB_NAME}'...")
        sheet.append_rows(parsed_posts, value_input_option="USER_ENTERED")
        print("Success! Google Sheet updated with @filmy_view updates.")
    else:
        print("No new BMS tracking posts found in this hourly cycle.")

if __name__ == "__main__":
    run()
