import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

# ============================================================
# CONFIG
# ============================================================

CITY = "mumbai"
REGION = "MUMBAI"

EVENT_CODE = "ET00379311"

MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

OUTPUT_DIR = Path("cinepolis_discovery")
OUTPUT_DIR.mkdir(exist_ok=True)

RAW_RESPONSES_FILE = OUTPUT_DIR / "all_bms_responses.json"
CINEPOLIS_RESULTS_FILE = OUTPUT_DIR / "cinepolis_candidates.json"
HTML_FILE = OUTPUT_DIR / "toxic_movie_page.html"
TEXT_FILE = OUTPUT_DIR / "toxic_movie_text.txt"


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).replace("\x00", "").strip()


def extract_codes(text):
    """
    Extract likely BMS venue/cinema codes.

    We deliberately collect several patterns rather than assuming
    a single venue-code format.
    """

    if not text:
        return set()

    codes = set()

    # Explicit BMS venue URL/code patterns
    patterns = [
        r"/cinemas/[^\"'<> ]+/([A-Z0-9]{3,12})(?:[\"'/?#]|$)",
        r"cinemas/[^\s\"'<>]+/([A-Z0-9]{3,12})",
        r'"venueCode"\s*:\s*"([^"]+)"',
        r'"venue_code"\s*:\s*"([^"]+)"',
        r'"strVenueCode"\s*:\s*"([^"]+)"',
        r'"cinemaCode"\s*:\s*"([^"]+)"',
        r'"cinema_code"\s*:\s*"([^"]+)"',
        r'"propertyCode"\s*:\s*"([^"]+)"',
        r'"property_code"\s*:\s*"([^"]+)"',
        r'"cineCode"\s*:\s*"([^"]+)"',
    ]

    for pattern in patterns:
        try:
            matches = re.findall(pattern, text, flags=re.I)

            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]

                match = clean_text(match)

                if not match:
                    continue

                # Avoid obvious non-venue values
                if match.lower() in {
                    "mumbai",
                    "cinemas",
                    "movies",
                    "movie",
                    "true",
                    "false",
                    "null",
                }:
                    continue

                if 2 <= len(match) <= 15:
                    codes.add(match)

        except Exception:
            pass

    return codes


def extract_cinepolis_context(text):
    """
    Find every Cinepolis occurrence and capture a large surrounding
    context window.
    """

    results = []

    if not text:
        return results

    lower = text.lower()

    positions = []

    start = 0

    while True:
        pos = lower.find("cinepolis", start)

        if pos == -1:
            break

        positions.append(pos)
        start = pos + len("cinepolis")

    for pos in positions:

        left = max(0, pos - 2500)
        right = min(len(text), pos + 5000)

        context = text[left:right]

        results.append({
            "position": pos,
            "context": context
        })

    return results


def extract_cinepolis_urls(text):
    """
    Extract BMS cinema URLs containing Cinepolis.
    """

    urls = set()

    if not text:
        return urls

    patterns = [
        r'https?://in\.bookmyshow\.com/cinemas/[^"\']*cinepolis[^"\']*',
        r'/cinemas/[^"\']*cinepolis[^"\']*',
        r'cinemas/mumbai/[^"\']*cinepolis[^"\']*',
    ]

    for pattern in patterns:

        try:
            matches = re.findall(pattern, text, flags=re.I)

            for match in matches:

                match = clean_text(match)

                if match:
                    urls.add(match)

        except Exception:
            pass

    return urls


def extract_venue_names(text):
    """
    Try to extract strings around Cinepolis references.
    """

    names = set()

    if not text:
        return names

    patterns = [
        r'"(?:venueName|venue_name|cinemaName|cinema_name|propertyName|property_name)"\s*:\s*"([^"]*cinepolis[^"]*)"',
        r'"name"\s*:\s*"([^"]*cinepolis[^"]*)"',
        r'(Cinepolis[^"<>\n]{0,150})',
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                text,
                flags=re.I
            )

            for match in matches:

                match = clean_text(match)

                if match and "cinepolis" in match.lower():
                    names.add(match)

        except Exception:
            pass

    return names


# ============================================================
# MAIN
# ============================================================

print("=" * 100)
print("BMS TOXIC - CINEPOLIS VENUE DISCOVERY")
print("=" * 100)

print()
print("Movie URL :", MOVIE_URL)
print("City      :", CITY)
print("Region    :", REGION)
print("Event     :", EVENT_CODE)

print()
print("THIS VERSION:")
print("- Uses Playwright browser session")
print("- Captures ALL BMS browser responses")
print("- Searches document HTML")
print("- Searches response bodies")
print("- Searches Cinepolis context")
print("- Searches venue codes")
print("- Searches BMS cinema URLs")
print("- Does NOT call seat API")
print("- Does NOT access Google Sheets")
print("- Does NOT modify tracker")
print("- Does NOT change YAML")

print("=" * 100)


captured = []


# ============================================================
# PLAYWRIGHT
# ============================================================

with sync_playwright() as p:

    print()
    print("=" * 100)
    print("LAUNCHING CHROMIUM")
    print("=" * 100)

    browser = p.chromium.launch(
        headless=True
    )

    context = browser.new_context(
        viewport={
            "width": 1440,
            "height": 1000
        },
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        )
    )

    page = context.new_page()

    # --------------------------------------------------------
    # RESPONSE CAPTURE
    # --------------------------------------------------------

    def handle_response(response):

        try:

            url = response.url

            if not url:
                return

            # Only retain BookMyShow / relevant browser data.
            if (
                "bookmyshow.com" not in url.lower()
                and "clickstream" not in url.lower()
            ):
                return

            request = response.request

            resource_type = request.resource_type

            body = ""

            # We want document, xhr, fetch and script responses.
            if resource_type in {
                "document",
                "xhr",
                "fetch",
                "script"
            }:

                try:
                    body = response.text()
                except Exception:
                    body = ""

            record = {
                "index": len(captured) + 1,
                "status": response.status,
                "resource_type": resource_type,
                "url": url,
                "method": request.method,
                "size": len(body),
                "body": body
            }

            captured.append(record)

            lower_body = body.lower()

            if "cinepolis" in lower_body:

                print()
                print("-" * 100)
                print("[CINEPOLIS RESPONSE FOUND]")
                print("Status :", response.status)
                print("Type   :", resource_type)
                print("Size   :", len(body))
                print("URL    :", url)
                print("-" * 100)

        except Exception:
            pass


    page.on("response", handle_response)

    # --------------------------------------------------------
    # OPEN PAGE
    # --------------------------------------------------------

    print()
    print("=" * 100)
    print("OPENING TOXIC MUMBAI PAGE")
    print("=" * 100)

    try:

        response = page.goto(
            MOVIE_URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        if response:
            print(
                "Movie page HTTP status:",
                response.status
            )

    except Exception as error:

        print(
            "Page open warning:",
            repr(error)
        )

    print()
    print("Waiting for BMS JavaScript...")

    time.sleep(8)

    # --------------------------------------------------------
    # SAVE INITIAL HTML
    # --------------------------------------------------------

    try:

        html = page.content()

        HTML_FILE.write_text(
            html,
            encoding="utf-8"
        )

        print(
            "Page HTML size:",
            len(html)
        )

    except Exception as error:

        print(
            "Could not capture HTML:",
            repr(error)
        )

        html = ""

    # --------------------------------------------------------
    # SAVE VISIBLE TEXT
    # --------------------------------------------------------

    try:

        visible_text = page.locator("body").inner_text()

        TEXT_FILE.write_text(
            visible_text,
            encoding="utf-8"
        )

        print(
            "Visible text size:",
            len(visible_text)
        )

    except Exception:

        visible_text = ""

    # --------------------------------------------------------
    # SCROLL SLOWLY
    # --------------------------------------------------------

    print()
    print("=" * 100)
    print("SCROLLING PAGE")
    print("=" * 100)

    for i in range(1, 21):

        try:

            page.evaluate(
                """
                () => {
                    window.scrollTo(
                        0,
                        document.body.scrollHeight
                    );
                }
                """
            )

        except Exception:
            pass

        print(
            f"Scroll {i}/20"
        )

        time.sleep(1.2)

    # --------------------------------------------------------
    # SCROLL BACK TOP
    # --------------------------------------------------------

    try:

        page.evaluate(
            """
            () => {
                window.scrollTo(0, 0);
            }
            """
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # WAIT FOR DELAYED RESPONSES
    # --------------------------------------------------------

    print()
    print(
        "Waiting for delayed BMS responses..."
    )

    time.sleep(8)

    # --------------------------------------------------------
    # FINAL HTML
    # --------------------------------------------------------

    try:

        final_html = page.content()

        HTML_FILE.write_text(
            final_html,
            encoding="utf-8"
        )

        html = final_html

    except Exception:
        pass

    browser.close()


# ============================================================
# SAVE ALL CAPTURED RESPONSES
# ============================================================

print()
print("=" * 100)
print("CAPTURE SUMMARY")
print("=" * 100)

print(
    "Total BMS responses captured:",
    len(captured)
)

try:

    RAW_RESPONSES_FILE.write_text(
        json.dumps(
            captured,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

except Exception as error:

    print(
        "Could not save raw responses:",
        repr(error)
    )


# ============================================================
# SEARCH EVERYTHING
# ============================================================

print()
print("=" * 100)
print("SEARCHING ALL CAPTURED DATA")
print("=" * 100)


candidate_records = []


# ------------------------------------------------------------
# SEARCH PAGE HTML
# ------------------------------------------------------------

all_sources = [
    {
        "source": "movie_page_html",
        "url": MOVIE_URL,
        "text": html
    }
]


# ------------------------------------------------------------
# SEARCH EVERY RESPONSE
# ------------------------------------------------------------

for item in captured:

    body = item.get("body", "")

    if not body:
        continue

    all_sources.append({
        "source": f"response_{item['index']}",
        "url": item.get("url"),
        "text": body
    })


# ============================================================
# PROCESS SOURCES
# ============================================================

for source in all_sources:

    text = source["text"]

    if not text:
        continue

    lower = text.lower()

    if "cinepolis" not in lower:
        continue

    print()
    print("-" * 100)
    print("CINEPOLIS FOUND")
    print("Source:", source["source"])
    print("URL   :", source["url"])
    print("-" * 100)

    contexts = extract_cinepolis_context(
        text
    )

    urls = extract_cinepolis_urls(
        text
    )

    codes = extract_codes(
        text
    )

    names = extract_venue_names(
        text
    )

    print(
        "Contexts:",
        len(contexts)
    )

    print(
        "URLs:",
        len(urls)
    )

    print(
        "Potential codes:",
        sorted(codes)
    )

    print(
        "Venue names:",
        sorted(names)
    )

    candidate_records.append({
        "source": source["source"],
        "url": source["url"],
        "cinepolis_occurrences": len(contexts),
        "cinepolis_urls": sorted(urls),
        "potential_codes": sorted(codes),
        "venue_names": sorted(names),
        "contexts": contexts
    })


# ============================================================
# DEDUPLICATE VENUE CODES
# ============================================================

print()
print("=" * 100)
print("BUILDING UNIQUE CINEPOLIS CANDIDATES")
print("=" * 100)


unique_codes = set()
unique_names = set()
unique_urls = set()


for record in candidate_records:

    for code in record.get(
        "potential_codes",
        []
    ):
        unique_codes.add(code)

    for name in record.get(
        "venue_names",
        []
    ):
        unique_names.add(name)

    for url in record.get(
        "cinepolis_urls",
        []
    ):
        unique_urls.add(url)


# ============================================================
# IMPORTANT: ONLY TRUST EXPLICIT CINEPOLIS CONTEXT
# ============================================================

explicit_candidates = []


for record in candidate_records:

    names = record.get(
        "venue_names",
        []
    )

    urls = record.get(
        "cinepolis_urls",
        []
    )

    codes = record.get(
        "potential_codes",
        []
    )

    # A code alone is NOT treated as Cinepolis.
    # It must occur in the same source as Cinepolis text.

    if names or urls:

        explicit_candidates.append({
            "source": record["source"],
            "url": record["url"],
            "venue_names": names,
            "cinepolis_urls": urls,
            "potential_codes": codes
        })


# ============================================================
# PRINT RESULTS
# ============================================================

print()
print("=" * 100)
print("CINEPOLIS REFERENCES")
print("=" * 100)

print(
    "Sources containing Cinepolis:",
    len(candidate_records)
)

print(
    "Unique possible codes:",
    len(unique_codes)
)

print(
    "Unique venue names:",
    len(unique_names)
)

print(
    "Unique Cinepolis URLs:",
    len(unique_urls)
)


print()
print("=" * 100)
print("VENUE NAMES")
print("=" * 100)

for name in sorted(unique_names):

    print(
        " -",
        name
    )


print()
print("=" * 100)
print("CINEPOLIS URLS")
print("=" * 100)

for url in sorted(unique_urls):

    print(
        " -",
        url
    )


print()
print("=" * 100)
print("POTENTIAL VENUE CODES")
print("=" * 100)

for code in sorted(unique_codes):

    print(
        " -",
        code
    )


# ============================================================
# SAVE STRUCTURED RESULTS
# ============================================================

output = {
    "movie_url": MOVIE_URL,
    "city": CITY,
    "region": REGION,
    "event_code": EVENT_CODE,
    "total_responses": len(captured),
    "sources_with_cinepolis": len(candidate_records),
    "unique_possible_codes": sorted(unique_codes),
    "unique_venue_names": sorted(unique_names),
    "unique_cinepolis_urls": sorted(unique_urls),
    "explicit_candidates": explicit_candidates,
    "source_records": candidate_records
}


try:

    CINEPOLIS_RESULTS_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

except Exception as error:

    print(
        "Could not save candidates:",
        repr(error)
    )


# ============================================================
# FINAL
# ============================================================

print()
print("=" * 100)
print("DISCOVERY COMPLETED")
print("=" * 100)

print(
    "Cinepolis sources:",
    len(candidate_records)
)

print(
    "Possible venue codes:",
    len(unique_codes)
)

print(
    "Venue names:",
    len(unique_names)
)

print()
print("Files saved:")
print(
    "1.",
    RAW_RESPONSES_FILE
)
print(
    "2.",
    CINEPOLIS_RESULTS_FILE
)
print(
    "3.",
    HTML_FILE
)
print(
    "4.",
    TEXT_FILE
)

print()
print("IMPORTANT:")
print(
    "Do NOT build the show/seat scraper from this run yet."
)

print(
    "We first need to inspect the discovered Cinepolis venue"
    " codes and their surrounding BMS structure."
)

print("=" * 100)
