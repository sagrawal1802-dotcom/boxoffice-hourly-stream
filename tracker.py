import os
import json
import re
import datetime
from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
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
    
    # Target the very first worksheet directly to avoid tab name mismatch
    sheet = spreadsheet.get_worksheet(0)

    # Ensure header row exists
    header = sheet.row_values(1)
    if not header or header[0] != "Timestamp (IST)":
        sheet.insert_row([
            "Timestamp (IST)", "Movie Title", "Event Code", 
            "Language", "Tickets Sold (Last 1 Hr)", "Raw Status Text", "Scope"
        ], 1)

    session = requests.Session(impersonate="chrome120")
    unique_movies = {}

    print("2. Fetching active movies from public catalog...")
    
    # Source A: Fast Catalog Endpoint
    catalog_urls = [
        "https://in.bookmyshow.com/serv/v2/explore/movies?region=MUMBAI",
        "https://in.bookmyshow.com/serv/v2/explore/movies?region=NCR",
        "https://in.bookmyshow.com/serv/v2/explore/movies?region=BANG"
    ]
    
    for url in catalog_urls:
        try:
            res = session.get(url, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for item in data.get("movies", []):
                    code = item.get("code") or item.get("eventCode")
                    title = item.get("name") or item.get("title")
                    lang = item.get("lang") or item.get("language") or ""
                    if code and title and code not in unique_movies:
                        unique_movies[code] = {"title": title, "lang": lang}
        except Exception:
            pass

    # Source B: XML Sitemap Fallback (100% immune to anti-bot blocks)
    if len(unique_movies) == 0:
        print("Using public movie sitemap fallback...")
        try:
            sitemap_res = session.get("https://in.bookmyshow.com/sitemap/movies.xml", timeout=15)
            if sitemap_res.status_code == 200:
                matches = re.findall(r'<loc>https:\/\/in\.bookmyshow\.com\/movies\/[^\/]+\/([a-z0-9-]+)\/(ET\d{6,10})<\/loc>', sitemap_res.text)
                for slug, code in matches[:35]: # Pick top 35 active listings
                    title = slug.replace("-", " ").title()
                    unique_movies[code] = {"title": title, "lang": ""}
        except Exception as e:
            print(f"Sitemap error: {e}")

    print(f"Total movies found: {len(unique_movies)}")

    now_ist = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:00:00")
    rows_to_append = []

    print("3. Querying velocity counters...")
    for code, meta in unique_movies.items():
        tickets = 0
        raw_text = "No Trending Badge"
        
        # Check details endpoint
        try:
            d_res = session.get(f"https://in.bookmyshow.com/serv/v2/movies/{code}", timeout=8)
            if d_res.status_code == 200:
                details = d_res.json().get("movieDetails", {})
                label = (
                    details.get("bookingVelocity", {}).get("label") or
                    details.get("recentBookings", {}).get("text") or
                    details.get("trendingCount") or ""
                )
                if label:
                    raw_text = str(label)
                    tickets = parse_tickets(raw_text)
        except Exception:
            pass

        rows_to_append.append([
            now_ist, meta["title"], code, meta["lang"], tickets, raw_text, "All India"
        ])

    # 4. Append directly to Sheet
    if rows_to_append:
        print(f"Writing {len(rows_to_append)} rows to Google Sheets...")
        sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        print("Success! Google Sheet updated.")
    else:
        print("No rows generated.")

if __name__ == "__main__":
    run()
