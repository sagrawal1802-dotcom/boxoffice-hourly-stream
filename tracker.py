import os
import json
import re
import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"

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
    sheet = spreadsheet.get_worksheet(0)

    # Ensure headers exist
    header = sheet.row_values(1)
    if not header or header[0] != "Timestamp (IST)":
        sheet.insert_row([
            "Timestamp (IST)", "Movie Title", "Event Code", 
            "Tickets Sold (Last 1 Hr)", "Raw Status Text", "Scope"
        ], 1)

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    unique_movies = {}
    rows_to_append = []

    print("2. Starting browser session...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        # Step A: Discover active movies on the explore page
        print("Discovering active movies on BookMyShow...")
        try:
            page.goto("https://in.bookmyshow.com/explore/movies-mumbai", wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(3000)

            # Scroll down to load all dynamic cards
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(2000)

            # Find all links containing movie slugs and event codes (ET00XXXXXX)
            links = page.eval_on_selector_all(
                "a[href*='/movies/']",
                "elements => elements.map(el => el.href)"
            )

            for href in links:
                match = re.search(r'/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})', href, re.IGNORECASE)
                if match:
                    slug = match.group(1)
                    code = match.group(2)
                    if code not in unique_movies:
                        title = slug.replace("-", " ").title()
                        unique_movies[code] = {
                            "title": title,
                            "url": href,
                            "code": code
                        }
        except Exception as e:
            print(f"Error while browsing catalog: {e}")

        print(f"Discovered {len(unique_movies)} active movies.")

        # Step B: Visit each movie to check for hourly trending booking badges
        for code, meta in unique_movies.items():
            tickets = 0
            raw_text = "No Trending Badge"

            try:
                page.goto(meta["url"], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                body_text = page.inner_text("body")

                # Match patterns like: "15.2K tickets bought in last 1 hour", "850 booked in last 1 hr", "trending"
                v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)\s*(?:in\s+last|in\s+the\s+last)?\s*1\s*(?:hour|hr)', body_text, re.IGNORECASE)
                if not v_match:
                    v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', body_text, re.IGNORECASE)

                if v_match:
                    raw_text = v_match.group(0)
                    tickets = parse_tickets(v_match.group(1))

            except Exception as e:
                print(f"Error checking {meta['title']}: {e}")

            rows_to_append.append([
                now_ist, meta["title"], code, tickets, raw_text, "All India"
            ])
            print(f"-> {meta['title']}: {tickets} ({raw_text})")

        browser.close()

    # Step C: Write to Google Sheet
    if rows_to_append:
        print(f"\nWriting {len(rows_to_append)} rows to Google Sheets...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet has been populated.")
    else:
        print("No movie rows generated.")

if __name__ == "__main__":
    run()
