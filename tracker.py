import os
import re
import json
import base64
from datetime import datetime

import pytz
import gspread

from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)

# First test: exact Toxic show from our HAR
EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"
DATE_CODE = "20260826"

CITY = "mumbai"

SEAT_URL = (
    f"https://in.bookmyshow.com/movies/{CITY}/seat-layout/"
    f"{EVENT_CODE}/{VENUE_CODE}/{SESSION_ID}/{DATE_CODE}"
)

SHEET_TAB_NAME = "Toxic_BMS_Test"


# ============================================================
# GOOGLE SHEETS
# ============================================================

def init_google_sheet():

    if not GCP_SA_KEY:
        raise ValueError(
            "Missing GCP_SA_KEY_B64 or GCP_SA_KEY"
        )

    raw_data = GCP_SA_KEY.strip()

    if raw_data.startswith("{"):
        sa_json = json.loads(raw_data)

    else:
        sa_json = json.loads(
            base64.b64decode(raw_data).decode("utf-8")
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = Credentials.from_service_account_info(
        sa_json,
        scopes=scopes
    )

    gc = gspread.authorize(creds)

    spreadsheet = gc.open_by_key(
        SPREADSHEET_ID
    )

    try:

        sheet = spreadsheet.worksheet(
            SHEET_TAB_NAME
        )

    except gspread.WorksheetNotFound:

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows="5000",
            cols="20"
        )

        headers = [
            "Timestamp IST",
            "Event Code",
            "Venue Code",
            "Session ID",
            "Date",
            "City",
            "Seat URL",
            "Potential Seat Elements",
            "Available",
            "Booked",
            "Selected",
            "Other Seat Elements"
        ]

        sheet.append_row(
            headers,
            value_input_option="USER_ENTERED"
        )

    return sheet


# ============================================================
# SEAT ANALYSIS
# ============================================================

def analyse_seats(page):

    available = 0
    booked = 0
    selected = 0
    other = 0

    seat_details = []

    # --------------------------------------------------------
    # Find elements with aria-label
    # --------------------------------------------------------

    elements = page.locator(
        "[aria-label]"
    )

    total_elements = elements.count()

    print(
        f"ARIA elements found: {total_elements}"
    )

    for i in range(total_elements):

        try:

            element = elements.nth(i)

            aria = element.get_attribute(
                "aria-label"
            )

            if not aria:
                continue

            text = aria.strip().lower()

            # Only inspect likely seat elements
            if not any(
                keyword in text
                for keyword in [
                    "seat",
                    "available",
                    "booked",
                    "selected"
                ]
            ):
                continue

            seat_details.append(
                {
                    "aria": aria,
                    "class": element.get_attribute(
                        "class"
                    ),
                    "data-seat-id": element.get_attribute(
                        "data-seat-id"
                    ),
                    "data-testid": element.get_attribute(
                        "data-testid"
                    )
                }
            )

            if "available" in text:
                available += 1

            elif "booked" in text:
                booked += 1

            elif "selected" in text:
                selected += 1

            else:
                other += 1

        except Exception:
            continue

    # --------------------------------------------------------
    # Additional selectors
    # --------------------------------------------------------

    selector_counts = {}

    selectors = [
        '[data-seat-id]',
        '[data-testid*="seat" i]',
        '[class*="seat" i]'
    ]

    for selector in selectors:

        try:

            selector_counts[selector] = (
                page.locator(
                    selector
                ).count()
            )

        except Exception:

            selector_counts[selector] = 0

    print()
    print("Seat selector counts:")

    for selector, count in selector_counts.items():

        print(
            f"{selector}: {count}"
        )

    return {
        "available": available,
        "booked": booked,
        "selected": selected,
        "other": other,
        "potential": len(seat_details),
        "seat_details": seat_details,
        "selector_counts": selector_counts
    }


# ============================================================
# BMS SEAT PAGE
# ============================================================

def fetch_bms_seat_data():

    print()
    print("=" * 70)
    print("OPENING BOOKMYSHOW")
    print("=" * 70)

    print(
        f"URL: {SEAT_URL}"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000
            },
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Network logging
        # ----------------------------------------------------

        def on_request(request):

            url = request.url.lower()

            if (
                "seatlayout" in url
                or "dotrans" in url
                or "seat" in url
            ):

                print()
                print("BMS REQUEST")
                print(request.method)
                print(request.url)

                if request.post_data:

                    print(
                        "POST DATA:"
                    )

                    print(
                        request.post_data[:2000]
                    )

        page.on(
            "request",
            on_request
        )

        def on_response(response):

            url = response.url.lower()

            if (
                "seatlayout" in url
                or "dotrans" in url
                or "seat" in url
            ):

                print()
                print("BMS RESPONSE")
                print(
                    response.status,
                    response.url
                )

        page.on(
            "response",
            on_response
        )

        # ----------------------------------------------------
        # Open page
        # ----------------------------------------------------

        try:

            page.goto(
                SEAT_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )

        except Exception as e:

            print(
                "Page load warning:",
                e
            )

        print()
        print(
            "Waiting 15 seconds for BMS..."
        )

        page.wait_for_timeout(
            15000
        )

        # ----------------------------------------------------
        # Page text
        # ----------------------------------------------------

        try:

            body_text = page.locator(
                "body"
            ).inner_text()

        except Exception:

            body_text = ""

        print()
        print("=" * 70)
        print("BMS PAGE TEXT")
        print("=" * 70)

        print(
            body_text[:5000]
        )

        # ----------------------------------------------------
        # Analyse seats
        # ----------------------------------------------------

        print()
        print("=" * 70)
        print("ANALYSING SEATS")
        print("=" * 70)

        seat_data = analyse_seats(
            page
        )

        # ----------------------------------------------------
        # Screenshot
        # ----------------------------------------------------

        try:

            page.screenshot(
                path="toxic_seat_layout.png",
                full_page=True
            )

            print()
            print(
                "Screenshot saved."
            )

        except Exception as e:

            print(
                "Screenshot error:",
                e
            )

        browser.close()

        return seat_data


# ============================================================
# GOOGLE SHEET LOGGING
# ============================================================

def save_to_google_sheet(
    seat_data
):

    sheet = init_google_sheet()

    ist = pytz.timezone(
        "Asia/Kolkata"
    )

    now = datetime.now(
        ist
    )

    row = [

        now.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        EVENT_CODE,

        VENUE_CODE,

        SESSION_ID,

        DATE_CODE,

        CITY,

        SEAT_URL,

        seat_data["potential"],

        seat_data["available"],

        seat_data["booked"],

        seat_data["selected"],

        seat_data["other"]
    ]

    sheet.append_row(
        row,
        value_input_option="USER_ENTERED"
    )

    print()
    print(
        "Google Sheet updated."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("TOXIC BMS SEAT TRACKER")
    print("=" * 70)

    print(
        f"Event:   {EVENT_CODE}"
    )

    print(
        f"Venue:   {VENUE_CODE}"
    )

    print(
        f"Session: {SESSION_ID}"
    )

    print(
        f"Date:    {DATE_CODE}"
    )

    try:

        seat_data = fetch_bms_seat_data()

        print()
        print("=" * 70)
        print("RESULT")
        print("=" * 70)

        print(
            "Potential seats:",
            seat_data["potential"]
        )

        print(
            "Available:",
            seat_data["available"]
        )

        print(
            "Booked:",
            seat_data["booked"]
        )

        print(
            "Selected:",
            seat_data["selected"]
        )

        print(
            "Other:",
            seat_data["other"]
        )

        save_to_google_sheet(
            seat_data
        )

        print()
        print(
            "SUCCESS"
        )

    except Exception as e:

        print()
        print(
            "TRACKER ERROR:"
        )

        print(
            repr(e)
        )

        raise


if __name__ == "__main__":
    main()
