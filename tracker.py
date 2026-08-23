import os
import re
import json
import time
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from curl_cffi import requests


# ============================================================
# CONFIG
# ============================================================

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"

CITY = "mumbai"
REGION_CODE = "MUMBAI"
DATE_CODE = "20260826"

VENUE_CODE = "CSWO"
VENUE_NAME = "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai"

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

SHEET_NAME = "Toxic_CSWO"

# Event code used by BMS as the reference event.
REFERENCE_EVENT = "ET00513506"


# ============================================================
# BMS ENDPOINTS
# ============================================================

SHOWTIME_URL = (
    "https://in.bookmyshow.com/api/movies-data/v5/"
    "showtimes-by-event/primary-dynamic"
)

SEATLAYOUT_URL = (
    "https://in.bookmyshow.com/api/movies-data/"
    "seatlayout/v1/primary"
)


# ============================================================
# HEADERS
# ============================================================

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en-GB;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "referer": (
        "https://in.bookmyshow.com/movies/mumbai/"
        "toxic-a-fairy-tale-for-grown-ups/"
        f"buytickets/{REFERENCE_EVENT}/{DATE_CODE}"
        f"?etCodes=*&language=hindi"
        f"&refEventCode={REFERENCE_EVENT}"
    ),
    "sec-ch-ua": (
        '"Not=A?Brand";v="99", '
        '"Google Chrome";v="151", '
        '"Chromium";v="151"'
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "x-app-code": "WEB",
    "x-platform": "WEB",
    "x-platform-code": "WEB",
    "x-region-code": REGION_CODE,
    "x-region-slug": CITY,
    "x-location-selection": "manual",
    "x-latitude": "19.076",
    "x-longitude": "72.8777",
    "x-geohash": "te7",
}


# ============================================================
# SESSION
# ============================================================

session = requests.Session(
    impersonate="chrome"
)


# ============================================================
# GOOGLE SHEETS
# ============================================================

def connect_google_sheet():

    print()
    print("=" * 90)
    print("CONNECTING TO GOOGLE SHEETS")
    print("=" * 90)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = None

    b64_key = os.environ.get("GCP_SA_KEY_B64")

    if b64_key:

        import base64

        try:
            decoded = base64.b64decode(
                b64_key
            ).decode("utf-8")

            service_account_info = json.loads(
                decoded
            )

            credentials = (
                Credentials.from_service_account_info(
                    service_account_info,
                    scopes=scopes
                )
            )

        except Exception as e:

            print(
                "Could not decode GCP_SA_KEY_B64:",
                e
            )

    if credentials is None:

        raw_key = os.environ.get("GCP_SA_KEY")

        if raw_key:

            try:

                service_account_info = json.loads(
                    raw_key
                )

                credentials = (
                    Credentials.from_service_account_info(
                        service_account_info,
                        scopes=scopes
                    )
                )

            except Exception as e:

                print(
                    "Could not load GCP_SA_KEY:",
                    e
                )

    if credentials is None:

        if os.path.exists("credentials.json"):

            credentials = (
                Credentials.from_service_account_file(
                    "credentials.json",
                    scopes=scopes
                )
            )

        else:

            raise RuntimeError(
                "No Google credentials found. "
                "Set GCP_SA_KEY_B64 or GCP_SA_KEY."
            )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    try:

        sheet = spreadsheet.worksheet(
            SHEET_NAME
        )

    except gspread.WorksheetNotFound:

        print(
            f"Creating worksheet: {SHEET_NAME}"
        )

        sheet = spreadsheet.add_worksheet(
            title=SHEET_NAME,
            rows=10000,
            cols=20
        )

    print("Google Sheets connected.")

    return sheet


# ============================================================
# SHOWTIME API
# ============================================================

def get_showtime_data():

    print()
    print("=" * 90)
    print("REQUESTING BMS SHOWTIME DATA")
    print("=" * 90)

    params = {
        "etCodes": "*",
        "dateCode": DATE_CODE,
        "isDesktop": "true",
        "regionCode": REGION_CODE,
        "xLocationShared": "false",
        "memberId": "",
        "lsId": "",
        "subCode": "",
        "appCode": "WEB",
        "language": "hindi",
        "refEventCode": REFERENCE_EVENT,
    }

    print()
    print("Endpoint:")
    print(SHOWTIME_URL)

    print()
    print("Parameters:")
    print(json.dumps(
        params,
        indent=2
    ))

    for attempt in range(1, 4):

        try:

            print()
            print(
                f"Attempt {attempt}/3"
            )

            response = session.get(
                SHOWTIME_URL,
                params=params,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP status:",
                response.status_code
            )

            print(
                "Response size:",
                len(response.content)
            )

            if response.status_code == 200:

                try:

                    data = response.json()

                    print(
                        "BMS showtime JSON received."
                    )

                    return data

                except Exception as e:

                    print(
                        "JSON parsing failed:",
                        e
                    )

            else:

                print(
                    "Response preview:"
                )

                print(
                    response.text[:1000]
                )

        except Exception as e:

            print(
                "Request error:",
                e
            )

        time.sleep(3)

    return None


# ============================================================
# DISCOVER CSWO SHOWS
# ============================================================

def discover_cswo_shows(data):

    print()
    print("=" * 90)
    print("DISCOVERING CSWO SHOWS")
    print("=" * 90)

    discovered = []

    if not data:
        return discovered

    widgets = (
        data
        .get("data", {})
        .get("showtimeWidgets", [])
    )

    print(
        "Showtime widgets:",
        len(widgets)
    )

    for widget in widgets:

        widget_data = (
            widget.get("data", [])
        )

        for level1 in widget_data:

            if not isinstance(
                level1,
                dict
            ):
                continue

            for level2 in level1.get(
                "data",
                []
            ):

                if not isinstance(
                    level2,
                    dict
                ):
                    continue

                additional = level2.get(
                    "additionalData",
                    {}
                )

                venue_code = additional.get(
                    "venueCode"
                )

                if venue_code != VENUE_CODE:
                    continue

                venue_name = additional.get(
                    "venueName",
                    VENUE_NAME
                )

                sections = level2.get(
                    "showtimesSections",
                    []
                )

                for section in sections:

                    section_text = ""

                    try:

                        section_text = (
                            section
                            .get("text", [])[0]
                            .get("components", [])[0]
                            .get("text", "")
                        )

                    except Exception:
                        pass

                    section_format = (
                        section_text
                    )

                    section_event_code = (
                        section
                        .get("additionalData", {})
                        .get(
                            "eventCode"
                        )
                    )

                    for show in section.get(
                        "showtimes",
                        []
                    ):

                        show_data = show.get(
                            "additionalData",
                            {}
                        )

                        cta = show.get(
                            "cta",
                            {}
                        )

                        analytics = cta.get(
                            "analytics",
                            {}
                        )

                        session_id = (
                            show_data.get(
                                "sessionId"
                            )
                        )

                        show_time = (
                            show_data.get(
                                "showTime"
                            )
                            or show.get(
                                "title"
                            )
                        )

                        show_time_code = (
                            show_data.get(
                                "showTimeCode"
                            )
                        )

                        show_date_time = (
                            show_data.get(
                                "showDateTime"
                            )
                        )

                        event_code = (
                            section_event_code
                            or show_data.get(
                                "eventCode"
                            )
                            or analytics.get(
                                "eventCode"
                            )
                        )

                        fmt = (
                            analytics.get(
                                "format"
                            )
                            or show_data.get(
                                "attributes"
                            )
                            or section_format
                        )

                        record = {
                            "movie": MOVIE_NAME,
                            "city": CITY,
                            "venue_code": VENUE_CODE,
                            "venue_name": venue_name,
                            "date": DATE_CODE,
                            "event_code": event_code,
                            "format": fmt,
                            "section": section_format,
                            "session_id": str(
                                session_id
                            ) if session_id else "",
                            "show_time": show_time,
                            "show_time_code": (
                                show_time_code
                                or ""
                            ),
                            "show_date_time": (
                                show_date_time
                                or ""
                            ),
                            "availability_status": (
                                show_data.get(
                                    "availStatus",
                                    ""
                                )
                            ),
                        }

                        if (
                            record["session_id"]
                            and record["event_code"]
                        ):

                            discovered.append(
                                record
                            )

    # --------------------------------------------------------
    # DEDUPLICATE
    # --------------------------------------------------------

    unique = {}

    for record in discovered:

        key = (
            record["event_code"],
            record["session_id"],
        )

        unique[key] = record

    discovered = list(
        unique.values()
    )

    discovered.sort(
        key=lambda x: (
            x["format"],
            x["show_time"],
            x["session_id"],
        )
    )

    return discovered


# ============================================================
# PRINT SHOW SUMMARY
# ============================================================

def print_show_summary(shows):

    print()
    print("=" * 90)
    print("CSWO SHOW SUMMARY")
    print("=" * 90)

    if not shows:

        print("NO CSWO SHOWS FOUND.")

        return

    current_format = None

    for show in shows:

        if show["format"] != current_format:

            current_format = show["format"]

            print()
            print(
                f"FORMAT: {current_format}"
            )

            print(
                "-" * 90
            )

        print(
            f"{show['show_time']:10} | "
            f"{show['event_code']} | "
            f"Session {show['session_id']}"
        )

    print()
    print(
        "TOTAL CSWO SHOWS:",
        len(shows)
    )

    event_codes = sorted(
        set(
            x["event_code"]
            for x in shows
        )
    )

    print(
        "EVENT CODES:",
        ", ".join(event_codes)
    )


# ============================================================
# SEAT LAYOUT
# ============================================================

def get_seat_layout(show):

    event_code = show[
        "event_code"
    ]

    session_id = show[
        "session_id"
    ]

    print()
    print(
        f"SEAT LAYOUT: "
        f"{show['format']} "
        f"{show['show_time']} "
        f"Session {session_id}"
    )

    params = {
        "eventCode": event_code,
        "dateCode": DATE_CODE,
        "regionCode": REGION_CODE,
        "venueCode": VENUE_CODE,
    }

    # BMS endpoint returns the venue-level layout.
    # The session is identified by the subsequent
    # show/session URL context.

    for attempt in range(1, 4):

        try:

            response = session.get(
                SEATLAYOUT_URL,
                params=params,
                headers=HEADERS,
                timeout=30
            )

            print(
                "Seat API:",
                response.status_code,
                "|",
                len(response.content),
                "bytes"
            )

            if response.status_code == 200:

                return response.json()

            print(
                response.text[:500]
            )

        except Exception as e:

            print(
                "Seat API error:",
                e
            )

        time.sleep(2)

    return None


# ============================================================
# PARSE SEATS
# ============================================================

def parse_seats(layout, show):

    rows = []

    if not layout:
        return rows

    event_data = (
        layout
        .get("data", {})
        .get("eventData", {})
    )

    actual_event_code = event_data.get(
        "eventCode",
        show["event_code"]
    )

    event_name = event_data.get(
        "eventName",
        ""
    )

    seat_data = (
        layout
        .get("data", {})
    )

    # --------------------------------------------------------
    # Find seat tokens recursively
    # --------------------------------------------------------

    def walk(obj):

        if isinstance(
            obj,
            dict
        ):

            for key, value in obj.items():

                if isinstance(
                    value,
                    str
                ):

                    # BMS seat tokens:
                    # A1052+1
                    # B2049+7
                    # etc.
                    matches = re.findall(
                        r"\b([A-E])([12]\d+)\+(\d+)\b",
                        value
                    )

                    for match in matches:

                        row_letter = match[0]
                        seat_code = (
                            row_letter
                            + match[1]
                        )
                        seat_number = match[2]

                        status = (
                            "SOLD"
                            if seat_code[
                                1:2
                            ] == "2"
                            else "AVAILABLE"
                        )

                        rows.append({
                            "timestamp": datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "event_code": actual_event_code,
                            "movie": MOVIE_NAME,
                            "city": CITY,
                            "venue_code": VENUE_CODE,
                            "venue_name": VENUE_NAME,
                            "date": DATE_CODE,
                            "format": show["format"],
                            "show_time": show["show_time"],
                            "session_id": show["session_id"],
                            "event_name": event_name,
                            "seat_token": (
                                row_letter
                                + match[1]
                                + "+"
                                + match[2]
                            ),
                            "seat_code": seat_code,
                            "seat_number": seat_number,
                            "status": status,
                        })

                else:

                    walk(value)

        elif isinstance(
            obj,
            list
        ):

            for item in obj:
                walk(item)

    walk(seat_data)

    # --------------------------------------------------------
    # Deduplicate
    # --------------------------------------------------------

    unique = {}

    for row in rows:

        key = (
            row["event_code"],
            row["session_id"],
            row["seat_token"],
        )

        unique[key] = row

    return list(
        unique.values()
    )


# ============================================================
# GOOGLE SHEETS WRITE
# ============================================================

def write_sheet(
    sheet,
    shows,
    seat_rows
):

    print()
    print("=" * 90)
    print("WRITING TO GOOGLE SHEETS")
    print("=" * 90)

    headers = [
        "timestamp",
        "event_code",
        "movie",
        "city",
        "venue_code",
        "venue_name",
        "date",
        "format",
        "show_time",
        "session_id",
        "event_name",
        "seat_token",
        "seat_code",
        "seat_number",
        "status",
    ]

    # Clear existing data
    sheet.clear()

    all_rows = [
        headers
    ]

    for row in seat_rows:

        all_rows.append([
            row.get(
                "timestamp",
                ""
            ),
            row.get(
                "event_code",
                ""
            ),
            row.get(
                "movie",
                ""
            ),
            row.get(
                "city",
                ""
            ),
            row.get(
                "venue_code",
                ""
            ),
            row.get(
                "venue_name",
                ""
            ),
            row.get(
                "date",
                ""
            ),
            row.get(
                "format",
                ""
            ),
            row.get(
                "show_time",
                ""
            ),
            row.get(
                "session_id",
                ""
            ),
            row.get(
                "event_name",
                ""
            ),
            row.get(
                "seat_token",
                ""
            ),
            row.get(
                "seat_code",
                ""
            ),
            row.get(
                "seat_number",
                ""
            ),
            row.get(
                "status",
                ""
            ),
        ])

    if len(all_rows) > 1:

        sheet.update(
            range_name="A1",
            values=all_rows
        )

        print(
            "Written",
            len(seat_rows),
            "seat records."
        )

    else:

        sheet.update(
            range_name="A1",
            values=[headers]
        )

        print(
            "No seat records."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 90)
    print("BMS TOXIC CSWO ALL-FORMAT TRACKER")
    print("=" * 90)

    print(
        "Timestamp :",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print(
        "Movie     :",
        MOVIE_NAME
    )

    print(
        "City      :",
        CITY
    )

    print(
        "Venue     :",
        VENUE_CODE
    )

    print(
        "Date      :",
        DATE_CODE
    )

    # --------------------------------------------------------
    # GOOGLE
    # --------------------------------------------------------

    sheet = connect_google_sheet()

    # --------------------------------------------------------
    # SHOW DISCOVERY
    # --------------------------------------------------------

    data = get_showtime_data()

    if not data:

        print()
        print(
            "FAILED: Could not retrieve BMS showtime data."
        )

        return

    shows = discover_cswo_shows(
        data
    )

    print_show_summary(
        shows
    )

    if not shows:

        print()
        print(
            "STOPPING: No CSWO shows discovered."
        )

        return

    # --------------------------------------------------------
    # SEAT TRACKING
    # --------------------------------------------------------

    all_seats = []

    for index, show in enumerate(
        shows,
        start=1
    ):

        print()
        print(
            f"[{index}/{len(shows)}] "
            f"{show['format']} | "
            f"{show['show_time']} | "
            f"{show['session_id']}"
        )

        layout = get_seat_layout(
            show
        )

        if layout:

            seats = parse_seats(
                layout,
                show
            )

            print(
                "Seats parsed:",
                len(seats)
            )

            all_seats.extend(
                seats
            )

        else:

            print(
                "No seat layout returned."
            )

        # Small pause between requests
        time.sleep(1)

    # --------------------------------------------------------
    # FINAL DEDUPLICATION
    # --------------------------------------------------------

    unique = {}

    for row in all_seats:

        key = (
            row["event_code"],
            row["session_id"],
            row["seat_token"],
        )

        unique[key] = row

    all_seats = list(
        unique.values()
    )

    # --------------------------------------------------------
    # SHEET
    # --------------------------------------------------------

    write_sheet(
        sheet,
        shows,
        all_seats
    )

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 90)
    print("FINAL SUMMARY")
    print("=" * 90)

    print(
        "Shows discovered :",
        len(shows)
    )

    print(
        "Seat records      :",
        len(all_seats)
    )

    print()
    print(
        "Event/format breakdown:"
    )

    breakdown = {}

    for show in shows:

        key = (
            show["event_code"],
            show["format"],
        )

        breakdown[key] = (
            breakdown.get(key, 0)
            + 1
        )

    for key, count in sorted(
        breakdown.items()
    ):

        print(
            f"{key[0]} | "
            f"{key[1]} | "
            f"{count} shows"
        )

    print()
    print(
        "BMS TOXIC CSWO TRACKER COMPLETED"
    )


if __name__ == "__main__":
    main()
