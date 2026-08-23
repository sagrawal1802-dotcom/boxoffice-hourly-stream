import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

MOVIE_URL = "https://in.bookmyshow.com/movies/mumbai/toxic-a-fairy-tale-for-grown-ups/ET00379311"

OUT_DIR = Path("bms_showtime_diagnostic")
OUT_DIR.mkdir(exist_ok=True)

HTML_FILE = OUT_DIR / "initial_bms_document.html"
MATCH_FILE = OUT_DIR / "showtime_matches.json"


def print_line():
    print("=" * 100)


def safe_text(value):
    if value is None:
        return ""
    return str(value)


def recursive_find(obj, path="root", results=None):
    if results is None:
        results = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            key_lower = str(key).lower()

            if key_lower in {
                "showtimessections",
                "flatshowtimes",
                "sessionid",
                "venuecode",
                "showdate",
                "showtimes",
                "venue",
            }:
                results.append({
                    "path": path,
                    "key": key,
                    "value": value
                })

            recursive_find(value, f"{path}.{key}", results)

    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            recursive_find(value, f"{path}[{i}]", results)

    return results


def search_html(html):
    terms = [
        "showtimesSections",
        "flatShowtimes",
        "sessionId",
        "venueCode",
        "showDate",
        "showtimes",
        "availStatus",
        "additionalData",
    ]

    matches = {}

    for term in terms:
        positions = []
        start = 0

        while True:
            pos = html.find(term, start)

            if pos == -1:
                break

            positions.append(pos)
            start = pos + len(term)

            if len(positions) >= 50:
                break

        matches[term] = positions

    return matches


def extract_contexts(html, positions, radius=1500):
    contexts = []

    for pos in positions:
        start = max(0, pos - radius)
        end = min(len(html), pos + radius)

        contexts.append({
            "position": pos,
            "context": html[start:end]
        })

    return contexts


def try_extract_json_scripts(page):
    """
    Look through script tags for JSON-like objects.
    We do NOT assume a specific BMS internal variable name.
    """

    candidates = []

    scripts = page.locator("script")

    count = scripts.count()

    print(f"Script tags found: {count}")

    for i in range(count):
        try:
            text = scripts.nth(i).text_content(timeout=2000)

            if not text:
                continue

            interesting = any(
                term in text
                for term in [
                    "showtimesSections",
                    "flatShowtimes",
                    "sessionId",
                    "venueCode",
                    "showtimes",
                ]
            )

            if interesting:
                candidates.append({
                    "script_index": i,
                    "size": len(text),
                    "text": text
                })

        except Exception:
            pass

    return candidates


print_line()
print("BMS TOXIC - INITIAL SHOWTIME STRUCTURE DIAGNOSTIC")
print_line()

print()
print("Movie URL:")
print(MOVIE_URL)

print()
print("THIS VERSION:")
print("- Does NOT access Google Sheets")
print("- Does NOT use credentials.json")
print("- Does NOT call the seat API")
print("- Does NOT call the showtime API directly")
print("- Does NOT modify YAML")
print("- Does NOT modify the existing tracker")
print("- Does NOT use the 7 Cinepolis codes")
print("- Only investigates the BMS page structure")

print_line()

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )

    context = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
    )

    page = context.new_page()

    document_response = None

    def response_handler(response):
        nonlocal document_response

        try:
            if response.request.resource_type == "document":
                if "bookmyshow.com/movies/" in response.url:
                    document_response = response

                    print()
                    print("[DOCUMENT RESPONSE]")
                    print("Status :", response.status)
                    print("URL    :", response.url)

        except Exception:
            pass

    page.on("response", response_handler)

    print()
    print("OPENING BMS MOVIE PAGE")
    print_line()

    try:
        response = page.goto(
            MOVIE_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        print("Page HTTP status:", response.status if response else "NONE")

    except Exception as e:
        print("Page open warning:", e)

    print()
    print("Waiting for initial BMS data...")

    time.sleep(8)

    print()
    print("Current URL:")
    print(page.url)

    print()
    print("Page title:")
    print(page.title())

    # ------------------------------------------------------------------
    # 1. Capture complete DOM HTML
    # ------------------------------------------------------------------

    print_line()
    print("CAPTURING CURRENT DOM HTML")
    print_line()

    html = page.content()

    HTML_FILE.write_text(
        html,
        encoding="utf-8"
    )

    print("HTML size:", len(html))
    print("Saved:", HTML_FILE)

    # ------------------------------------------------------------------
    # 2. Search DOM for known showtime structures
    # ------------------------------------------------------------------

    print_line()
    print("SEARCHING DOM HTML")
    print_line()

    matches = search_html(html)

    for term, positions in matches.items():
        print(f"{term:20} : {len(positions)} matches")

    # ------------------------------------------------------------------
    # 3. Save surrounding contexts
    # ------------------------------------------------------------------

    all_contexts = {}

    for term, positions in matches.items():

        if positions:
            all_contexts[term] = extract_contexts(
                html,
                positions[:10]
            )

    # ------------------------------------------------------------------
    # 4. Inspect script tags
    # ------------------------------------------------------------------

    print_line()
    print("SEARCHING SCRIPT TAGS")
    print_line()

    script_candidates = try_extract_json_scripts(page)

    print()
    print("Interesting scripts:", len(script_candidates))

    for item in script_candidates:
        print(
            "Script:",
            item["script_index"],
            "| Size:",
            item["size"]
        )

    # Save only metadata + first chunks to avoid gigantic output
    script_output = []

    for item in script_candidates:
        script_output.append({
            "script_index": item["script_index"],
            "size": item["size"],
            "text_preview": item["text"][:20000],
        })

    # ------------------------------------------------------------------
    # 5. Try to locate JSON-looking objects in HTML
    # ------------------------------------------------------------------

    print_line()
    print("SEARCHING FOR JSON-LIKE SHOWTIME OBJECTS")
    print_line()

    json_candidates = []

    important_terms = [
        "showtimesSections",
        "flatShowtimes",
        "sessionId",
        "venueCode",
    ]

    for term in important_terms:

        for pos in matches.get(term, [])[:10]:

            start = max(0, pos - 5000)
            end = min(len(html), pos + 15000)

            chunk = html[start:end]

            json_candidates.append({
                "term": term,
                "position": pos,
                "chunk": chunk
            })

    # ------------------------------------------------------------------
    # 6. Search for known Cinepolis codes
    # ------------------------------------------------------------------

    print_line()
    print("SEARCHING KNOWN CINEPOLIS CODES")
    print_line()

    # These are the confirmed codes from your HAR/work so far.
    known_codes = [
        "CSWO",
        "CPVV",
    ]

    code_results = {}

    for code in known_codes:

        positions = []

        start = 0

        while True:

            pos = html.find(code, start)

            if pos == -1:
                break

            positions.append(pos)
            start = pos + len(code)

            if len(positions) >= 50:
                break

        code_results[code] = {
            "count": len(positions),
            "contexts": extract_contexts(
                html,
                positions[:10],
                radius=2000
            )
        }

        print(
            f"{code:10} : {len(positions)} matches"
        )

    # ------------------------------------------------------------------
    # 7. Build diagnostic output
    # ------------------------------------------------------------------

    diagnostic = {
        "movie_url": MOVIE_URL,
        "page_url": page.url,
        "page_title": page.title(),
        "html_size": len(html),

        "term_matches": {
            k: len(v)
            for k, v in matches.items()
        },

        "contexts": all_contexts,

        "interesting_scripts": script_output,

        "json_candidates": json_candidates,

        "cinepolis_codes": code_results,
    }

    MATCH_FILE.write_text(
        json.dumps(
            diagnostic,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    # ------------------------------------------------------------------
    # 8. Print important findings
    # ------------------------------------------------------------------

    print_line()
    print("DIAGNOSTIC SUMMARY")
    print_line()

    print()
    print("HTML size:", len(html))

    print()
    print("STRUCTURE MATCHES:")

    for term, positions in matches.items():
        print(
            f"  {term:20} -> {len(positions)}"
        )

    print()
    print("INTERESTING SCRIPT TAGS:")
    print(" ", len(script_candidates))

    print()
    print("KNOWN VENUE CODES:")

    for code, data in code_results.items():
        print(
            f"  {code:10} -> {data['count']} HTML matches"
        )

    print()
    print("Files created:")
    print("1.", HTML_FILE)
    print("2.", MATCH_FILE)

    print_line()

    browser.close()

print()
print("DIAGNOSTIC COMPLETED")
print_line()
