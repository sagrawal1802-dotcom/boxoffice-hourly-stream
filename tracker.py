import os
import json
import re
import datetime
import time

from curl_cffi import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
SHEET_TAB_NAME = "FilmyView_Hourly"
TARGET_HANDLE = "filmy_view"

X_TIMELINE_URL = (
    f"https://syndication.twitter.com/"
    f"srv/timeline-profile/screen-name/{TARGET_HANDLE}"
)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ============================================================
# NUMBER PARSER
# ============================================================

def parse_num(value):
    if value is None:
        return 0

    value = str(value).strip()

    if not value:
        return 0

    value = value.replace(",", "").replace(" ", "").upper()

    multiplier = 1

    if value.endswith("K"):
        multiplier = 1000
        value = value[:-1]

    elif value.endswith("M"):
        multiplier = 1000000
        value = value[:-1]

    elif value.endswith("L"):
        multiplier = 100000
        value = value[:-1]

    try:
        return int(float(value) * multiplier)
    except (ValueError, TypeError):
        return 0


# ============================================================
# CLEAN TEXT
# ============================================================

def clean_text(text):
    if not text:
        return ""

    soup = BeautifulSoup(str(text), "html.parser")

    text = soup.get_text(" ", strip=True)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# EXTRACT __NEXT_DATA__
# ============================================================

def extract_next_data(html):

    soup = BeautifulSoup(html, "html.parser")

    script = soup.find(
        "script",
        id="__NEXT_DATA__"
    )

    if not script:
        print("ERROR: __NEXT_DATA__ not found.")
        return None

    try:
        return json.loads(script.string or script.get_text())
    except Exception as e:
        print(f"ERROR: Could not parse __NEXT_DATA__: {e}")
        return None


# ============================================================
# FETCH X TIMELINE
# ============================================================

def fetch_x_posts():

    print(f"Fetching X timeline for @{TARGET_HANDLE}...")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    session = requests.Session(
        impersonate="chrome"
    )

    for attempt in range(1, 4):

        print(f"X timeline attempt {attempt}/3")

        try:

            response = session.get(
                X_TIMELINE_URL,
                headers=headers,
                timeout=20,
            )

            print(
                f"HTTP status: {response.status_code}"
            )

            print(
                f"Response size: {len(response.text)} bytes"
            )

            if response.status_code != 200:
                time.sleep(2)
                continue

            if "__NEXT_DATA__" not in response.text:

                print(
                    "WARNING: __NEXT_DATA__ not found "
                    "in X response."
                )

                # Save a small diagnostic sample
                print(
                    "Response beginning:"
                )
                print(response.text[:500])

                time.sleep(2)
                continue

            data = extract_next_data(
                response.text
            )

            if not data:
                time.sleep(2)
                continue

            page_props = (
                data
                .get("props", {})
                .get("pageProps", {})
            )

            timeline = (
                page_props
                .get("timeline", {})
            )

            entries = timeline.get(
                "entries",
                []
            )

            print(
                f"Timeline entries found: "
                f"{len(entries)}"
            )

            posts = []

            for entry in entries:

                # Some entries are not tweets.
                # Ignore them.
                if not isinstance(entry, dict):
                    continue

                if entry.get("type") != "tweet":
                    continue

                tweet_id = entry.get(
                    "entry_id",
                    ""
                )

                # Extract tweet information.
                # Different versions of the endpoint
                # can expose different structures.
                tweet = entry.get(
                    "content",
                    {}
                )

                if not isinstance(tweet, dict):
                    tweet = {}

                # Search recursively for useful fields.
                text = find_first_value(
                    entry,
                    [
                        "text",
                        "full_text",
                    ]
                )

                if not text:
                    text = ""

                text = clean_text(text)

                if not text:
                    continue

                posts.append({
                    "id": tweet_id,
                    "text": text,
                })

            # If the direct structure didn't work,
            # perform a broader recursive extraction.
            if not posts:

                print(
                    "Standard tweet extraction returned "
                    "0 posts. Trying fallback extraction..."
                )

                posts = extract_posts_recursively(
                    entries
                )

            print(
                f"Usable posts found: {len(posts)}"
            )

            if posts:
                return posts

        except Exception as e:

            print(
                f"X timeline attempt {attempt} failed: "
                f"{repr(e)}"
            )

        time.sleep(3)

    print(
        "ERROR: Could not retrieve X timeline."
    )

    return []


# ============================================================
# RECURSIVE FIELD FINDER
# ============================================================

def find_first_value(obj, keys):

    if isinstance(obj, dict):

        for key in keys:

            value = obj.get(key)

            if isinstance(value, str) and value.strip():

                return value

        for value in obj.values():

            result = find_first_value(
                value,
                keys
            )

            if result:
                return result

    elif isinstance(obj, list):

        for item in obj:

            result = find_first_value(
                item,
                keys
            )

            if result:
                return result

    return None


# ============================================================
# FALLBACK POST EXTRACTION
# ============================================================

def extract_posts_recursively(entries):

    posts = []

    visited_ids = set()

    def walk(obj):

        if isinstance(obj, dict):

            # Look for tweet-like objects.
            text = obj.get("text")

            if (
                isinstance(text, str)
                and text.strip()
            ):

                entry_id = (
                    obj.get("entry_id")
                    or obj.get("rest_id")
                    or obj.get("id")
                    or ""
                )

                text_clean = clean_text(text)

                if text_clean:

                    unique_key = (
                        str(entry_id)
                        + "|"
                        + text_clean
                    )

                    if unique_key not in visited_ids:

                        visited_ids.add(
                            unique_key
                        )

                        posts.append({
                            "id": str(entry_id),
                            "text": text_clean,
                        })

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    walk(entries)

    # Remove duplicates
    unique = []
    seen_text = set()

    for post in posts:

        text = post["text"]

        if text not in seen_text:

            seen_text.add(text)
            unique.append(post)

    return unique


# ============================================================
# EXTRACT BMS METRICS
# ============================================================

def extract_bms_metrics(text):

    text = clean_text(text)

    # --------------------------------------------------------
    # MOVIE
    # --------------------------------------------------------

    movie_match = re.search(
        r"#([A-Za-z0-9_]+)",
        text
    )

    movie = (
        movie_match.group(1)
        if movie_match
        else "Toxic"
    )

    # --------------------------------------------------------
    # TIME WINDOW
    # --------------------------------------------------------

    time_patterns = [

        # 2-3 PM
        r"\b(\d{1,2}(?::\d{2})?\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))\b",

        # 2 PM - 3 PM
        r"\b(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))\b",

        # 2-3pm
        r"\b(\d{1,2}\s*[-–]\s*\d{1,2}\s*(?:am|pm))\b",
    ]

    time_slot = "Hourly Update"

    for pattern in time_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            time_slot = (
                match.group(1)
                .strip()
            )

            break

    # --------------------------------------------------------
    # HOURLY TICKETS
    # --------------------------------------------------------

    hourly_tickets = 0

    hourly_patterns = [

        # 2,104 tickets sold
        r"([\d,.]+[KM]?)\s*tickets?\s*(?:sold|booked)",

        # sold 2,104 tickets
        r"(?:sold|booked)\s*([\d,.]+[KM]?)\s*tickets?",

        # hourly: 2,104
        r"hourly[\s:=\-]*([\d,.]+[KM]?)",

        # hourly tickets: 2,104
        r"hourly\s*tickets?[\s:=\-]*([\d,.]+[KM]?)",

        # BMS: 2,104
        r"\bBMS[\s:=\-]+([\d,.]+[KM]?)",
    ]

    for pattern in hourly_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            hourly_tickets = parse_num(
                match.group(1)
            )

            if hourly_tickets:
                break

    # --------------------------------------------------------
    # CUMULATIVE TOTAL
    # --------------------------------------------------------

    total_tickets = 0

    total_patterns = [

        # Total: 24,531
        r"\btotal\s*(?:tickets?)?\s*[:=-]\s*([\d,.]+[KM]?)",

        # Total BMS: 24,531
        r"\btotal\s+BMS\s*[:=-]\s*([\d,.]+[KM]?)",

        # Total tickets booked: 24,531
        r"\btotal\s+tickets?\s*(?:booked|sold)?\s*[:=-]\s*([\d,.]+[KM]?)",

        # Total from 6am: 24,531
        r"\btotal\s+from\s+6\s*am\s*[:=-]\s*([\d,.]+[KM]?)",
    ]

    for pattern in total_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            total_tickets = parse_num(
                match.group(1)
            )

            if total_tickets:
                break

    return (
        movie,
        time_slot,
        hourly_tickets,
        total_tickets
    )


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_google_sheet():

    print(
        "1. Connecting to Google Sheets..."
    )

    key = os.environ.get(
        "GCP_SA_KEY"
    )

    if not key:
        raise RuntimeError(
            "GCP_SA_KEY secret is missing."
        )

    try:

        sa_info = json.loads(key)

    except json.JSONDecodeError as e:

        raise RuntimeError(
            "GCP_SA_KEY is not valid JSON."
        ) from e

    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets"
        ],
    )

    client = gspread.authorize(
        creds
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    try:

        sheet = spreadsheet.worksheet(
            SHEET_TAB_NAME
        )

    except gspread.exceptions.WorksheetNotFound:

        print(
            f"Creating worksheet "
            f"'{SHEET_TAB_NAME}'..."
        )

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=1000,
            cols=7,
        )

        sheet.append_row(
            [
                "Logged Timestamp (IST)",
                "Movie / Hashtag",
                "Time Window",
                "Hourly Tickets (BMS)",
                "Total Cumulative (BMS)",
                "Raw Post Text",
                "X Post ID",
            ],
            value_input_option="USER_ENTERED",
        )

    return sheet


# ============================================================
# MAIN
# ============================================================

def run():

    sheet = connect_google_sheet()

    print()
    print(
        f"2. Fetching recent tweets from "
        f"@{TARGET_HANDLE}..."
    )

    posts = fetch_x_posts()

    if not posts:

        print(
            "No posts could be retrieved from X."
        )

        return

    now_ist = datetime.datetime.now(
        datetime.timezone.utc
    ).astimezone(
        IST
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # READ EXISTING DATA
    # --------------------------------------------------------

    print(
        "Reading existing Google Sheet records..."
    )

    try:

        existing_values = sheet.get_all_values()

    except Exception as e:

        print(
            f"Could not read existing rows: {e}"
        )

        existing_values = []

    existing_ids = set()
    existing_texts = set()

    for row in existing_values[1:]:

        if len(row) >= 7:

            post_id = str(
                row[6]
            ).strip()

            if post_id:
                existing_ids.add(
                    post_id
                )

        if len(row) >= 6:

            raw_text = str(
                row[5]
            ).strip()

            if raw_text:
                existing_texts.add(
                    raw_text
                )

    # --------------------------------------------------------
    # PROCESS POSTS
    # --------------------------------------------------------

    rows_to_append = []

    for post in posts:

        post_id = str(
            post.get("id", "")
        ).strip()

        text = clean_text(
            post.get("text", "")
        )

        if not text:
            continue

        # Only track relevant posts.
        lower = text.lower()

        if not any(
            word in lower
            for word in [
                "bms",
                "tickets",
                "ticket",
                "booked",
                "sold",
                "toxic",
                "6am",
            ]
        ):
            continue

        # Duplicate prevention
        if post_id and post_id in existing_ids:

            print(
                f"Skipping existing post: "
                f"{post_id}"
            )

            continue

        if text in existing_texts:

            print(
                "Skipping duplicate post text."
            )

            continue

        (
            movie,
            time_slot,
            hourly,
            total
        ) = extract_bms_metrics(
            text
        )

        # Don't log completely unparseable posts
        # unless they clearly contain BMS information.
        if (
            hourly == 0
            and total == 0
            and "bms" not in lower
        ):
            print(
                "Skipping post because no BMS "
                "numbers could be extracted:"
            )

            print(text)

            continue

        rows_to_append.append(
            [
                now_ist,
                movie,
                time_slot,
                hourly,
                total,
                text,
                post_id,
            ]
        )

        print()
        print(
            f"-> NEW POST FOUND"
        )
        print(
            f"Movie: {movie}"
        )
        print(
            f"Time: {time_slot}"
        )
        print(
            f"Hourly BMS: {hourly}"
        )
        print(
            f"Cumulative BMS: {total}"
        )
        print(
            f"Post ID: {post_id}"
        )
        print(
            f"Text: {text}"
        )

    # --------------------------------------------------------
    # WRITE TO SHEET
    # --------------------------------------------------------

    if rows_to_append:

        print()
        print(
            f"3. Writing "
            f"{len(rows_to_append)} new rows "
            f"to '{SHEET_TAB_NAME}'..."
        )

        sheet.append_rows(
            rows_to_append,
            value_input_option="USER_ENTERED",
        )

        print(
            "SUCCESS: Google Sheet updated."
        )

    else:

        print()
        print(
            "No new hourly BMS updates "
            "found in this run."
        )


if __name__ == "__main__":
    run()
