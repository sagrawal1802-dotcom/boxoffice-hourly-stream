import re
import json
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


MOVIE_URL = (
    "https://in.bookmyshow.com/movies/mumbai/"
    "toxic-a-fairy-tale-for-grown-ups/ET00379311"
)

TARGET_CITY = "mumbai"
TARGET_CHAIN = "cinepolis"


def print_header(title):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def normalise(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def looks_like_cinepolis(text):
    return "cinepolis" in normalise(text).lower()


def extract_venue_codes(text):
    """
    Extract BMS-style venue codes from URLs/text.
    This is deliberately broad because venue links can appear
    in different formats on BMS.
    """
    found = set()

    patterns = [
        r"/cinemas/[^/]+/[^/]+/buytickets/([A-Z0-9]+)",
        r"venueCode[=:][\"']?([A-Z0-9]+)",
        r'"venueCode"\s*:\s*"([A-Z0-9]+)"',
        r'"venue_code"\s*:\s*"([A-Z0-9]+)"',
        r'"venueCode"\s*:\s*([A-Z0-9]+)',
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            if match:
                found.add(match.upper())

    return found


def extract_cinepolis_from_links(page):
    results = []

    for link in page.locator("a").all():
        try:
            href = link.get_attribute("href") or ""
            text = normalise(link.inner_text(timeout=1000))
        except Exception:
            continue

        combined = f"{text} {href}"

        if not looks_like_cinepolis(combined):
            continue

        results.append({
            "name": text,
            "href": href,
            "source": "link",
        })

    return results


def extract_cinepolis_from_html(html):
    results = []

    # Look around occurrences of Cinepolis in the HTML.
    for match in re.finditer(
        r"cinepolis",
        html,
        flags=re.I
    ):
        start = max(0, match.start() - 1500)
        end = min(len(html), match.end() + 2500)
        block = html[start:end]

        venue_codes = extract_venue_codes(block)

        results.append({
            "name": None,
            "href": None,
            "venue_codes": sorted(venue_codes),
            "source": "html",
        })

    return results


def clean_name(name):
    name = normalise(name)

    if not name:
        return ""

    name = re.sub(
        r"\s+(?:Buy Tickets|Book Tickets|Tickets)$",
        "",
        name,
        flags=re.I,
    )

    return name.strip()


def main():

    print_header("BMS TOXIC MUMBAI CINEPOLIS PROPERTY DISCOVERY")

    print(f"Movie URL : {MOVIE_URL}")
    print("City      : MUMBAI")
    print("Chain     : CINEPOLIS")
    print("Mode      : PROPERTY DISCOVERY ONLY")

    print_header("LAUNCHING CHROMIUM")

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1366,
                "height": 768,
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        responses = []

        def capture_response(response):
            try:
                url = response.url.lower()

                if (
                    "bookmyshow" in url
                    and (
                        "showtime" in url
                        or "cinema" in url
                        or "venue" in url
                        or "movie" in url
                        or "trans" in url
                    )
                ):
                    responses.append({
                        "status": response.status,
                        "url": response.url,
                    })

            except Exception:
                pass

        page.on("response", capture_response)

        print_header("OPENING TOXIC MUMBAI PAGE")

        try:
            response = page.goto(
                MOVIE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print("HTTP status:", response.status)
            else:
                print("No main document response.")

        except Exception as e:
            print("Navigation error:", e)

        print("Waiting for BMS page data...")

        page.wait_for_timeout(10000)

        # Scroll several times so lazy-loaded cinema/show data can appear.
        print("Scrolling BMS page...")

        for i in range(8):
            try:
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(1000)
            except Exception:
                break

        print_header("COLLECTING PAGE DATA")

        try:
            html = page.content()
        except Exception:
            html = ""

        print("HTML size:", len(html))
        print("Links:", page.locator("a").count())

        link_results = extract_cinepolis_from_links(page)
        html_results = extract_cinepolis_from_html(html)

        print("Cinepolis-related links:", len(link_results))
        print("Cinepolis HTML matches:", len(html_results))

        # ------------------------------------------------------------
        # Build candidates
        # ------------------------------------------------------------

        candidates = []

        for item in link_results:

            name = clean_name(item.get("name"))
            href = item.get("href") or ""

            if not looks_like_cinepolis(
                f"{name} {href}"
            ):
                continue

            absolute_href = href

            if href.startswith("/"):
                absolute_href = (
                    "https://in.bookmyshow.com" + href
                )

            venue_codes = extract_venue_codes(
                f"{name} {href} {absolute_href}"
            )

            candidates.append({
                "name": name,
                "href": absolute_href,
                "venue_codes": sorted(venue_codes),
            })

        # ------------------------------------------------------------
        # Search raw HTML for Cinepolis venue URLs
        # ------------------------------------------------------------

        href_pattern = re.compile(
            r'href=["\']([^"\']*cinepolis[^"\']*)["\']',
            flags=re.I,
        )

        for href in href_pattern.findall(html):

            absolute_href = href

            if href.startswith("/"):
                absolute_href = (
                    "https://in.bookmyshow.com" + href
                )

            venue_codes = extract_venue_codes(
                absolute_href
            )

            candidates.append({
                "name": "",
                "href": absolute_href,
                "venue_codes": sorted(venue_codes),
            })

        # ------------------------------------------------------------
        # Deduplicate
        # ------------------------------------------------------------

        unique = {}

        for item in candidates:

            href = item.get("href") or ""
            codes = tuple(item.get("venue_codes") or [])

            key = (
                href.lower(),
                codes,
            )

            if key not in unique:
                unique[key] = item

        candidates = list(unique.values())

        # ------------------------------------------------------------
        # Print raw candidates
        # ------------------------------------------------------------

        print_header("CINEPOLIS CANDIDATES")

        if not candidates:
            print("NO CINEPOLIS CANDIDATES FOUND.")

        else:

            for index, item in enumerate(
                candidates,
                start=1
            ):

                print(f"\n[{index}]")

                print(
                    "Name       :",
                    item.get("name") or "(not extracted)",
                )

                print(
                    "Venue Code :",
                    ", ".join(
                        item.get("venue_codes") or []
                    ) or "(not found)",
                )

                print(
                    "URL        :",
                    item.get("href") or "(not found)",
                )

        # ------------------------------------------------------------
        # Browser storage/cookies
        # ------------------------------------------------------------

        print_header("BROWSER STATE")

        try:
            cookies = context.cookies()

            print(
                "Cookies:",
                len(cookies)
            )

            for cookie in cookies:

                name = cookie.get("name", "")

                if name in (
                    "cf_clearance",
                    "__cf_bm",
                ):
                    print(
                        name,
                        "= present"
                    )

        except Exception as e:
            print(
                "Could not inspect cookies:",
                e
            )

        # ------------------------------------------------------------
        # Network summary
        # ------------------------------------------------------------

        print_header("CAPTURED BMS RESPONSES")

        for item in responses:
            print(
                item["status"],
                item["url"]
            )

        # ------------------------------------------------------------
        # Save debugging information
        # ------------------------------------------------------------

        debug = {
            "timestamp": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "movie_url": MOVIE_URL,
            "city": TARGET_CITY,
            "chain": TARGET_CHAIN,
            "candidates": candidates,
            "responses": responses,
        }

        with open(
            "cinepolis_discovery.json",
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                debug,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print_header("DISCOVERY COMPLETE")

        print(
            "Cinepolis candidates:",
            len(candidates)
        )

        print(
            "Saved:",
            "cinepolis_discovery.json"
        )

        browser.close()


if __name__ == "__main__":
    main()
