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


def get_response_status(response):
    try:
        status = response.status
        if callable(status):
            return status()
        return status
    except Exception:
        return "unknown"


def extract_code(url):
    if not url:
        return None

    # BMS cinema URLs normally end with the cinema code.
    match = re.search(r"/([A-Z0-9]{2,12})/?$", url)

    if match:
        return match.group(1)

    return None


def main():

    banner("BMS MUMBAI THEATRE LIST - CINEPOLIS DISCOVERY")

    print("Source:")
    print(BMS_CINEMAS_URL)

    print("\nPurpose:")
    print("Open the Mumbai theatre listing and discover all Cinepolis properties.")

    print("\nTHIS VERSION DOES NOT:")
    print("- Access Google Sheets")
    print("- Read credentials.json")
    print("- Call the BMS showtime API")
    print("- Call the seat API")
    print("- Modify your existing tracker")

    results = []
    all_venues = []

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
            viewport={
                "width": 1440,
                "height": 1000
            },
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
                wait_until="commit",
                timeout=60000,
            )

            if response:
                print(
                    "Initial HTTP status:",
                    get_response_status(response)
                )

        except Exception as e:
            print("Page navigation warning:", repr(e))

        # Give BMS React/Next.js time to initialise.
        print("Waiting for BMS page JavaScript...")
        time.sleep(8)

        print("Page title:", normalise(page.title()))
        print("Current URL:", page.url)

        banner("WAITING FOR THEATRE DATA")

        # Wait for the document to become reasonably populated.
        for i in range(10):

            try:

                body_length = page.locator("body").inner_text(
                    timeout=3000
                )

                print(
                    f"Data wait {i + 1}/10 | "
                    f"Visible text: {len(body_length)}"
                )

                if len(body_length) > 2000:
                    break

            except Exception as e:
                print(
                    f"Data wait {i + 1}/10 failed:",
                    repr(e)
                )

            time.sleep(2)

        banner("SCROLLING MUMBAI THEATRE LIST")

        # Slowly scroll through the entire page.
        # BMS frequently lazy-loads theatre information.
        last_height = 0
        stable = 0

        for i in range(40):

            try:

                height = page.evaluate(
                    "document.documentElement.scrollHeight"
                )

                page.evaluate(
                    """
                    window.scrollTo({
                        top: document.documentElement.scrollHeight,
                        behavior: 'instant'
                    });
                    """
                )

                time.sleep(2)

                new_height = page.evaluate(
                    "document.documentElement.scrollHeight"
                )

                print(
                    f"Scroll {i + 1}/40 | "
                    f"Height {height} -> {new_height}"
                )

                if new_height == last_height:
                    stable += 1
                else:
                    stable = 0

                last_height = new_height

                # Four consecutive unchanged heights means
                # there is probably no more lazy-loaded content.
                if stable >= 4:
                    print(
                        "Page height stable. "
                        "Continuing to extraction."
                    )
                    break

            except Exception as e:

                print(
                    "Scroll error:",
                    repr(e)
                )

                break

        # Scroll back up.
        try:
            page.evaluate(
                "window.scrollTo(0, 0)"
            )
            time.sleep(2)
        except Exception:
            pass

        banner("PAGE INFORMATION")

        try:

            print(
                "Final page title:",
                normalise(page.title())
            )

            print(
                "Final URL:",
                page.url
            )

            print(
                "HTML size:",
                len(page.content())
            )

        except Exception as e:
            print(
                "Page information error:",
                repr(e)
            )

        banner("EXTRACTING THEATRE INFORMATION")

        # ---------------------------------------------------------
        # METHOD 1
        # Extract every anchor whose URL contains /cinemas/
        # ---------------------------------------------------------

        try:

            links = page.locator(
                "a[href*='/cinemas/']"
            )

            link_count = links.count()

            print(
                "Cinema links detected:",
                link_count
            )

            seen = set()

            for i in range(link_count):

                try:

                    element = links.nth(i)

                    href = element.get_attribute("href")

                    if not href:
                        continue

                    full_url = urljoin(
                        BMS_CINEMAS_URL,
                        href
                    )

                    if full_url in seen:
                        continue

                    seen.add(full_url)

                    # Get text from the complete element.
                    text = normalise(
                        element.inner_text()
                    )

                    # Sometimes the clickable element contains
                    # nested elements and inner_text is empty.
                    if not text:

                        try:

                            text = normalise(
                                element.text_content()
                            )

                        except Exception:
                            pass

                    if not text:
                        continue

                    code = extract_code(full_url)

                    venue = {
                        "name": text,
                        "code": code,
                        "url": full_url
                    }

                    all_venues.append(venue)

                except Exception:
                    continue

        except Exception as e:

            print(
                "Anchor extraction error:",
                repr(e)
            )

        # ---------------------------------------------------------
        # METHOD 2
        # Inspect all links manually as fallback.
        # ---------------------------------------------------------

        if len(all_venues) < 5:

            banner("FALLBACK LINK SCAN")

            try:

                all_links = page.locator("a")

                count = all_links.count()

                print(
                    "Total page links:",
                    count
                )

                existing_urls = {
                    x["url"]
                    for x in all_venues
                }

                for i in range(count):

                    try:

                        element = all_links.nth(i)

                        href = element.get_attribute("href")

                        if not href:
                            continue

                        full_url = urljoin(
                            BMS_CINEMAS_URL,
                            href
                        )

                        if "/cinemas/" not in full_url.lower():
                            continue

                        if full_url in existing_urls:
                            continue

                        text = normalise(
                            element.inner_text()
                        )

                        if not text:
                            text = normalise(
                                element.text_content()
                            )

                        if not text:
                            continue

                        existing_urls.add(full_url)

                        all_venues.append(
                            {
                                "name": text,
                                "code": extract_code(full_url),
                                "url": full_url
                            }
                        )

                    except Exception:
                        continue

            except Exception as e:

                print(
                    "Fallback scan error:",
                    repr(e)
                )

        # ---------------------------------------------------------
        # Remove duplicates
        # ---------------------------------------------------------

        unique = {}

        for venue in all_venues:

            key = (
                venue.get("url")
                or venue.get("code")
                or venue.get("name")
            )

            if key not in unique:
                unique[key] = venue

        all_venues = list(unique.values())

        banner("BMS THEATRE PROPERTIES EXTRACTED")

        print(
            "Unique cinema properties:",
            len(all_venues)
        )

        for venue in all_venues:

            print(
                f"{venue['name']} | "
                f"{venue['code']} | "
                f"{venue['url']}"
            )

        # ---------------------------------------------------------
        # CINEPOLIS FILTER
        # ---------------------------------------------------------

        banner("FILTERING VENUE NAME FOR CINEPOLIS")

        for venue in all_venues:

            name = normalise(
                venue.get("name")
            )

            if "cinepolis" in name.lower():

                print("\nFOUND CINEPOLIS")

                print(
                    "Name:",
                    name
                )

                print(
                    "Code:",
                    venue.get("code")
                )

                print(
                    "URL:",
                    venue.get("url")
                )

                results.append(
                    {
                        "name": name,
                        "code": venue.get("code"),
                        "url": venue.get("url")
                    }
                )

        # ---------------------------------------------------------
        # SECONDARY FULL HTML SEARCH
        # ---------------------------------------------------------

        banner("SECONDARY HTML SEARCH")

        try:

            html = page.content()

            print(
                "HTML size:",
                len(html)
            )

            cine_matches = re.findall(
                r".{0,150}cinepolis.{0,250}",
                html,
                flags=re.IGNORECASE
            )

            print(
                "Cinepolis HTML matches:",
                len(cine_matches)
            )

            for match in cine_matches[:20]:

                print(
                    normalise(
                        re.sub(
                            r"<[^>]+>",
                            " ",
                            match
                        )
                    )
                )

        except Exception as e:

            print(
                "HTML search error:",
                repr(e)
            )

        # ---------------------------------------------------------
        # Final deduplication
        # ---------------------------------------------------------

        unique_results = {}

        for venue in results:

            key = (
                venue.get("code")
                or venue.get("url")
                or venue.get("name")
            )

            unique_results[key] = venue

        results = list(
            unique_results.values()
        )

        results.sort(
            key=lambda x:
            x.get("name", "").lower()
        )

        # ---------------------------------------------------------
        # SAVE
        # ---------------------------------------------------------

        output = {
            "source": BMS_CINEMAS_URL,
            "city": "mumbai",
            "chain": "Cinepolis",
            "total_bms_cinema_properties": len(all_venues),
            "total_cinepolis_properties": len(results),
            "properties": results
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

        banner("FINAL CINEPOLIS PROPERTY LIST")

        if results:

            for i, venue in enumerate(
                results,
                1
            ):

                print(
                    f"\n{i}. {venue['name']}"
                )

                print(
                    f"   BMS Code: {venue['code']}"
                )

                print(
                    f"   URL: {venue['url']}"
                )

        else:

            print(
                "NO CINEPOLIS PROPERTIES FOUND."
            )

        banner("DISCOVERY COMPLETED")

        print(
            "Total BMS cinema properties:",
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
