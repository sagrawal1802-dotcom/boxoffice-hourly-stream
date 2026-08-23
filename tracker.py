import os
import json
import base64
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from curl_cffi import requests
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CONFIGURATION
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1zzp8T0ergvrIcyqutlLTh6bzO2CBwfWT9xoaAMaCOO4"
)

SHEET_TAB_NAME = os.environ.get(
    "SHEET_TAB_NAME",
    "Toxic_Cinepolis"
)

CITY = "mumbai"
SHOW_DATE = "20260826"

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"

# These are the 7 Cinepolis codes extracted from the supplied HAR.
VENUE_CODES = [
    "CAGL",
    "FNAN",
    "THAB",
    "CPVM",
    "CPNM",
    "CSWO",
    "CPVV",
]

VENUE_NAMES = {
    "CAGL": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
    "FNAN": "Cinepolis: Fun Republic Mall, Andheri (W)",
    "THAB": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
    "CPVM": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
    "CPNM": "Cinepolis: Magnet Mall, Bhandup (W)",
    "CSWO": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
    "CPVV": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)"
}

# Keep the same pacing used by the successful CSWO tracker.
DELAY_BETWEEN_SHOWS = 8
MAX_ATTEMPTS = 3
GOOGLE_BATCH_SIZE = 500


# ============================================================
# 106 SHOWS EXTRACTED FROM THE SUPPLIED HAR
#
# Venue totals:
# CAGL = 14
# FNAN = 10
# THAB = 12
# CPVM = 24
# CPNM = 14
# CSWO = 23
# CPVV = 9
#
# TOTAL = 106
# ============================================================

SHOWS = [
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "5788"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "07:50 AM",
        "event_code": "ET00379311",
        "session_id": "5783"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "09:00 AM",
        "event_code": "ET00379311",
        "session_id": "5900"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "10:50 AM",
        "event_code": "ET00379311",
        "session_id": "5789"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "11:40 AM",
        "event_code": "ET00379311",
        "session_id": "5784"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "12:50 PM",
        "event_code": "ET00379311",
        "session_id": "5901"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "02:55 PM",
        "event_code": "ET00379311",
        "session_id": "5790"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "03:45 PM",
        "event_code": "ET00379311",
        "session_id": "5785"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "04:55 PM",
        "event_code": "ET00379311",
        "session_id": "5902"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "07:00 PM",
        "event_code": "ET00379311",
        "session_id": "5791"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "07:50 PM",
        "event_code": "ET00379311",
        "session_id": "5786"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "09:00 PM",
        "event_code": "ET00379311",
        "session_id": "5903"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "11:05 PM",
        "event_code": "ET00379311",
        "session_id": "5792"
    },
    {
        "venue_code": "CAGL",
        "venue_name": "Cinepolis: Aurum, Ghansoli, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "11:55 PM",
        "event_code": "ET00379311",
        "session_id": "5787"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "5704"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "08:00 AM",
        "event_code": "ET00379311",
        "session_id": "5709"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "10:40 AM",
        "event_code": "ET00379311",
        "session_id": "5705"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "11:40 AM",
        "event_code": "ET00379311",
        "session_id": "5710"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "02:45 PM",
        "event_code": "ET00379311",
        "session_id": "5706"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "03:45 PM",
        "event_code": "ET00379311",
        "session_id": "5711"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "06:50 PM",
        "event_code": "ET00379311",
        "session_id": "5707"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "07:50 PM",
        "event_code": "ET00379311",
        "session_id": "5712"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "10:55 PM",
        "event_code": "ET00379311",
        "session_id": "5708"
    },
    {
        "venue_code": "FNAN",
        "venue_name": "Cinepolis: Fun Republic Mall, Andheri (W)",
        "format": "Hindi 2D",
        "show_time": "11:55 PM",
        "event_code": "ET00379311",
        "session_id": "5713"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "6613"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "08:00 AM",
        "event_code": "ET00379311",
        "session_id": "6620"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "10:40 AM",
        "event_code": "ET00379311",
        "session_id": "6616"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "11:40 AM",
        "event_code": "ET00379311",
        "session_id": "6621"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "02:45 PM",
        "event_code": "ET00379311",
        "session_id": "6617"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "03:45 PM",
        "event_code": "ET00379311",
        "session_id": "6622"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "06:50 PM",
        "event_code": "ET00379311",
        "session_id": "6618"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "07:20 PM",
        "event_code": "ET00379311",
        "session_id": "6696"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "07:50 PM",
        "event_code": "ET00379311",
        "session_id": "6623"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "10:55 PM",
        "event_code": "ET00379311",
        "session_id": "6619"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "11:25 PM",
        "event_code": "ET00379311",
        "session_id": "6697"
    },
    {
        "venue_code": "THAB",
        "venue_name": "Cinepolis: High Street Mall, Thane (EX Cinemastar)",
        "format": "Hindi 2D",
        "show_time": "11:55 PM",
        "event_code": "ET00379311",
        "session_id": "6624"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "4DX",
        "show_time": "07:45 AM",
        "event_code": "ET00513506",
        "session_id": "13210"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "4DX",
        "show_time": "11:30 AM",
        "event_code": "ET00513506",
        "session_id": "13215"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "4DX",
        "show_time": "03:35 PM",
        "event_code": "ET00513506",
        "session_id": "13216"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "4DX",
        "show_time": "07:40 PM",
        "event_code": "ET00513506",
        "session_id": "13217"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "4DX",
        "show_time": "11:45 PM",
        "event_code": "ET00513506",
        "session_id": "13218"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "13199"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "08:00 AM",
        "event_code": "ET00379311",
        "session_id": "13204"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "09:00 AM",
        "event_code": "ET00379311",
        "session_id": "13354"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "10:45 AM",
        "event_code": "ET00379311",
        "session_id": "13200"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "11:45 AM",
        "event_code": "ET00379311",
        "session_id": "13205"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "01:05 PM",
        "event_code": "ET00379311",
        "session_id": "13355"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "02:50 PM",
        "event_code": "ET00379311",
        "session_id": "13201"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "03:50 PM",
        "event_code": "ET00379311",
        "session_id": "13206"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "05:10 PM",
        "event_code": "ET00379311",
        "session_id": "13356"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "06:55 PM",
        "event_code": "ET00379311",
        "session_id": "13202"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "07:55 PM",
        "event_code": "ET00379311",
        "session_id": "13207"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "09:15 PM",
        "event_code": "ET00379311",
        "session_id": "13357"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "10:59 PM",
        "event_code": "ET00379311",
        "session_id": "13203"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "11:59 PM",
        "event_code": "ET00379311",
        "session_id": "13208"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "IMAX",
        "show_time": "07:30 AM",
        "event_code": "ET00513458",
        "session_id": "13209"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "IMAX",
        "show_time": "11:15 AM",
        "event_code": "ET00513458",
        "session_id": "13211"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "IMAX",
        "show_time": "03:20 PM",
        "event_code": "ET00513458",
        "session_id": "13212"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "IMAX",
        "show_time": "07:25 PM",
        "event_code": "ET00513458",
        "session_id": "13213"
    },
    {
        "venue_code": "CPVM",
        "venue_name": "Cinepolis: Lake Shore, Thane (EX Viviana Mall)",
        "format": "IMAX",
        "show_time": "11:30 PM",
        "event_code": "ET00513458",
        "session_id": "13214"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "7591"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "08:00 AM",
        "event_code": "ET00379311",
        "session_id": "7586"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "09:00 AM",
        "event_code": "ET00379311",
        "session_id": "7656"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "10:40 AM",
        "event_code": "ET00379311",
        "session_id": "7592"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "11:40 AM",
        "event_code": "ET00379311",
        "session_id": "7587"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "12:45 PM",
        "event_code": "ET00379311",
        "session_id": "7657"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "02:45 PM",
        "event_code": "ET00379311",
        "session_id": "7593"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "03:45 PM",
        "event_code": "ET00379311",
        "session_id": "7588"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "04:50 PM",
        "event_code": "ET00379311",
        "session_id": "7658"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "06:50 PM",
        "event_code": "ET00379311",
        "session_id": "7594"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "07:50 PM",
        "event_code": "ET00379311",
        "session_id": "7589"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "08:55 PM",
        "event_code": "ET00379311",
        "session_id": "7659"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "10:55 PM",
        "event_code": "ET00379311",
        "session_id": "7595"
    },
    {
        "venue_code": "CPNM",
        "venue_name": "Cinepolis: Magnet Mall, Bhandup (W)",
        "format": "Hindi 2D",
        "show_time": "11:55 PM",
        "event_code": "ET00379311",
        "session_id": "7590"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "4DX",
        "show_time": "07:45 AM",
        "event_code": "ET00513506",
        "session_id": "16020"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "4DX",
        "show_time": "03:30 PM",
        "event_code": "ET00513506",
        "session_id": "16021"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "4DX",
        "show_time": "07:35 PM",
        "event_code": "ET00513506",
        "session_id": "16024"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "4DX",
        "show_time": "11:40 PM",
        "event_code": "ET00513506",
        "session_id": "16023"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "07:00 AM",
        "event_code": "ET00379311",
        "session_id": "15925"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "08:00 AM",
        "event_code": "ET00379311",
        "session_id": "15934"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "09:00 AM",
        "event_code": "ET00379311",
        "session_id": "16072"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "10:40 AM",
        "event_code": "ET00379311",
        "session_id": "15926"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "11:40 AM",
        "event_code": "ET00379311",
        "session_id": "15933"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "01:05 PM",
        "event_code": "ET00379311",
        "session_id": "16073"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "02:45 PM",
        "event_code": "ET00379311",
        "session_id": "15927"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "03:45 PM",
        "event_code": "ET00379311",
        "session_id": "15932"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "05:10 PM",
        "event_code": "ET00379311",
        "session_id": "16074"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "06:50 PM",
        "event_code": "ET00379311",
        "session_id": "15928"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "07:50 PM",
        "event_code": "ET00379311",
        "session_id": "15931"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "09:15 PM",
        "event_code": "ET00379311",
        "session_id": "16075"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "10:55 PM",
        "event_code": "ET00379311",
        "session_id": "15929"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "Hindi 2D",
        "show_time": "11:55 PM",
        "event_code": "ET00379311",
        "session_id": "15930"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "IMAX",
        "show_time": "07:30 AM",
        "event_code": "ET00513458",
        "session_id": "16005"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "IMAX",
        "show_time": "11:10 AM",
        "event_code": "ET00513458",
        "session_id": "16006"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "IMAX",
        "show_time": "03:15 PM",
        "event_code": "ET00513458",
        "session_id": "16007"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "IMAX",
        "show_time": "07:20 PM",
        "event_code": "ET00513458",
        "session_id": "16008"
    },
    {
        "venue_code": "CSWO",
        "venue_name": "Cinepolis: Nexus Seawoods, Nerul, Navi Mumbai",
        "format": "IMAX",
        "show_time": "11:25 PM",
        "event_code": "ET00513458",
        "session_id": "16009"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "07:20 AM",
        "event_code": "ET00379311",
        "session_id": "4888"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "08:30 AM",
        "event_code": "ET00379311",
        "session_id": "4913"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "11:10 AM",
        "event_code": "ET00379311",
        "session_id": "4895"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "12:35 PM",
        "event_code": "ET00379311",
        "session_id": "4914"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "03:15 PM",
        "event_code": "ET00379311",
        "session_id": "4896"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "04:40 PM",
        "event_code": "ET00379311",
        "session_id": "4915"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "07:20 PM",
        "event_code": "ET00379311",
        "session_id": "4897"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "08:45 PM",
        "event_code": "ET00379311",
        "session_id": "4916"
    },
    {
        "venue_code": "CPVV",
        "venue_name": "Cinepolis: VIP Lake Shore, Thane (EX Viviana Mall)",
        "format": "Hindi 2D",
        "show_time": "11:25 PM",
        "event_code": "ET00379311",
        "session_id": "4898"
    }
]


# ============================================================
# GOOGLE SHEET HEADERS
# ============================================================

HEADERS = [
    "Timestamp IST",
    "Movie",
    "Event Code",
    "Venue Code",
    "Session ID",
    "Format",
    "Show Time",
    "Date",
    "City",
    "Row Number",
    "Row Name",
    "Category Code",
    "Category",
    "Seat Token",
    "Seat Code",
    "Seat Number",
    "BMS State",
]


# ============================================================
# GOOGLE CREDENTIALS
# ============================================================

GCP_SA_KEY = (
    os.environ.get("GCP_SA_KEY_B64")
    or os.environ.get("GCP_SA_KEY")
)


# ============================================================
# CATEGORY FALLBACK
# ============================================================

CATEGORY_FALLBACK = {
    "A": "RECLINER",
    "B": "PREMIUM",
    "C": "EXECUTIVE XL",
    "D": "EXECUTIVE",
    "E": "NORMAL",
}


# ============================================================
# HELPERS
# ============================================================

def banner(title):
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


def get_ist_timestamp():
    return datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# GOOGLE SHEETS
# ============================================================

def init_google_sheet():
    banner("CONNECTING TO GOOGLE SHEETS")

    if not GCP_SA_KEY:
        raise ValueError(
            "Missing GCP_SA_KEY_B64 or GCP_SA_KEY GitHub Secret."
        )

    raw_key = GCP_SA_KEY.strip()

    try:
        if raw_key.startswith("{"):
            service_account_info = json.loads(raw_key)
        else:
            decoded = base64.b64decode(raw_key).decode("utf-8")
            service_account_info = json.loads(decoded)
    except Exception as error:
        raise ValueError(
            f"Could not decode Google service account secret: {error}"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes
    )

    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        sheet = spreadsheet.worksheet(SHEET_TAB_NAME)
    except gspread.WorksheetNotFound:
        print(f"Creating worksheet: {SHEET_TAB_NAME}")
        sheet = spreadsheet.add_worksheet(
            title=SHEET_TAB_NAME,
            rows=100000,
            cols=len(HEADERS)
        )

    existing = sheet.get_all_values()

    if not existing:
        print("Sheet empty. Adding headers.")
        sheet.update(
            range_name="A1",
            values=[HEADERS]
        )
    else:
        current_headers = existing[0]
        if current_headers[:len(HEADERS)] != HEADERS:
            print()
            print("WARNING: Existing headers differ.")
            print("Current:")
            print(current_headers)
            print()
            print("Expected:")
            print(HEADERS)
            print()

    print("Google Sheets connected.")
    return sheet


# ============================================================
# BMS SEAT LAYOUT REQUEST
#
# SAME REQUEST STRUCTURE AS THE SUCCESSFUL CSWO TRACKER.
#
# Only the venue code is now taken from the individual show.
# ============================================================

def get_seat_layout(show):
    event_code = show["event_code"]
    session_id = show["session_id"]
    show_time = show["show_time"]
    show_format = show["format"]
    venue_code = show["venue_code"]

    url = "https://services-in.bookmyshow.com/doTrans.aspx"

    payload = {
        "strCommand": "GETSEATLAYOUT",
        "strVenueCode": venue_code,
        "strParam1": session_id,
        "strParam2": "WEB",
        "strParam5": "Y",
        "strParam6": "Y",
        "strParam7": "N",
        "strFormat": "json",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": (
            "application/x-www-form-urlencoded; charset=UTF-8"
        ),
        "Origin": "https://in.bookmyshow.com",
        "Referer": (
            f"https://in.bookmyshow.com/movies/"
            f"{CITY}/seat-layout/"
            f"{event_code}/{venue_code}/"
            f"{session_id}/{SHOW_DATE}"
        ),
    }

    print()
    print("-" * 90)
    print(
        f"VENUE      : {venue_code} - "
        f"{VENUE_NAMES.get(venue_code, venue_code)}"
    )
    print(
        f"SEAT LAYOUT | {show_format} | "
        f"{show_time} | Session {session_id}"
    )
    print("-" * 90)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(f"Attempt {attempt}/{MAX_ATTEMPTS}")

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                impersonate="chrome120",
                timeout=30,
            )

            print(f"HTTP status: {response.status_code}")
            print(f"Response size: {len(response.content)} bytes")

            if response.status_code != 200:
                print("BMS request failed.")

                if response.status_code == 429:
                    print("BMS returned HTTP 429 rate limit.")

                if attempt < MAX_ATTEMPTS:
                    time.sleep(5)

                continue

            try:
                data = response.json()
            except Exception:
                text = response.text.strip()
                print("JSON decoding failed.")
                print("Response preview:")
                print(text[:1000])

                if attempt < MAX_ATTEMPTS:
                    time.sleep(5)

                continue

            bookmyshow = data.get("BookMyShow", {})

            success = bookmyshow.get("blnSuccess")

            print(f"blnSuccess : {success}")
            print(
                f"intException : "
                f"{bookmyshow.get('intException')}"
            )

            if bookmyshow.get("strException"):
                print(
                    f"strException : "
                    f"{bookmyshow.get('strException')}"
                )

            str_data = bookmyshow.get("strData")

            if not str_data:
                print("No strData returned by BMS.")

                if attempt < MAX_ATTEMPTS:
                    time.sleep(5)

                continue

            print(f"strData length : {len(str_data)}")

            return str_data

        except Exception as error:
            print(f"Request error: {repr(error)}")

            if attempt < MAX_ATTEMPTS:
                time.sleep(5)

    return None


# ============================================================
# CATEGORY PARSER
# ============================================================

def parse_categories(category_section):
    categories = {}

    parts = category_section.split("|")

    for part in parts:
        part = part.strip()

        if not part:
            continue

        pieces = part.split(":")

        if len(pieces) < 2:
            continue

        category_name = pieces[0].strip()
        category_code = pieces[1].strip()

        if category_code:
            categories[category_code] = category_name

    return categories


# ============================================================
# SEAT TOKEN PARSER
#
# B1048+6 = AVAILABLE
# B2049+7 = SOLD
# ============================================================

def parse_seat_token(token):
    token = token.strip()

    if not token:
        return None

    token = token.replace(" ", "")

    match = re.match(
        r"^([A-Za-z])(\d+)\+(\d+)$",
        token
    )

    if not match:
        return None

    letter = match.group(1).upper()
    numeric_code = match.group(2)
    actual_seat_number = match.group(3)

    seat_code = f"{letter}{numeric_code}"

    if numeric_code == "0":
        return None

    if numeric_code.startswith("1"):
        bms_state = "AVAILABLE"
    elif numeric_code.startswith("2"):
        bms_state = "SOLD"
    else:
        return None

    return {
        "seat_token": token,
        "seat_code": seat_code,
        "seat_number": actual_seat_number,
        "bms_state": bms_state,
    }


# ============================================================
# PARSE BMS strData
# ============================================================

def parse_seat_rows(str_data, show):
    event_code = show["event_code"]
    session_id = show["session_id"]
    show_time = show["show_time"]
    show_format = show["format"]
    venue_code = show["venue_code"]

    timestamp = get_ist_timestamp()

    sections = str_data.split("||", 1)

    if len(sections) != 2:
        print("ERROR: Could not split BMS strData.")
        print("strData preview:")
        print(str_data[:2000])
        return []

    category_section = sections[0]
    seat_section = sections[1]

    categories = parse_categories(category_section)

    for code, name in CATEGORY_FALLBACK.items():
        if code not in categories:
            categories[code] = name

    print()
    print("CATEGORY MAP")

    for code, name in categories.items():
        print(f"{code} -> {name}")

    print()

    raw_rows = seat_section.split("|")
    results = []

    available_count = 0
    sold_count = 0

    for raw_row in raw_rows:
        raw_row = raw_row.strip()

        if not raw_row:
            continue

        row_parts = raw_row.split(":", 3)

        if len(row_parts) < 4:
            continue

        row_number = row_parts[0].strip()
        row_name = row_parts[1].strip()
        category_code = row_parts[2].strip()
        seat_data = row_parts[3].strip()

        category = categories.get(
            category_code,
            category_code
        )

        seat_tokens = seat_data.split(":")

        for token in seat_tokens:
            token = token.strip()

            if not token:
                continue

            parsed = parse_seat_token(token)

            if parsed is None:
                continue

            bms_state = parsed["bms_state"]

            if bms_state == "AVAILABLE":
                available_count += 1
            elif bms_state == "SOLD":
                sold_count += 1

            results.append([
                timestamp,
                MOVIE_NAME,
                event_code,
                venue_code,
                session_id,
                show_format,
                show_time,
                SHOW_DATE,
                CITY,
                row_number,
                row_name,
                category_code,
                category,
                parsed["seat_token"],
                parsed["seat_code"],
                parsed["seat_number"],
                bms_state,
            ])

    print()
    print("=" * 90)
    print("SHOW SUMMARY")
    print("=" * 90)

    print(f"Venue      : {venue_code}")
    print(f"Format     : {show_format}")
    print(f"Show       : {show_time}")
    print(f"Event      : {event_code}")
    print(f"Session    : {session_id}")
    print(f"Available  : {available_count}")
    print(f"Sold       : {sold_count}")
    print(f"Total      : {available_count + sold_count}")

    print("=" * 90)

    return results


# ============================================================
# PRINT SAMPLE
# ============================================================

def print_sample(rows):
    if not rows:
        return

    print()
    print("=" * 120)
    print("SEAT SAMPLE")
    print("=" * 120)

    print(
        "Venue | Format | Show Time | Session | Row | "
        "Category | Seat Token | Seat Code | Seat No | Status"
    )

    print("-" * 120)

    for row in rows[:20]:
        print(
            f"{row[3]} | "
            f"{row[5]} | "
            f"{row[6]} | "
            f"{row[4]} | "
            f"{row[9]} | "
            f"{row[12]} | "
            f"{row[13]} | "
            f"{row[14]} | "
            f"{row[15]} | "
            f"{row[16]}"
        )

    print("-" * 120)


# ============================================================
# GOOGLE SHEETS BATCH WRITE
# ============================================================

def write_to_sheet(sheet, rows):
    if not rows:
        print()
        print("No seat records to write.")
        return

    banner("WRITING ALL SEATS TO GOOGLE SHEETS")

    total = len(rows)

    print(f"Total seat records: {total}")

    for start in range(0, total, GOOGLE_BATCH_SIZE):
        batch = rows[
            start:start + GOOGLE_BATCH_SIZE
        ]

        end = start + len(batch)

        print(
            f"Writing rows "
            f"{start + 1}-{end} / {total}"
        )

        sheet.append_rows(
            batch,
            value_input_option="USER_ENTERED"
        )

    print()
    print(
        f"Google Sheet updated successfully. "
        f"{total} seat records written."
    )


# ============================================================
# TEST PARSER
# ============================================================

def test_parser():
    banner("TESTING BMS SEAT PARSER")

    tests = [
        "B1042+2",
        "B1043+3",
        "A1052+1",
        "A1053+2",
        "B1048+6",
        "B2049+7",
        "D10216+10",
        "A0+0",
        "B0+0",
    ]

    for token in tests:
        result = parse_seat_token(token)

        print(
            f"{token:<15} -> {result}"
        )


# ============================================================
# SHOW LIST
# ============================================================

def print_show_list():
    banner("106 HAR-CONFIRMED CINEPOLIS SHOWS")

    venue_counts = {}

    for index, show in enumerate(SHOWS, start=1):
        code = show["venue_code"]

        venue_counts[code] = (
            venue_counts.get(code, 0) + 1
        )

        print(
            f"{index:03d}. "
            f"{code:<4} | "
            f"{show['format']:<10} | "
            f"{show['show_time']:<9} | "
            f"{show['event_code']} | "
            f"Session {show['session_id']}"
        )

    print()
    print(f"TOTAL SHOWS: {len(SHOWS)}")

    print()

    for code in VENUE_CODES:
        print(
            f"{code} | "
            f"{venue_counts.get(code, 0):02d} shows | "
            f"{VENUE_NAMES.get(code, '')}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    banner("BMS TOXIC - CINEPOLIS 7-VENUE ALL-SHOW SEAT TRACKER")

    print(f"Timestamp : {get_ist_timestamp()}")
    print(f"Movie     : {MOVIE_NAME}")
    print(f"City      : {CITY}")
    print(f"Date      : {SHOW_DATE}")
    print(f"Venues    : {len(VENUE_CODES)}")
    print(f"Shows     : {len(SHOWS)}")

    print()
    print("VENUES")

    for code in VENUE_CODES:
        print(
            f"{code} - "
            f"{VENUE_NAMES.get(code, '')}"
        )

    print_show_list()
    test_parser()

    sheet = init_google_sheet()

    all_rows = []
    successful_shows = 0
    failed_shows = 0

    for index, show in enumerate(
        SHOWS,
        start=1
    ):
        banner(
            f"SHOW {index}/{len(SHOWS)}"
        )

        print(
            f"Venue      : {show['venue_code']}"
        )

        print(
            f"Venue Name : "
            f"{show['venue_name']}"
        )

        print(
            f"Format     : {show['format']}"
        )

        print(
            f"Show Time  : {show['show_time']}"
        )

        print(
            f"Event Code : {show['event_code']}"
        )

        print(
            f"Session ID : {show['session_id']}"
        )

        str_data = get_seat_layout(show)

        if not str_data:
            print()
            print(
                f"FAILED: No seat layout for "
                f"{show['venue_code']} / "
                f"session {show['session_id']}"
            )

            failed_shows += 1

        else:
            rows = parse_seat_rows(
                str_data,
                show
            )

            if rows:
                successful_shows += 1
                all_rows.extend(rows)
                print_sample(rows)
            else:
                print(
                    "WARNING: BMS returned strData "
                    "but no seats were parsed."
                )
                failed_shows += 1

        if index < len(SHOWS):
            print()
            print(
                f"Waiting {DELAY_BETWEEN_SHOWS} seconds "
                f"before next show..."
            )
            time.sleep(DELAY_BETWEEN_SHOWS)

    write_to_sheet(
        sheet,
        all_rows
    )

    banner("FINAL CINEPOLIS SUMMARY")

    print(f"Venues           : {len(VENUE_CODES)}")
    print(f"Shows             : {len(SHOWS)}")
    print(f"Successful shows  : {successful_shows}")
    print(f"Failed shows      : {failed_shows}")
    print(f"Seat records      : {len(all_rows)}")

    print()
    print("VENUE SHOW COUNTS")

    counts = {}

    for show in SHOWS:
        code = show["venue_code"]
        counts[code] = counts.get(code, 0) + 1

    for code in VENUE_CODES:
        print(
            f"{code} : {counts.get(code, 0)}"
        )


if __name__ == "__main__":
    main()
