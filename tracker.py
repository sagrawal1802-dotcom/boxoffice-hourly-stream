import os
import json
import base64
from datetime import datetime

import pytz
import gspread
from curl_cffi import requests
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIG
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)

PROXY_URL = os.environ.get("PROXY_URL")

SHEET_TAB_NAME = "Toxic_BMS_Raw"


# ============================================================
# TOXIC TEST SHOW FROM HAR
# ============================================================

EVENT_CODE = "ET00379311"
VENUE_CODE = "CSWO"
SESSION_ID = "15925"

DATE_CODE = "20260826"

CITY = "mumbai"


# ============================================================
# GOOGLE SHEETS
# ============================================================

def get_google_sheet():

    if not GCP_SA_KEY:
        raise ValueError(
            "GCP_SA_KEY_B64 / GCP_SA_KEY is missing"
        )

    raw = GCP_SA_KEY.strip()

    if raw.startswith("{"):
        service_account = json.loads(raw)
    else:
        service_account = json.loads(
            base64.b64decode(raw).decode("utf-8")
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials = (
        Credentials
        .from_service_account_info(
            service_account,
            scopes=scopes
        )
    )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        SPREADSHEET_ID
    )

    try:

        sheet = spreadsheet.worksheet(
            SHEET_TAB_NAME
        )

    except gspread.WorksheetNotFound:

        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=5000,
            cols=20
        )

        sheet.append_row([
            "Timestamp IST",
            "Event Code",
            "Venue Code",
            "Session ID",
            "Date",
            "City",
            "HTTP Status",
            "Success",
            "Exception",
            "Raw Data Length",
            "Raw Data Preview"
        ])

    return sheet


# ============================================================
# BMS GETSEATLAYOUT
# ============================================================

def get_seat_layout():

    url = (
        "https://services-in.bookmyshow.com/"
        "doTrans.aspx"
    )

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": VENUE_CODE,
        "strParam1": SESSION_ID,
        "strParam2": "WEB",
        "strParam5": "Y",
        "strParam6": "Y",
        "strParam7": "N",
        "strFormat": "json"
    }

    headers = {

        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 "
            "Safari/537.36"
        ),

        "Accept": (
            "application/json, text/plain, */*"
        ),

        "Content-Type": (
            "application/x-www-form-urlencoded; "
            "charset=UTF-8"
        ),

        "Origin": (
            "https://in.bookmyshow.com"
        ),

        "Referer": (
            "https://in.bookmyshow.com/"
        )
    }

    proxies = None

    if PROXY_URL:

        proxies = {
            "http": PROXY_URL,
            "https": PROXY_URL
        }

    print()
    print("=" * 70)
    print("BMS GETSEATLAYOUT")
    print("=" * 70)

    print("URL:")
    print(url)

    print()
    print("PAYLOAD:")
    print(payload)

    try:

        response = requests.post(

            url,

            data=payload,

            headers=headers,

            proxies=proxies,

            impersonate="chrome120",

            timeout=30
        )

    except Exception as e:

        print()
        print("REQUEST ERROR:")
        print(repr(e))

        return None

    print()
    print("HTTP STATUS:")
    print(response.status_code)

    print()
    print("RESPONSE SIZE:")
    print(len(response.text))

    print()
    print("RESPONSE PREVIEW:")
    print(response.text[:1000])

    return response


# ============================================================
# PROCESS RESPONSE
# ============================================================

def process_response(response):

    if response is None:
        return None

    result = {
        "http_status": response.status_code,
        "success": False,
        "exception": "",
        "raw_data_length": len(response.text),
        "raw_data_preview": response.text[:500]
    }

    try:

        data = response.json()

        print()
        print("=" * 70)
        print("JSON RESPONSE")
        print("=" * 70)

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )[:5000]
        )

        result["success"] = (
            str(
                data.get(
                    "blnSuccess",
                    ""
                )
            ).lower()
            == "true"
        )

        result["exception"] = str(
            data.get(
                "strException",
                ""
            )
        )

        if "strData" in data:

            raw_data = data["strData"]

            print()
            print(
                "strData found!"
            )

            print(
                "strData length:",
                len(raw_data)
            )

            print()
            print(
                "strData preview:"
            )

            print(
                raw_data[:1000]
            )

            result["raw_data_length"] = len(
                raw_data
            )

            result["raw_data_preview"] = (
                raw_data[:500]
            )

    except Exception as e:

        print()
        print(
            "Could not parse JSON:"
        )

        print(
            repr(e)
        )

        result["exception"] = str(e)

    return result


# ============================================================
# SAVE RESULT
# ============================================================

def save_result(result):

    if not result:
        return

    sheet = get_google_sheet()

    ist = pytz.timezone(
        "Asia/Kolkata"
    )

    now = datetime.now(
        ist
    )

    sheet.append_row([

        now.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        EVENT_CODE,

        VENUE_CODE,

        SESSION_ID,

        DATE_CODE,

        CITY,

        result["http_status"],

        result["success"],

        result["exception"],

        result["raw_data_length"],

        result["raw_data_preview"]

    ], value_input_option="USER_ENTERED")

    print()
    print(
        "Result saved to Google Sheets."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("TOXIC BMS DIRECT SEAT TEST")
    print("=" * 70)

    print(
        "Event:",
        EVENT_CODE
    )

    print(
        "Venue:",
        VENUE_CODE
    )

    print(
        "Session:",
        SESSION_ID
    )

    response = get_seat_layout()

    result = process_response(
        response
    )

    save_result(
        result
    )

    print()
    print("=" * 70)
    print("TEST FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()
