import re
import json
import time
from datetime import datetime

from playwright.sync_api import sync_playwright


BMS_URL = "https://in.bookmyshow.com/cinemas-list/cinepolis/mumbai/cnpl"


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_cinepolis_properties(page):
    print("\n" + "=" * 90)
    print("BMS MUMBAI CINEPOLIS PROPERTY DISCOVERY")
    print("=" * 90)
    print(f"URL: {BMS_URL}")
    print("=" * 90)

    responses = []

    def on_response(response):
        url = response.url.lower()

        if "bookmyshow.com" in url:
            if any(x in url for x in [
                "cinema",
                "venue",
                "showtime",
                "api"
            ]):
                responses.append({
                    "status": response.status,
                    "type": response.request.resource_type,
                    "url": response.url
                })

    page.on("response", on_response)

    print("\nOpening BMS Cinepolis Mumbai page...")

    response = page.goto(
        BMS_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    if response:
        print("HTTP status:", response.status)
    else:
        print("No main response received.")

    print("Waiting for BMS page data...")
    time.sleep(8)

    # Scroll several times because BMS may lazy-load cinema entries.
    for i in range(8):
        page.mouse.wheel(0, 3000)
        time.sleep(1)

    html = page.content()

    print("\n" + "=" * 90)
    print("PAGE ANALYSIS")
    print("=" * 90)

    print("HTML size:", len(html))
    print("Page title:", page.title())

    properties = []

    # ------------------------------------------------------------------
    # Strategy 1:
    # Extract visible text around Cinepolis listings.
    # ------------------------------------------------------------------

    body_text = page.locator("body").inner_text(timeout=15000)

    lines = [
        clean_text(x)
        for x in body_text.splitlines()
        if clean_text(x)
    ]

    # Known BMS presentation:
    #
    # Cinepolis: Property Name
    # Address
    #
    # Capture a Cinepolis line and the following address line.
    for i, line in enumerate(lines):

        if "cinepolis:" not in line.lower():
            continue

        name = line

        address = ""

        if i + 1 < len(lines):
            possible_address = lines[i + 1]

            # Don't accidentally use another heading.
            if (
                "cinepolis" not in possible_address.lower()
                and "cinema in" not in possible_address.lower()
                and "home" not in possible_address.lower()
            ):
                address = possible_address

        properties.append({
            "name": name,
            "address": address
        })

    # ------------------------------------------------------------------
    # Strategy 2:
    # Search HTML text directly for Cinepolis names if DOM extraction
    # missed anything.
    # ------------------------------------------------------------------

    for match in re.finditer(
        r"Cinepolis\s*:\s*([^<\n]+)",
        html,
        flags=re.IGNORECASE
    ):
        name = clean_text(match.group(0))

        if name:
            properties.append({
                "name": name,
                "address": ""
            })

    # ------------------------------------------------------------------
    # Deduplicate
    # ------------------------------------------------------------------

    unique = {}

    for item in properties:
        key = clean_text(item["name"]).lower()

        if not key:
            continue

        if key not in unique:
            unique[key] = item
        else:
            if not unique[key]["address"] and item["address"]:
                unique[key]["address"] = item["address"]

    properties = list(unique.values())

    # ------------------------------------------------------------------
    # Print result
    # ------------------------------------------------------------------

    print("\n" + "=" * 90)
    print("CINEPOLIS PROPERTIES FOUND")
    print("=" * 90)

    if not properties:
        print("NO CINEPOLIS PROPERTIES FOUND.")
    else:
        for i, item in enumerate(properties, 1):
            print(f"\n{i}. {item['name']}")

            if item["address"]:
                print(f"   Address: {item['address']}")

    print("\n" + "=" * 90)
    print("TOTAL CINEPOLIS PROPERTIES:", len(properties))
    print("=" * 90)

    # ------------------------------------------------------------------
    # Save JSON
    # ------------------------------------------------------------------

    output = {
        "timestamp": datetime.now().isoformat(),
        "source": BMS_URL,
        "city": "Mumbai",
        "chain": "Cinepolis",
        "properties": properties,
        "captured_responses": responses
    }

    with open(
        "cinepolis_mumbai_properties.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\nSaved: cinepolis_mumbai_properties.json")

    return properties


def main():

    print("\n" + "=" * 90)
    print("BMS TOXIC PROJECT - CINEPOLIS PROPERTY DISCOVERY")
    print("=" * 90)

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
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
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()

        try:
            properties = extract_cinepolis_properties(page)

            print("\n" + "=" * 90)
            print("DISCOVERY COMPLETED")
            print("=" * 90)
            print("Properties found:", len(properties))

        finally:
            browser.close()


if __name__ == "__main__":
    main()
