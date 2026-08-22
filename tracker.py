import os
import json
import base64
from datetime import datetime

import pytz
import gspread
from curl_cffi import requests
from google.oauth2.service_account import Credentials


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

# IMPORTANT:
# Proxy is deliberately NOT being used in this test.
# We need to determine whether GitHub can reach BMS directly.

SHEET_TAB_NAME = "Toxic_BMS_Raw"


# ============================================================
# TOXIC TEST SHOW
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
            "GCP_SA_KEY_B64 or GCP_SA_KEY is missing."
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

    credentials = Credentials.from_service_account_info(
        service_account,
        scopes=scopes
    )

    client = gspread.authorize(credentials)

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
            "Response Length",
            "Response Preview"
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
        ),

        "Accept-Language": (
            "en-IN,en;q=0.9"
        ),

        "Connection": "keep-alive"
    }

    print()
    print("=" * 70)
    print("BMS GETSEATLAYOUT")
    print("=" * 70)

    print()
    print("URL:")
    print(url)

    print()
    print("PAYLOAD:")
    print(payload)

    print()
    print("PROXY:")
    print("DISABLED FOR THIS TEST")

    try:

        response = requests.post(

            url,

            data=payload,

            headers=headers,

            impersonate="chrome120",

            timeout=30
        )

    except Exception as e:

        print()
        print("=" * 70)
        print("REQUEST ERROR")
        print("=" * 70)

        print(
            repr(e)
        )

        return None

    print()
    print("=" * 70)
    print("BMS RESPONSE")
    print("=" * 70)

    print()
    print("HTTP STATUS:")
    print(
        response.status_code
    )

    print()
    print("RESPONSE SIZE:")
    print(
        len(response.text)
    )

    print()
    print("RESPONSE HEADERS:")

    for key, value in response.headers.items():

        print(
            f"{key}: {value}"
        )

    print()
    print("RESPONSE PREVIEW:")

    print(
        response.text[:3000]
    )

    return response


# ============================================================
# PROCESS BMS RESPONSE
# ============================================================

def process_response(response):

    if response is None:

        return {
            "http_status": 0,
            "success": False,
            "exception": "No response received",
            "raw_length": 0,
            "preview": ""
        }

    result = {

        "http_status": response.status_code,

        "success": False,

        "exception": "",

        "raw_length": len(
            response.text
        ),

        "preview": response.text[:500]

    }

    # --------------------------------------------------------
    # Try JSON
    # --------------------------------------------------------

    try:

        data = response.json()

        print()
        print("=" * 70)
        print("JSON RESPONSE RECEIVED")
        print("=" * 70)

        print(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )[:10000]
        )

        # ----------------------------------------------------
        # BMS success flag
        # ----------------------------------------------------

        success_value = data.get(
            "blnSuccess"
        )

        if str(
            success_value
        ).lower() == "true":

            result["success"] = True

        # ----------------------------------------------------
        # Exception
        # ----------------------------------------------------

        result["exception"] = str(
            data.get(
                "strException",
                ""
            )
        )

        # ----------------------------------------------------
        # strData
        # ----------------------------------------------------

        if "strData" in data:

            raw_data = data["strData"]

            print()
            print("=" * 70)
            print("STRDATA FOUND")
            print("=" * 70)

            print()
            print(
                "strData length:"
            )

            print(
                len(raw_data)
            )

            print()
            print(
                "strData preview:"
            )

            print(
                raw_data[:3000]
            )

            result["raw_length"] = len(
                raw_data
            )

            result["preview"] = (
                raw_data[:500]
            )

        else:

            print()
            print(
                "No strData field found."
            )

    except Exception as e:

        print()
        print("=" * 70)
        print("JSON PARSE ERROR")
        print("=" * 70)

        print(
            repr(e)
        )

        result["exception"] = str(e)

    return result


# ============================================================
# SAVE RESULT TO GOOGLE SHEETS
# ============================================================

def save_result(result):

    sheet = get_google_sheet()

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

        result["http_status"],

        result["success"],

        result["exception"],

        result["raw_length"],

        result["preview"]

    ]

    sheet.append_row(
        row,
        value_input_option="USER_ENTERED"
    )

    print()
    print(
        "Google Sheet updated successfully."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("TOXIC BMS DIRECT SEAT TEST")
    print("=" * 70)

    print()
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

    print(
        "Date:",
        DATE_CODE
    )

    print(
        "City:",
        CITY
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
