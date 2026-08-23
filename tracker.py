import json
import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


BMS_URL = "https://in.bookmyshow.com/cinemas-list/cinepolis/mumbai/cnpl"
OUTPUT_FILE = "cinepolis_mumbai_properties.json"


def print_line(char="=", length=100):
    print(char * length)


def clean_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_code_from_url(url):
    if not url:
        return ""

    # Examples:
    # /buytickets/CPNM/20260826
    # /CPNM
    # /cinemas/.../CPNM
    match = re.search(r"/([A-Z0-9]{4,8})(?:/|$|\?)", url)

    if match:
        code = match.group(1)

        # Avoid obvious non-cinema path components
        invalid = {
            "MUMBAI",
            "CINEMA",
            "CINEMAS",
            "BUY",
            "TICKETS",
            "CNPL",
        }

        if code not in invalid:
            return code

    return ""


def extract_properties_from_page(page):
    properties = []

    links = page.locator("a").all()

    print()
    print_line("-")
    print("ANALYSING BMS CINEMA LINKS")
    print_line("-")

    print(f"Total links found: {len(links)}")

    for index, link in enumerate(links, start=1):
        try:
            href = link.get_attribute("href")
            text = clean_text(link.inner_text())

            if not href:
                continue

            full_url = urljoin("https://in.bookmyshow.com", href)

            combined = f"{text} {full_url}".lower()

            # We only want Cinepolis cinema/property links
            if "cinepolis" not in combined:
                continue

            # Ignore chain navigation pages
            if "/cinemas-list/cinepolis" in full_url.lower():
                continue

            # Ignore irrelevant pages
            if "/movies/" in full_url.lower():
                continue

            code = extract_code_from_url(full_url)

            property_name = text

            # Sometimes anchor text is empty.
            if not property_name:
                match = re.search(
                    r"/cinemas/mumbai/([^/]+)",
                    full_url,
                    re.IGNORECASE,
                )

                if match:
                    slug = match.group(1)
                    property_name = slug.replace("-", " ").title()

            if not property_name:
                continue

            record = {
                "property_name": property_name,
                "bms_code": code,
                "url": full_url,
            }

            properties.append(record)

            print()
            print(f"Candidate #{len(properties)}")
            print(f"Name : {property_name}")
            print(f"Code : {code}")
            print(f"URL  : {full_url}")

        except Exception as e:
            print(f"Link {index} error: {e}")

    return properties


def deduplicate_properties(properties):
    unique = {}

    for item in properties:
        name = clean_text(item.get("property_name", ""))
        code = clean_text(item.get("bms_code", ""))
        url = clean_text(item.get("url", ""))

        key = code.upper() if code else url.lower()

        if not key:
            key = name.lower()

        if key not in unique:
            unique[key] = {
                "property_name": name,
                "bms_code": code,
                "url": url,
            }

    return list(unique.values())


def main():

    print_line()
    print("BMS TOXIC PROJECT - CINEPOLIS MUMBAI PROPERTY DISCOVERY")
    print_line()

    print()
    print("Source:")
    print(BMS_URL)

    print()
    print("MODE:")
    print("CINEPOLIS PROPERTY DISCOVERY ONLY")

    print()
    print("NO GOOGLE SHEETS")
    print("NO CREDENTIALS.JSON")
    print("NO SEAT API")
    print("NO SHOWTIME API")
    print("NO EXISTING TRACKER MODIFICATION")

    print()
    print_line()
    print("LAUNCHING CHROMIUM")
    print_line()

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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        print()
        print_line()
        print("OPENING BMS CINEPOLIS MUMBAI PAGE")
        print_line()

        try:
            response = page.goto(
                BMS_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print("HTTP status:", response.status)
            else:
                print("No HTTP response object returned.")

        except Exception as e:
            print("Page opening error:", e)

        print()
        print("Waiting for BMS page...")
        time.sleep(5)

        # Give React/Next.js time to render
        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=20000,
            )
        except Exception:
            pass

        time.sleep(3)

        print()
        print_line()
        print("PAGE INFORMATION")
        print_line()

        try:
            print("Title:", page.title())
        except Exception:
            print("Title unavailable")

        try:
            print("Current URL:", page.url)
        except Exception:
            pass

        # Scroll to force lazy-loaded cinema content
        print()
        print_line()
        print("SCROLLING PAGE")
        print_line()

        for i in range(12):

            try:
                page.mouse.wheel(0, 1200)
            except Exception:
                pass

            time.sleep(0.8)

            print(f"Scroll {i + 1}/12")

        time.sleep(3)

        print()
        print_line()
        print("COLLECTING CINEPOLIS PROPERTIES")
        print_line()

        properties = extract_properties_from_page(page)

        print()
        print_line()
        print("DEDUPLICATING")
        print_line()

        properties = deduplicate_properties(properties)

        # Sort alphabetically
        properties.sort(
            key=lambda x: x.get("property_name", "").lower()
        )

        print()
        print_line()
        print("CINEPOLIS PROPERTIES FOUND")
        print_line()

        if not properties:
            print("NO CINEPOLIS PROPERTIES FOUND.")

        else:

            for i, item in enumerate(properties, start=1):

                print()
                print(f"{i}. {item['property_name']}")
                print(f"   BMS Code : {item['bms_code']}")
                print(f"   URL      : {item['url']}")

        output = {
            "source": BMS_URL,
            "city": "Mumbai",
            "chain": "Cinepolis",
            "property_count": len(properties),
            "properties": properties,
        }

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                output,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print()
        print_line()
        print("FINAL RESULT")
        print_line()

        print(
            f"TOTAL CINEPOLIS PROPERTIES FOUND: {len(properties)}"
        )

        print()
        print(f"Saved: {OUTPUT_FILE}")

        print()
        print_line()
        print("DISCOVERY COMPLETED")
        print_line()

        browser.close()


if __name__ == "__main__":
    main()
