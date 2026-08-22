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
    velocity_data = {}  # event_code -> (tickets_count, raw_text)
    rows_to_append = []

    print("2. Launching browser with network interception...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        # Intercept background API JSON payloads directly
        def handle_response(response):
            url = response.url
            if ("explore" in url or "movie" in url or "velocity" in url or "analytics" in url) and "json" in response.headers.get("content-type", ""):
                try:
                    payload = response.json()
                    # Check for movieDetails / velocity objects
                    if isinstance(payload, dict):
                        # Pattern A: Direct movieDetails
                        details = payload.get("movieDetails") or payload.get("data") or payload
                        if isinstance(details, dict):
                            code = details.get("eventCode") or details.get("code") or details.get("EventCode")
                            label = (
                                details.get("bookingVelocity", {}).get("label")
                                or details.get("recentBookings", {}).get("text")
                                or details.get("trendingCount")
                                or ""
                            )
                            if code and label:
                                velocity_data[code] = (parse_tickets(label), str(label))
                except Exception:
                    pass

        page.on("response", handle_response)

        # Step A: Discover active movies on explore page
        print("Navigating to explore catalog...")
        try:
            page.goto("https://in.bookmyshow.com/explore/movies-mumbai", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Scroll down to trigger all dynamic cards
            page.evaluate("window.scrollBy(0, 2000)")
            page.wait_for_timeout(2000)

            links = page.eval_on_selector_all(
                "a",
                "elements => elements.map(el => el.getAttribute('href')).filter(Boolean)"
            )

            for href in links:
                match = re.search(r'/movies/[^/]+/([a-z0-9-]+)/(ET\d{6,10})', href, re.IGNORECASE)
                if match:
                    slug = match.group(1)
                    code = match.group(2)
                    if code not in unique_movies:
                        clean_title = slug.replace("-", " ").title()
                        full_url = href if href.startswith("http") else f"https://in.bookmyshow.com{href}"
                        unique_movies[code] = {
                            "title": clean_title,
                            "url": full_url,
                            "code": code
                        }
        except Exception as e:
            print(f"Error exploring catalog: {e}")

        print(f"Discovered {len(unique_movies)} active movies.")

        # Step B: Visit each movie page to allow the velocity widget to load
        for code, meta in unique_movies.items():
            tickets = 0
            raw_text = "No Velocity Badge"

            # Check if intercepted by network listener
            if code in velocity_data:
                tickets, raw_text = velocity_data[code]
            else:
                try:
                    page.goto(meta["url"], wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2500) # Give 2.5s for dynamic widgets to render

                    if code in velocity_data:
                        tickets, raw_text = velocity_data[code]
                    else:
                        # Scan rendered DOM elements for velocity text
                        text_content = page.content()
                        # Search for trending patterns (e.g., "12.5K tickets bought in last 1 hour" or "850 bought in last 24 hours")
                        v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)\s*(?:in\s+last|in\s+the\s+last)?\s*(\d+\s*(?:hour|hr|hours|hrs))', text_content, re.IGNORECASE)
                        if not v_match:
                            v_match = re.search(r'([\d\.]+[KMkm]?)\s*(?:tickets\s+bought|bought|booked)', text_content, re.IGNORECASE)

                        if v_match:
                            raw_text = v_match.group(0)
                            tickets = parse_tickets(v_match.group(1))

                except Exception as e:
                    print(f"Error visiting {meta['title']}: {e}")

            rows_to_append.append([
                now_ist, meta["title"], code, tickets, raw_text, "All India"
            ])
            print(f"-> {meta['title']}: {tickets} tickets ({raw_text})")

        browser.close()

    # Step C: Write to Google Sheets
    if rows_to_append:
        print(f"\nWriting {len(rows_to_append)} rows to Google Sheets...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet populated with velocity numbers.")
    else:
        print("No movie rows generated.")

if __name__ == "__main__":
    run()
