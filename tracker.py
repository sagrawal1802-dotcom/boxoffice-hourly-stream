import os
import re
import json
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIG
# ============================================================

MOVIE_NAME = "Toxic: A Fairy Tale for Grown-ups"
CITY = "mumbai"
VENUE_CODE = "CSWO"
DATE_CODE = "20260826"

# Main Toxic movie page
MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

# Known event codes from previous successful tracking.
# These are NOT treated as the final list.
KNOWN_EVENT_CODES = {
    "ET00379311",
    "ET00513506",
}

# Output directory
OUTPUT_DIR = "bms_debug"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()

    return str(value)


def extract_event_codes(text):
    """
    Extract BMS event codes from HTML, URLs and JSON.

    Example:
        ET00379311
        ET00513506
    """

    if not text:
        return set()

    return set(re.findall(r"\bET\d{6,10}\b", text))


def extract_session_ids(text):
    """
    Extract likely numeric session IDs.

    We deliberately keep this conservative.
    """

    if not text:
        return set()

    results = set()

    patterns = [
        r'"sessionId"\s*:\s*"(\d+)"',
        r'"sessionID"\s*:\s*"(\d+)"',
        r'"session_id"\s*:\s*"(\d+)"',
        r'"sessionId"\s*:\s*(\d+)',
        r'"sessionID"\s*:\s*(\d+)',
        r'"session_id"\s*:\s*(\d+)',
    ]

    for pattern in patterns:
        for value in re.findall(pattern, text, flags=re.I):
            results.add(value)

    return results


def find_format_words(text):
    """
    Look for common format labels in BMS responses/page source.
    """

    if not text:
        return set()

    formats = set()

    format_patterns = {
        "2D": [
            r"\b2D\b",
            r"2-D",
        ],
        "3D": [
            r"\b3D\b",
            r"3-D",
        ],
        "IMAX": [
            r"\bIMAX\b",
        ],
        "4DX": [
            r"\b4DX\b",
        ],
        "MX4D": [
            r"\bMX4D\b",
        ],
        "ICE": [
            r"\bICE\b",
        ],
        "D-BOX": [
            r"\bD-BOX\b",
        ],
        "SCREENX": [
            r"\bSCREENX\b",
        ],
        "LASER": [
            r"\bLASER\b",
        ],
    }

    for fmt, patterns in format_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text, flags=re.I):
                formats.add(fmt)
                break

    return formats


def save_text(filename, text):
    path = os.path.join(OUTPUT_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return path


# ============================================================
# MAIN
# ============================================================

def main():

    timestamp = now()

    print("=" * 90)
    print("BMS TOXIC EVENT + FORMAT DISCOVERY")
    print("=" * 90)
    print(f"Timestamp : {timestamp}")
    print(f"Movie     : {MOVIE_NAME}")
    print(f"City      : {CITY}")
    print(f"Venue     : {VENUE_CODE}")
    print(f"Date      : {DATE_CODE}")
    print("=" * 90)

    all_event_codes = set(KNOWN_EVENT_CODES)
    captured_responses = []
    candidate_show_urls = []

    with sync_playwright() as p:

        print()
        print("=" * 90)
        print("LAUNCHING CHROMIUM")
        print("=" * 90)

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 900,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # ----------------------------------------------------
        # NETWORK RESPONSE CAPTURE
        # ----------------------------------------------------

        def handle_response(response):

            try:
                url = response.url

                resource_type = response.request.resource_type

                if resource_type not in {
                    "xhr",
                    "fetch",
                    "document",
                    "script",
                }:
                    return

                event_codes = extract_event_codes(url)

                if event_codes:
                    all_event_codes.update(event_codes)

                # Save metadata
                item = {
                    "url": url,
                    "status": response.status,
                    "resource_type": resource_type,
                    "content_type": response.headers.get(
                        "content-type", ""
                    ),
                }

                captured_responses.append(item)

                # Print only potentially useful BMS responses
                lower_url = url.lower()

                interesting = (
                    "bookmyshow" in lower_url
                    or "bms" in lower_url
                    or "show" in lower_url
                    or "event" in lower_url
                    or "movie" in lower_url
                    or "listing" in lower_url
                    or "session" in lower_url
                )

                if interesting:

                    print()
                    print("[NETWORK]")
                    print("Status :", response.status)
                    print("Type   :", resource_type)
                    print("URL    :", url[:500])

                    try:
                        body = response.text()

                        if body:

                            body_event_codes = extract_event_codes(body)
                            body_sessions = extract_session_ids(body)
                            body_formats = find_format_words(body)

                            if body_event_codes:
                                all_event_codes.update(
                                    body_event_codes
                                )

                            print(
                                "Events :",
                                sorted(body_event_codes)
                            )

                            print(
                                "Sessions:",
                                sorted(body_sessions)[:20]
                            )

                            print(
                                "Formats :",
                                sorted(body_formats)
                            )

                            # Save useful JSON/text response
                            safe_index = len(captured_responses)

                            filename = (
                                f"response_{safe_index}.txt"
                            )

                            save_text(
                                filename,
                                (
                                    f"URL:\n{url}\n\n"
                                    f"STATUS:\n{response.status}\n\n"
                                    f"BODY:\n{body}"
                                ),
                            )

                    except Exception as e:
                        print(
                            "Could not read response:",
                            e
                        )

            except Exception:
                pass

        page.on("response", handle_response)

        # ----------------------------------------------------
        # REQUEST CAPTURE
        # ----------------------------------------------------

        def handle_request(request):

            try:
                url = request.url

                event_codes = extract_event_codes(url)

                if event_codes:
                    all_event_codes.update(event_codes)

                lower = url.lower()

                if (
                    "bookmyshow" in lower
                    and (
                        "show" in lower
                        or "event" in lower
                        or "movie" in lower
                        or "listing" in lower
                        or "session" in lower
                    )
                ):
                    print()
                    print("[REQUEST]")
                    print(request.method, url[:600])

            except Exception:
                pass

        page.on("request", handle_request)

        # ----------------------------------------------------
        # OPEN MOVIE PAGE
        # ----------------------------------------------------

        print()
        print("=" * 90)
        print("OPENING BMS MOVIE PAGE")
        print("=" * 90)

        print("URL:")
        print(MOVIE_URL)

        try:

            response = page.goto(
                MOVIE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print(
                    "Page HTTP status:",
                    response.status
                )

        except Exception as e:

            print()
            print("PAGE NAVIGATION ERROR")
            print(e)

        # ----------------------------------------------------
        # WAIT FOR JAVASCRIPT
        # ----------------------------------------------------

        print()
        print("Waiting for BMS JavaScript...")
        page.wait_for_timeout(10000)

        print("Scrolling page...")

        try:
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(3000)

            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(3000)

        except Exception:
            pass

        # ----------------------------------------------------
        # GET PAGE CONTENT
        # ----------------------------------------------------

        print()
        print("=" * 90)
        print("ANALYSING PAGE SOURCE")
        print("=" * 90)

        try:

            html = page.content()

            save_text(
                "movie_page.html",
                html
            )

            print(
                "HTML size:",
                len(html),
                "bytes"
            )

            html_events = extract_event_codes(html)

            print(
                "Event codes found in HTML:",
                sorted(html_events)
            )

            all_event_codes.update(
                html_events
            )

            html_formats = find_format_words(html)

            print(
                "Formats found in HTML:",
                sorted(html_formats)
            )

        except Exception as e:

            print(
                "Could not read page HTML:",
                e
            )

        # ----------------------------------------------------
        # ANALYSE ALL LINKS
        # ----------------------------------------------------

        print()
        print("=" * 90)
        print("ANALYSING BMS LINKS")
        print("=" * 90)

        try:

            links = page.locator("a").all()

            print(
                "Links found:",
                len(links)
            )

            for link in links:

                try:

                    href = link.get_attribute(
                        "href"
                    )

                    text = clean_text(
                        link.inner_text()
                    )

                    if not href:
                        continue

                    href_events = extract_event_codes(
                        href
                    )

                    if href_events:

                        all_event_codes.update(
                            href_events
                        )

                        candidate_show_urls.append(
                            {
                                "text": text,
                                "href": href,
                                "events": sorted(
                                    href_events
                                ),
                            }
                        )

                        print()
                        print(
                            "EVENT LINK:"
                        )
                        print(
                            "Text :",
                            text[:150]
                        )
                        print(
                            "URL  :",
                            href[:500]
                        )
                        print(
                            "Event:",
                            sorted(href_events)
                        )

                except Exception:
                    continue

        except Exception as e:

            print(
                "Link analysis failed:",
                e
            )

        # ----------------------------------------------------
        # LOCAL STORAGE / COOKIES
        # ----------------------------------------------------

        print()
        print("=" * 90)
        print("BROWSER STATE")
        print("=" * 90)

        try:

            cookies = context.cookies()

            print(
                "Cookies:",
                len(cookies)
            )

            for cookie in cookies:

                print(
                    cookie.get("name"),
                    "=",
                    str(
                        cookie.get("value", "")
                    )[:80]
                )

        except Exception:
            pass

        # ----------------------------------------------------
        # FINAL RESULTS
        # ----------------------------------------------------

        print()
        print("=" * 90)
        print("DISCOVERY RESULT")
        print("=" * 90)

        print()
        print(
            "KNOWN EVENT CODES:"
        )

        for code in sorted(KNOWN_EVENT_CODES):
            print(
                " ",
                code
            )

        print()
        print(
            "ALL EVENT CODES FOUND:"
        )

        for code in sorted(all_event_codes):
            print(
                " ",
                code
            )

        print()
        print(
            "TOTAL EVENT CODES:",
            len(all_event_codes)
        )

        print()
        print(
            "CAPTURED NETWORK RESPONSES:",
            len(captured_responses)
        )

        print()
        print(
            "EVENT-LINK CANDIDATES:",
            len(candidate_show_urls)
        )

        # ----------------------------------------------------
        # SAVE DISCOVERY JSON
        # ----------------------------------------------------

        discovery = {
            "timestamp": timestamp,
            "movie": MOVIE_NAME,
            "city": CITY,
            "venue": VENUE_CODE,
            "date": DATE_CODE,
            "movie_url": MOVIE_URL,
            "known_event_codes": sorted(
                KNOWN_EVENT_CODES
            ),
            "discovered_event_codes": sorted(
                all_event_codes
            ),
            "captured_responses": captured_responses,
            "candidate_show_urls": candidate_show_urls,
        }

        discovery_path = os.path.join(
            OUTPUT_DIR,
            "discovery.json"
        )

        with open(
            discovery_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                discovery,
                f,
                indent=2,
                ensure_ascii=False
            )

        print()
        print(
            "Saved:",
            discovery_path
        )

        # ----------------------------------------------------
        # CLOSE
        # ----------------------------------------------------

        browser.close()

    print()
    print("=" * 90)
    print("DISCOVERY RUN COMPLETED")
    print("=" * 90)

    if len(all_event_codes) > 0:

        print()
        print(
            "Next step: use the discovered event codes"
            " to identify CSWO shows and formats."
        )

    else:

        print()
        print(
            "No event codes discovered."
        )

        print(
            "Check bms_debug/movie_page.html and"
            " the response files generated by this run."
        )


if __name__ == "__main__":
    main()
