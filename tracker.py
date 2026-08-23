import json
import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

CITY = "mumbai"

# These were discovered in the previous browser capture.
# We will VERIFY them instead of assuming they are Cinepolis.
CANDIDATE_CODES = [
    "CPVV",
    "FMRL",
    "FNCM",
    "GATY",
    "MTCR",
    "MUCK",
    "MXBY",
    "PDDV",
    "PMPK",
    "POLM",
]

OUTPUT_FILE = "cinepolis_mumbai_properties.json"

HEADLESS = True


# ============================================================
# PRINT HELPERS
# ============================================================

def banner(title):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


# ============================================================
# NORMALIZE
# ============================================================

def normalize(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text.replace("\n", " ")
    ).strip()


# ============================================================
# FIND CINEPOLIS LINKS IN HTML
# ============================================================

def extract_cinepolis_links(html):

    results = []

    patterns = [
        r'href=["\']([^"\']*cinepolis[^"\']*)["\']',
        r'(?:https://in\.bookmyshow\.com)?'
        r'(/cinemas/[^"\']*cinepolis[^"\']*)',
    ]

    for pattern in patterns:

        for match in re.findall(
            pattern,
            html,
            flags=re.IGNORECASE
        ):

            if isinstance(match, tuple):
                match = match[0]

            value = match.strip()

            if value and value not in results:
                results.append(value)

    return results


# ============================================================
# EXTRACT CINEMA LINKS FROM PAGE
# ============================================================

def extract_cinema_links(page):

    links = []

    anchors = page.locator("a").all()

    for anchor in anchors:

        try:
            href = anchor.get_attribute("href")
            text = normalize(anchor.inner_text())

        except Exception:
            continue

        if not href:
            continue

        href_lower = href.lower()

        if "/cinemas/" not in href_lower:
            continue

        full_url = urljoin(
            "https://in.bookmyshow.com",
            href
        )

        item = {
            "name": text,
            "url": full_url,
        }

        if item not in links:
            links.append(item)

    return links


# ============================================================
# SEARCH CODE IN HTML
# ============================================================

def code_contexts(html, code):

    contexts = []

    for match in re.finditer(
        re.escape(code),
        html,
        flags=re.IGNORECASE
    ):

        start = max(0, match.start() - 500)
        end = min(
            len(html),
            match.end() + 1000
        )

        context = html[start:end]

        if context not in contexts:
            contexts.append(context)

    return contexts


# ============================================================
# EXTRACT VENUE NAME FROM CONTEXT
# ============================================================

def extract_names_from_context(context):

    names = []

    patterns = [

        # JSON-style venueName
        r'"venueName"\s*:\s*"([^"]+)"',

        # cinemaName
        r'"cinemaName"\s*:\s*"([^"]+)"',

        # name
        r'"name"\s*:\s*"([^"]*Cinepolis[^"]*)"',
    ]

    for pattern in patterns:

        for match in re.findall(
            pattern,
            context,
            flags=re.IGNORECASE
        ):

            value = normalize(match)

            if value and value not in names:
                names.append(value)

    return names


# ============================================================
# VERIFY A VENUE CODE
# ============================================================

def verify_candidate(page, code):

    banner(f"VERIFYING VENUE CODE: {code}")

    result = {
        "code": code,
        "cinepolis": False,
        "names": [],
        "urls": [],
        "contexts": [],
    }

    # --------------------------------------------------------
    # Search current movie HTML
    # --------------------------------------------------------

    try:
        html = page.content()
    except Exception:
        html = ""

    contexts = code_contexts(
        html,
        code
    )

    print(
        f"Movie HTML contexts containing {code}: "
        f"{len(contexts)}"
    )

    for context in contexts:

        if "cinepolis" not in context.lower():
            continue

        result["cinepolis"] = True

        names = extract_names_from_context(
            context
        )

        for name in names:
            if name not in result["names"]:
                result["names"].append(name)

        result["contexts"].append(
            context[:1500]
        )

    # --------------------------------------------------------
    # Search links on movie page
    # --------------------------------------------------------

    links = extract_cinema_links(page)

    for item in links:

        if code.lower() in item["url"].lower():

            result["urls"].append(
                item["url"]
            )

            if "cinepolis" in (
                item["url"] + " " + item["name"]
            ).lower():

                result["cinepolis"] = True

                if item["name"]:
                    if item["name"] not in result["names"]:
                        result["names"].append(
                            item["name"]
                        )

    # --------------------------------------------------------
    # Print result
    # --------------------------------------------------------

    print()
    print(f"Code       : {code}")
    print(
        f"Cinepolis  : "
        f"{'YES' if result['cinepolis'] else 'NO'}"
    )

    if result["names"]:
        print("Names:")
        for name in result["names"]:
            print(f"  - {name}")

    if result["urls"]:
        print("URLs:")
        for url in result["urls"]:
            print(f"  - {url}")

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    banner(
        "BMS TOXIC - MUMBAI CINEPOLIS VENUE VERIFICATION"
    )

    print(f"Movie URL : {MOVIE_URL}")
    print(f"City      : {CITY}")

    print()
    print("Candidate venue codes:")
    print(", ".join(CANDIDATE_CODES))

    print()
    print("This version:")
    print(" - Uses Playwright")
    print(" - Opens the existing BMS movie page")
    print(" - Uses the 10 candidate codes already discovered")
    print(" - Verifies Cinepolis association")
    print(" - Does NOT call seat API")
    print(" - Does NOT call showtime API")
    print(" - Does NOT access Google Sheets")
    print(" - Does NOT modify YAML")
    print(" - Does NOT modify existing tracker")

    all_results = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=HEADLESS
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Capture every response
        # ----------------------------------------------------

        captured_responses = []

        def handle_response(response):

            try:

                url = response.url

                if (
                    "bookmyshow.com" not in
                    url.lower()
                ):
                    return

                captured_responses.append({
                    "url": url,
                    "status": response.status,
                    "resource_type": response.request.resource_type,
                })

            except Exception:
                pass

        page.on(
            "response",
            handle_response
        )

        # ----------------------------------------------------
        # OPEN MOVIE PAGE
        # ----------------------------------------------------

        banner("OPENING TOXIC MUMBAI PAGE")

        response = page.goto(
            MOVIE_URL,
            wait_until="domcontentloaded",
            timeout=90000
        )

        if response:
            print(
                f"Movie page HTTP status: "
                f"{response.status}"
            )

        print(
            "Waiting for BMS JavaScript..."
        )

        page.wait_for_timeout(8000)

        # ----------------------------------------------------
        # SCROLL
        # ----------------------------------------------------

        banner("SCROLLING BMS PAGE")

        for i in range(12):

            page.mouse.wheel(
                0,
                1000
            )

            page.wait_for_timeout(
                700
            )

            print(
                f"Scroll {i + 1}/12"
            )

        page.wait_for_timeout(5000)

        # ----------------------------------------------------
        # PAGE HTML
        # ----------------------------------------------------

        html = page.content()

        print()
        print(
            f"Page HTML size: "
            f"{len(html)}"
        )

        # ----------------------------------------------------
        # DIRECT CINEPOLIS LINKS
        # ----------------------------------------------------

        banner(
            "DIRECT CINEPOLIS LINKS IN MOVIE PAGE"
        )

        cinepolis_links = extract_cinepolis_links(
            html
        )

        if cinepolis_links:

            for link in cinepolis_links:
                print(
                    f"FOUND: {link}"
                )

        else:

            print(
                "No direct Cinepolis links found."
            )

        # ----------------------------------------------------
        # VERIFY CANDIDATES
        # ----------------------------------------------------

        banner(
            "VERIFYING ALL DISCOVERED VENUE CODES"
        )

        for code in CANDIDATE_CODES:

            result = verify_candidate(
                page,
                code
            )

            all_results.append(
                result
            )

            time.sleep(0.5)

        # ----------------------------------------------------
        # CLOSE
        # ----------------------------------------------------

        browser.close()

    # ========================================================
    # FINAL FILTER
    # ========================================================

    cinepolis_properties = []

    for result in all_results:

        if not result["cinepolis"]:
            continue

        code = result["code"]

        names = result["names"]

        urls = result["urls"]

        # Try to derive a cinema URL if we know
        # the Cinepolis slug from the name.
        primary_url = (
            urls[0]
            if urls
            else None
        )

        property_record = {
            "venue_code": code,
            "venue_names": names,
            "urls": urls,
            "primary_url": primary_url,
        }

        cinepolis_properties.append(
            property_record
        )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    banner(
        "FINAL CINEPOLIS PROPERTY LIST"
    )

    if not cinepolis_properties:

        print(
            "NO CINEPOLIS PROPERTIES VERIFIED."
        )

    else:

        for index, item in enumerate(
            cinepolis_properties,
            1
        ):

            print(
                f"{index}. "
                f"{item['venue_names']}"
            )

            print(
                f"   BMS Code: "
                f"{item['venue_code']}"
            )

            if item["primary_url"]:
                print(
                    f"   URL: "
                    f"{item['primary_url']}"
                )

    # ========================================================
    # SAVE
    # ========================================================

    output = {
        "movie_url": MOVIE_URL,
        "city": CITY,
        "candidate_codes": CANDIDATE_CODES,
        "verified_cinepolis_properties":
            cinepolis_properties,
        "all_candidate_results":
            all_results,
        "captured_response_count":
            len(captured_responses),
        "captured_responses":
            captured_responses,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print(
        f"Saved: {OUTPUT_FILE}"
    )

    print()
    print(
        f"Verified Cinepolis properties: "
        f"{len(cinepolis_properties)}"
    )


if __name__ == "__main__":
    main()
