import json
import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


BMS_URL = "https://in.bookmyshow.com/cinemas-list/cinepolis/mumbai/cnpl"
OUTPUT_FILE = "cinepolis_mumbai_properties.json"


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_cinema_code(url):
    if not url:
        return ""

    # Standard BMS cinema URL:
    # /cinemas/mumbai/cinepolis-xxxx/XXXX
    match = re.search(
        r"/cinemas/mumbai/[^/]+/([A-Za-z0-9]+)",
        url,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    # Fallback
    match = re.search(r"/([A-Z]{3,8})(?:/)?$", url)

    if match:
        return match.group(1).upper()

    return ""


def extract_slug_name(url):
    match = re.search(
        r"/cinemas/mumbai/([^/]+)",
        url,
        re.IGNORECASE,
    )

    if not match:
        return ""

    slug = match.group(1)

    return slug.replace("-", " ").strip().title()


def extract_properties(page):

    properties = {}

    links = page.locator("a")

    print()
    print("=" * 100)
    print("SCANNING ALL BMS LINKS")
    print("=" * 100)

    count = links.count()

    print("Total links:", count)

    for i in range(count):

        try:
            link = links.nth(i)

            href = link.get_attribute("href")

            if not href:
                continue

            full_url = urljoin(
                "https://in.bookmyshow.com",
                href
            )

            full_url = full_url.split("?")[0]

            # We specifically want BMS cinema/property URLs.
            if not re.search(
                r"/cinemas/mumbai/",
                full_url,
                re.IGNORECASE,
            ):
                continue

            # Must be Cinepolis property.
            if "cinepolis" not in full_url.lower():
                continue

            # Ignore chain listing page itself.
            if "/cinemas-list/" in full_url.lower():
                continue

            code = extract_cinema_code(full_url)

            if not code:
                continue

            text = clean_text(link.inner_text())

            slug_name = extract_slug_name(full_url)

            # Prefer visible text if it looks like a cinema name.
            name = text if text else slug_name

            # If visible text is generic, use URL slug.
            generic_names = {
                "book tickets",
                "view details",
                "view",
                "book now",
                "more",
            }

            if name.lower() in generic_names:
                name = slug_name

            key = code.upper()

            if key not in properties:

                properties[key] = {
                    "property_name": name,
                    "bms_code": code,
                    "url": full_url,
                }

                print()
                print("FOUND PROPERTY")
                print("Name :", name)
                print("Code :", code)
                print("URL  :", full_url)

        except Exception as e:
            print("Link processing error:", e)

    return list(properties.values())


def main():

    print()
    print("=" * 100)
    print("BMS TOXIC - MUMBAI CINEPOLIS PROPERTY DISCOVERY")
    print("=" * 100)

    print()
    print("Source:")
    print(BMS_URL)

    print()
    print("Purpose:")
    print("Discover ALL Cinepolis properties listed by BMS under Mumbai.")

    print()
    print("THIS VERSION DOES NOT:")
    print("- Access Google Sheets")
    print("- Read credentials.json")
    print("- Call the BMS showtime API")
    print("- Call the seat API")
    print("- Parse seat availability")
    print("- Modify your existing tracker logic")

    print()
    print("=" * 100)
    print("LAUNCHING CHROMIUM")
    print("=" * 100)

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
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
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        print()
        print("=" * 100)
        print("OPENING BMS CINEPOLIS MUMBAI PAGE")
        print("=" * 100)

        try:

            response = page.goto(
                BMS_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print("HTTP status:", response.status)

        except Exception as e:

            print("Initial page error:", e)

        print()
        print("Waiting for BMS page...")
        time.sleep(5)

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=20000,
            )
        except Exception:
            pass

        time.sleep(3)

        print()
        print("=" * 100)
        print("PAGE INFORMATION")
        print("=" * 100)

        try:
            print("Title:", page.title())
        except Exception:
            pass

        print("URL:", page.url)

        # Scroll gradually because BMS can lazy-load cinema cards.
        print()
        print("=" * 100)
        print("SCROLLING FOR LAZY-LOADED CINEMA DATA")
        print("=" * 100)

        for i in range(15):

            try:
                page.evaluate(
                    """
                    window.scrollTo(
                        0,
                        document.body.scrollHeight
                    );
                    """
                )
            except Exception:
                pass

            time.sleep(1)

            print(f"Scroll {i + 1}/15")

        # Return to top.
        try:
            page.evaluate(
                "window.scrollTo(0, 0);"
            )
        except Exception:
            pass

        time.sleep(2)

        print()
        print("=" * 100)
        print("EXTRACTING CINEPOLIS PROPERTIES")
        print("=" * 100)

        properties = extract_properties(page)

        # Sort by property name.
        properties.sort(
            key=lambda x: x["property_name"].lower()
        )

        print()
        print("=" * 100)
        print("FINAL CINEPOLIS PROPERTY LIST")
        print("=" * 100)

        if not properties:

            print()
            print("NO CINEPOLIS PROPERTIES FOUND.")

            # Save diagnostic page HTML as well.
            try:
                with open(
                    "bms_cinepolis_page.html",
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(page.content())

                print()
                print(
                    "Diagnostic HTML saved: "
                    "bms_cinepolis_page.html"
                )

            except Exception as e:
                print("Could not save diagnostic HTML:", e)

        else:

            for number, property_data in enumerate(
                properties,
                start=1,
            ):

                print()
                print(
                    f"{number}. "
                    f"{property_data['property_name']}"
                )

                print(
                    f"   BMS Code: "
                    f"{property_data['bms_code']}"
                )

                print(
                    f"   URL: "
                    f"{property_data['url']}"
                )

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
        print("=" * 100)
        print("DISCOVERY COMPLETED")
        print("=" * 100)

        print()
        print(
            "Cinepolis properties found:",
            len(properties),
        )

        print()
        print("Saved:", OUTPUT_FILE)

        browser.close()


if __name__ == "__main__":
    main()
