import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

CITY = "mumbai"
REGION = "MUMBAI"
DATE_CODE = "20260826"

EVENT_CODES = [
    "ET00379311",
    "ET00513458",
    "ET00513506",
]

OUTPUT_DIR = Path("bms_capture")
OUTPUT_DIR.mkdir(exist_ok=True)

captured = []
interesting = []


def banner(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def safe_filename(text):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:180]


def looks_interesting(url, content_type, body):
    """
    We intentionally do NOT depend on one specific BMS endpoint.

    Search broadly for:
    - showtime
    - cinema
    - venue
    - Cinepolis
    - Toxic
    - ET event codes
    - region
    """

    combined = (
        url.lower()
        + "\n"
        + content_type.lower()
        + "\n"
        + body[:500000].lower()
    )

    keywords = [
        "cinepolis",
        "showtime",
        "showtimes",
        "cinema",
        "venue",
        "toxic",
        "et00379311",
        "et00513458",
        "et00513506",
        "mumbai",
    ]

    return any(k in combined for k in keywords)


def save_response(index, url, content_type, body):
    parsed = urlparse(url)

    filename = (
        f"{index:04d}_"
        f"{safe_filename(parsed.netloc)}_"
        f"{safe_filename(parsed.path)}"
    )

    if not filename.endswith(".txt"):
        filename += ".txt"

    path = OUTPUT_DIR / filename

    try:
        path.write_text(body, encoding="utf-8", errors="ignore")
    except Exception:
        pass

    return str(path)


def extract_strings(body):
    """
    Extract useful human-readable strings from JSON/text.
    """

    results = set()

    patterns = [
        r"Cinepolis[^\"<]{0,150}",
        r"cinema[^\"<]{0,150}",
        r"venue[^\"<]{0,150}",
        r"ET\d{8}",
        r"[A-Za-z0-9 .&'()-]{0,100}Cinepolis[A-Za-z0-9 .&'()-]{0,100}",
    ]

    for pattern in patterns:
        try:
            for match in re.findall(pattern, body, flags=re.I):
                cleaned = re.sub(r"\s+", " ", match).strip()

                if cleaned:
                    results.add(cleaned[:300])
        except Exception:
            pass

    return sorted(results)


def inspect_json(body):
    """
    Recursively walk JSON and identify objects that look like:
    cinema / venue / property / showtime records.
    """

    found = []

    try:
        data = json.loads(body)
    except Exception:
        return found

    def walk(obj, path="root"):
        if isinstance(obj, dict):

            keys_lower = {
                str(k).lower(): k
                for k in obj.keys()
            }

            interesting_keys = [
                "cinema",
                "cinemacode",
                "cinemaname",
                "venue",
                "venuename",
                "venuecode",
                "property",
                "propertyname",
                "propertycode",
                "audi",
                "audiid",
                "showtime",
                "showtimes",
                "eventcode",
                "event_code",
            ]

            matched = [
                keys_lower[k]
                for k in interesting_keys
                if k in keys_lower
            ]

            if matched:
                record = {
                    "_path": path,
                    "_matched_keys": [str(x) for x in matched],
                }

                for key in matched:
                    try:
                        value = obj[key]

                        if isinstance(value, (str, int, float, bool)):
                            record[str(key)] = value
                        elif isinstance(value, list):
                            record[str(key)] = value[:10]
                        elif isinstance(value, dict):
                            record[str(key)] = value
                    except Exception:
                        pass

                found.append(record)

            for key, value in obj.items():
                walk(value, f"{path}.{key}")

        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")

    walk(data)

    return found


def record_response(response):
    url = response.url

    # Only BMS responses are relevant.
    if "bookmyshow.com" not in url.lower():
        return

    request = response.request
    resource_type = request.resource_type

    # Ignore obvious static assets.
    ignored_extensions = (
        ".js",
        ".css",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".ico",
        ".webp",
    )

    lower_url = url.lower()

    if any(lower_url.split("?")[0].endswith(ext) for ext in ignored_extensions):
        return

    try:
        content_type = response.headers.get("content-type", "")
    except Exception:
        content_type = ""

    # We care primarily about API/XHR/fetch/document responses.
    if resource_type not in (
        "xhr",
        "fetch",
        "document",
    ):
        return

    try:
        body = response.text()
    except Exception:
        return

    if not body:
        return

    index = len(captured) + 1

    entry = {
        "index": index,
        "status": response.status,
        "resource_type": resource_type,
        "url": url,
        "content_type": content_type,
        "size": len(body),
    }

    captured.append(entry)

    print()
    print("[BMS RESPONSE]")
    print("Index :", index)
    print("Status:", response.status)
    print("Type  :", resource_type)
    print("Size  :", len(body))
    print("URL   :", url[:500])

    # Save ALL useful BMS responses, not just Cinepolis ones.
    path = save_response(
        index,
        url,
        content_type,
        body,
    )

    entry["saved_file"] = path

    if looks_interesting(url, content_type, body):

        print(">>> INTERESTING RESPONSE <<<")

        entry["interesting"] = True

        strings = extract_strings(body)

        if strings:
            print("Useful strings:")

            for value in strings[:50]:
                print("  ", value)

        json_records = inspect_json(body)

        if json_records:
            print(
                "Potential structured records:",
                len(json_records),
            )

        interesting.append(
            {
                "response": entry,
                "strings": strings[:200],
                "json_records": json_records[:500],
            }
        )

    else:
        entry["interesting"] = False


def main():

    banner(
        "BMS TOXIC - MUMBAI CINEPOLIS "
        "NETWORK DISCOVERY"
    )

    print("Movie URL :", MOVIE_URL)
    print("City      :", CITY)
    print("Region    :", REGION)
    print("Date      :", DATE_CODE)
    print("Events    :", ", ".join(EVENT_CODES))

    print()
    print("IMPORTANT")
    print("This diagnostic version:")
    print("- Does NOT use Google Sheets")
    print("- Does NOT use credentials.json")
    print("- Does NOT use the seat API")
    print("- Does NOT modify your existing tracker")
    print("- Does NOT directly request the BMS showtime API")
    print("- Captures BMS webpage network responses")

    banner("LAUNCHING CHROMIUM")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        page.on(
            "response",
            lambda response: record_response(response)
        )

        banner("OPENING TOXIC MUMBAI PAGE")

        try:

            response = page.goto(
                MOVIE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print(
                    "Movie page HTTP status:",
                    response.status,
                )
            else:
                print(
                    "Movie page returned no response object."
                )

        except Exception as e:

            print(
                "Movie page navigation error:",
                repr(e),
            )

        banner("WAITING FOR BMS JAVASCRIPT")

        time.sleep(8)

        banner("INITIAL PAGE INFORMATION")

        try:
            print("Title:", page.title())
        except Exception:
            pass

        try:
            print("Current URL:", page.url)
        except Exception:
            pass

        try:
            print(
                "Page HTML size:",
                len(page.content()),
            )
        except Exception:
            pass

        banner("SCROLLING BMS PAGE")

        for i in range(1, 16):

            print(
                f"Scroll {i}/15"
            )

            try:
                page.mouse.wheel(
                    0,
                    1000,
                )
            except Exception:
                pass

            time.sleep(2)

        banner("WAITING FOR DELAYED BMS RESPONSES")

        time.sleep(10)

        banner("CLICKING POSSIBLE SHOWTIME CONTROLS")

        # Try harmless clicks on text that may expose the
        # cinema/showtime section.
        click_texts = [
            "Book Tickets",
            "Book ticket",
            "Showtimes",
            "SHOWTIMES",
            "View All",
            "View all",
        ]

        for text in click_texts:

            try:

                locator = page.get_by_text(
                    text,
                    exact=True,
                )

                count = locator.count()

                if count:

                    print(
                        f"Found clickable text: {text} "
                        f"({count})"
                    )

                    for j in range(min(count, 2)):

                        try:

                            locator.nth(j).click(
                                timeout=3000
                            )

                            print(
                                "Clicked:",
                                text,
                            )

                            time.sleep(4)

                        except Exception:
                            pass

            except Exception:
                pass

        banner("SECOND SCROLL PASS")

        for i in range(1, 11):

            print(
                f"Second scroll {i}/10"
            )

            try:
                page.mouse.wheel(
                    0,
                    1200,
                )
            except Exception:
                pass

            time.sleep(2)

        banner("FINAL WAIT")

        time.sleep(10)

        banner("PAGE TEXT SEARCH")

        try:

            text = page.locator("body").inner_text(
                timeout=10000
            )

            print(
                "Visible text size:",
                len(text),
            )

            lower = text.lower()

            terms = [
                "cinepolis",
                "toxic",
                "showtimes",
                "cinema",
                "mumbai",
            ]

            for term in terms:

                count = lower.count(term)

                print(
                    f"{term}: {count}"
                )

            if "cinepolis" in lower:

                print()
                print(
                    "CINEPOLIS TEXT WAS FOUND "
                    "ON THE RENDERED PAGE."
                )

                positions = []

                start = 0

                while True:

                    pos = lower.find(
                        "cinepolis",
                        start,
                    )

                    if pos == -1:
                        break

                    positions.append(pos)

                    start = pos + 1

                    if len(positions) >= 20:
                        break

                for pos in positions:

                    begin = max(
                        0,
                        pos - 250,
                    )

                    end = min(
                        len(text),
                        pos + 500,
                    )

                    print()
                    print(
                        "----- Cinepolis context -----"
                    )

                    print(
                        text[begin:end]
                    )

        except Exception as e:

            print(
                "Page text extraction error:",
                repr(e),
            )

        banner("CAPTURE SUMMARY")

        print(
            "Total BMS responses captured:",
            len(captured),
        )

        print(
            "Interesting responses:",
            len(interesting),
        )

        print(
            "Raw response directory:",
            str(OUTPUT_DIR),
        )

        # Save master response index.
        with open(
            "bms_network_index.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                captured,
                f,
                indent=2,
                ensure_ascii=False,
            )

        # Save interesting responses.
        with open(
            "bms_interesting_responses.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                interesting,
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        # Save cookies because they may be useful for
        # understanding the successful BMS session.
        try:

            cookies = context.cookies()

            with open(
                "bms_cookies.json",
                "w",
                encoding="utf-8",
            ) as f:

                json.dump(
                    cookies,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            print(
                "Cookies saved: bms_cookies.json"
            )

        except Exception as e:

            print(
                "Could not save cookies:",
                repr(e),
            )

        banner("CINEPOLIS SEARCH")

        cinepolis_results = []

        for item in interesting:

            strings = item.get(
                "strings",
                [],
            )

            for value in strings:

                if "cinepolis" in value.lower():

                    cinepolis_results.append(
                        {
                            "response_index":
                                item["response"]["index"],
                            "url":
                                item["response"]["url"],
                            "value":
                                value,
                        }
                    )

        if cinepolis_results:

            print(
                "Cinepolis references found:",
                len(cinepolis_results),
            )

            for item in cinepolis_results:

                print()
                print(
                    "Response:",
                    item["response_index"],
                )

                print(
                    "URL:",
                    item["url"][:500],
                )

                print(
                    "VALUE:",
                    item["value"],
                )

        else:

            print(
                "NO CINEPOLIS STRING FOUND "
                "IN CAPTURED BMS RESPONSES."
            )

        # Save Cinepolis-only search results.
        with open(
            "cinepolis_search_results.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                cinepolis_results,
                f,
                indent=2,
                ensure_ascii=False,
            )

        banner("FINAL FILES")

        print(
            "1. bms_network_index.json"
        )

        print(
            "2. bms_interesting_responses.json"
        )

        print(
            "3. bms_cookies.json"
        )

        print(
            "4. cinepolis_search_results.json"
        )

        print(
            "5. bms_capture/"
        )

        print()
        print(
            "DO NOT BUILD THE SHOW SCRAPER YET."
        )

        print(
            "First inspect the captured BMS responses."
        )

        print(
            "The next version will be built from "
            "the actual response structure."
        )

        browser.close()


if __name__ == "__main__":
    main()
