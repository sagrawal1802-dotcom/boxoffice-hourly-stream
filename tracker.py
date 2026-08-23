import json
import re
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


BMS_CINEMAS_URL = "https://in.bookmyshow.com/cinemas/mumbai"

OUTPUT_FILE = "cinepolis_mumbai_properties.json"


def banner(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_code(url):
    if not url:
        return None

    match = re.search(r"/([A-Z]{2,10})/?$", url)

    if match:
        return match.group(1)

    return None


def is_cinepolis_name(name):
    return "cinepolis" in normalise(name).lower()


def main():

    banner("BMS MUMBAI THEATRE LIST - CINEPOLIS DISCOVERY")

    print("Source:")
    print(BMS_CINEMAS_URL)

    print("\nPurpose:")
    print("Open the complete Mumbai theatre listing and filter venue names containing Cinepolis.")

    print("\nTHIS VERSION DOES NOT:")
    print("- Access Google Sheets")
    print("- Read credentials.json")
    print("- Call the BMS showtime API")
    print("- Call the seat API")
    print("- Modify your existing tracker")

    results = []

    with sync_playwright() as p:

        banner("LAUNCHING CHROMIUM")

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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
        )

        page = context.new_page()

        banner("OPENING MUMBAI THEATRE LIST")

        try:
            response = page.goto(
                BMS_CINEMAS_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print("HTTP status:", response.status())
            else:
                print("No initial response object.")

        except Exception as e:
            print("Page open error:", e)

        time.sleep(5)

        print("Page title:", normalise(page.title()))
        print("Current URL:", page.url)

        banner("LOADING COMPLETE THEATRE LIST")

        previous_height = 0
        stable_count = 0

        for i in range(30):

            try:
                current_height = page.evaluate(
                    "document.documentElement.scrollHeight"
                )

                page.evaluate(
                    "window.scrollTo(0, document.documentElement.scrollHeight)"
                )

                time.sleep(1.5)

                new_height = page.evaluate(
                    "document.documentElement.scrollHeight"
                )

                print(
                    f"Scroll {i + 1}/30 | "
                    f"Height: {current_height} -> {new_height}"
                )

                if new_height == previous_height:
                    stable_count += 1
                else:
                    stable_count = 0

                previous_height = new_height

                if stable_count >= 4:
                    print("Page height stable. Stopping scroll.")
                    break

            except Exception as e:
                print("Scroll error:", e)
                break

        # Scroll back to top once
        try:
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(2)
        except Exception:
            pass

        banner("EXTRACTING ALL THEATRE LINKS")

        links = page.locator("a")

        total_links = links.count()

        print("Total links found:", total_links)

        all_venues = []

        seen_urls = set()

        for i in range(total_links):

            try:
                element = links.nth(i)

                href = element.get_attribute("href")
                text = normalise(element.inner_text())

                if not href:
                    continue

                if not text:
                    continue

                full_url = urljoin(BMS_CINEMAS_URL, href)

                # We are interested in BMS cinema/theatre URLs.
                if "/cinemas/" not in full_url.lower():
                    continue

                if full_url in seen_urls:
                    continue

                seen_urls.add(full_url)

                code = extract_code(full_url)

                venue = {
                    "name": text,
                    "code": code,
                    "url": full_url,
                }

                all_venues.append(venue)

            except Exception:
                continue

        banner("ALL BMS THEATRE LINKS")

        print("Cinema links extracted:", len(all_venues))

        # Print every venue so we can diagnose the structure.
        for venue in all_venues:

            print(
                f"{venue['name']} | "
                f"{venue['code']} | "
                f"{venue['url']}"
            )

        banner("FILTERING VENUE NAME = CINEPOLIS")

        for venue in all_venues:

            if not is_cinepolis_name(venue["name"]):
                continue

            print("\nFOUND CINEPOLIS PROPERTY")

            print("Name :", venue["name"])
            print("Code :", venue["code"])
            print("URL  :", venue["url"])

            results.append(venue)

        # Also perform a second check against the complete HTML.
        # This helps if BMS renders some theatre information outside
        # normal <a> elements.

        banner("SECONDARY CINEPOLIS TEXT CHECK")

        try:

            body_text = normalise(page.locator("body").inner_text())

            cinepolis_lines = []

            for line in body_text.split("\n"):

                line = normalise(line)

                if "cinepolis" in line.lower():
                    cinepolis_lines.append(line)

            print(
                "Visible Cinepolis text matches:",
                len(cinepolis_lines)
            )

            for line in cinepolis_lines:
                print("TEXT:", line)

        except Exception as e:
            print("Secondary text scan error:", e)

        # Remove duplicate results.
        unique = {}

        for item in results:

            key = (
                item.get("code")
                or item.get("url")
                or item.get("name")
            )

            unique[key] = item

        results = list(unique.values())

        results.sort(
            key=lambda x: x.get("name", "").lower()
        )

        banner("FINAL CINEPOLIS PROPERTY LIST")

        if not results:

            print("NO CINEPOLIS PROPERTIES FOUND.")

        else:

            for index, venue in enumerate(results, 1):

                print(
                    f"\n{index}. {venue['name']}"
                )

                print(
                    f"   BMS Code: {venue['code']}"
                )

                print(
                    f"   URL: {venue['url']}"
                )

        output = {
            "source": BMS_CINEMAS_URL,
            "city": "mumbai",
            "chain": "Cinepolis",
            "total_bms_cinema_links": len(all_venues),
            "total_cinepolis_properties": len(results),
            "properties": results,
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

        banner("DISCOVERY COMPLETED")

        print(
            "Total BMS cinema links:",
            len(all_venues)
        )

        print(
            "Cinepolis properties:",
            len(results)
        )

        print(
            "Saved:",
            OUTPUT_FILE
        )

        browser.close()


if __name__ == "__main__":
    main()
