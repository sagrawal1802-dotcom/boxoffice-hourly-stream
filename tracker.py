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

    header = sheet.row_values(1)
    if not header or header[0] != "Timestamp (IST)":
        sheet.insert_row([
            "Timestamp (IST)", "Movie Title", "Event Code", 
            "Tickets Sold (Last 1 Hr)", "Raw Status Text", "Scope"
        ], 1)

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    unique_movies = {}
    network_velocity = {}
    rows_to_append = []

    print("2. Starting browser session...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        # METHOD 1: Universal Network Interceptor
        def on_response(response):
            try:
                if "json" in response.headers.get("content-type", ""):
                    text = response.text()
                    # Search for any bookingVelocity or ticket count keys in all JSON responses
                    matches = re.findall(r'\"(?:bookingVelocity|recentBookings|trendingCount|ticketCountLabel)\"\s*:\s*\{?[^\}]*\"?(?:label|text|count)?\"?\s*:?\s*\"?([^\",\}]+)', text, re.IGNORECASE)
                    for m in matches:
                        if any(k in m.lower() for k in ["bought", "booked", "ticket", "k"]):
                            for code in unique_movies:
                                if code in response.url or code in text:
                                    network_velocity[code] = m
            except Exception:
                pass

        page.on("response", on_response)

        # Discover Movies
        print("Discovering active movies...")
        try:
            page.goto("https://in.bookmyshow.com/explore/movies-mumbai", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            page.evaluate("window.scrollBy(0, 2000)")
            page.wait_for_timeout(1500)

            links = page.eval_on_selector_all("a", "elements => elements.map(el => el.getAttribute('href')).filter(Boolean)")
            for href in links:
                match = re.search(r'/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})', href, re.IGNORECASE)
                if match:
                    slug = match.group(1)
                    code = match.group(2)
                    if code not in unique_movies:
                        unique_movies[code] = {
                            "title": slug.replace("-", " ").title(),
                            "url": href if href.startswith("http") else f"https://in.bookmyshow.com{href}",
                            "code": code
                        }
        except Exception as e:
            print(f"Explore error: {e}")

        print(f"Found {len(unique_movies)} active movies. Extracting data via all strategies...")

        for code, meta in unique_movies.items():
            tickets = 0
            raw_text = "No Trending Badge"

            try:
                page.goto(meta["url"], wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)

                # METHOD 2: Check Network Intercepted Data
                if code in network_velocity:
                    raw_text = network_velocity[code]
                    tickets = parse_tickets(raw_text)

                # METHOD 3: DOM Selector & Badge Search
                if tickets == 0:
                    badges = page.eval_on_selector_all(
                        "span, div, p", 
                        "elements => elements.map(e => e.innerText).filter(t => t && (t.includes('bought') || t.includes('booked')))"
                    )
                    for b in badges:
                        m = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', b, re.IGNORECASE)
                        if m:
                            raw_text = b.strip()
                            tickets = parse_tickets(m.group(1))
                            break

                # METHOD 4: Full Page Regex & Next.js Embedded State
                if tickets == 0:
                    content = page.content()
                    m = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)\s*(?:in\s+last|in\s+the\s+last)?\s*1\s*(?:hour|hr)', content, re.IGNORECASE)
                    if not m:
                        m = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', content, re.IGNORECASE)
                    if m:
                        raw_text = m.group(0)
                        tickets = parse_tickets(m.group(1))

            except Exception as e:
                print(f"Error checking {meta['title']}: {e}")

            rows_to_append.append([now_ist, meta["title"], code, tickets, raw_text, "All India"])
            print(f"-> {meta['title']}: {tickets} ({raw_text})")

        browser.close()

    # Write to Sheet
    if rows_to_append:
        print(f"\nPushing {len(rows_to_append)} rows to Google Sheets...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Done! Data written to Google Sheet.")

if __name__ == "__main__":
    run()
