import json
import os
from datetime import datetime
import pickle
import random
import asyncio
from playwright.async_api import async_playwright
import time

import pytz
from dotenv import load_dotenv
from make_webpage import (
    make_index_page,
    make_user_pages,
    make_about_page,
    make_combined_chart,
)
from make_podcast import generate_podcast_audio

load_dotenv()

# Add list of user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
]


def get_random_user_agent():
    return random.choice(USER_AGENTS)


# --- functions ---  # PEP8: `lower_case_names`
async def save_cookies(context, path):
    cookies = await context.cookies()
    with open(path, "wb") as file:
        pickle.dump(cookies, file)


async def load_cookies(context, path):
    with open(path, "rb") as file:
        cookies = pickle.load(file)
        await context.add_cookies(cookies)
    return True


async def login(page):
    INVESTOPEDIA_EMAIL = os.environ.get("INVESTOPEDIA_EMAIL")
    INVESTOPEDIA_PASSWORD = os.environ.get("INVESTOPEDIA_PASSWORD")
    COOKIE_PATH = "./backend/cookies.pkl"

    # First try to use cookies
    await page.goto("https://www.investopedia.com/simulator", wait_until="networkidle")
    if await load_cookies(page.context, COOKIE_PATH):
        await page.goto(
            "https://www.investopedia.com/simulator/home.aspx", wait_until="networkidle"
        )
        # Check if we're logged in
        login_button = await page.query_selector("#login")
        if not login_button:
            return

    # If cookies didn't work, do regular login
    await page.goto(
        "https://www.investopedia.com/simulator/home.aspx", wait_until="networkidle"
    )

    await page.fill("#username", INVESTOPEDIA_EMAIL)
    await page.fill("#password", INVESTOPEDIA_PASSWORD)
    await page.click("#login")
    await page.wait_for_load_state("networkidle")

    # Save cookies after successful login
    await save_cookies(page.context, COOKIE_PATH)


# Add after imports
SCREENSHOT_DIR = "./backend/screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


async def process_single_account(context, url):
    """Process a single account and return its information"""
    page = await context.new_page()

    try:
        # First attempt
        await login(page)
        await page.goto(url, wait_until="domcontentloaded")
        print(page.url)
        account_name = ""
        try:
            # Wait for account value and name to be present
            await page.wait_for_selector(
                '[data-cy="account-value-text"]', timeout=300000
            )
            await page.wait_for_selector(
                '[data-cy="user-portfolio-name"]', timeout=300000
            )

            account_value = await page.text_content('[data-cy="account-value-text"]')
            account_value = float(account_value.replace("$", "").replace(",", ""))
            account_name = await page.text_content('[data-cy="user-portfolio-name"]')
            account_name = account_name.replace(" Portfolio", "").strip()
        except Exception as e:
            print("First attempt failed, trying again with fresh login...")
            await context.clear_cookies()
            await login(page)
            await page.goto(url, wait_until="domcontentloaded")

            # Wait for account value and name to be present on second attempt
            await page.wait_for_selector(
                '[data-cy="account-value-text"]', timeout=300000
            )
            await page.wait_for_selector(
                '[data-cy="user-portfolio-name"]', timeout=300000
            )

            account_value = await page.text_content('[data-cy="account-value-text"]')
            account_value = float(account_value.replace("$", "").replace(",", ""))
            account_name = await page.text_content('[data-cy="user-portfolio-name"]')
            account_name = account_name.replace(" Portfolio", "").strip()
            with open("logs/log.txt", "a") as file:
                file.write(
                    f" {datetime.now()} First attempt failed, trying again with fresh login, specific error was {e}\n"
                )
        # Wait for table to be fully loaded
        await page.wait_for_selector(
            "table tr td", timeout=300000
        )  # Wait for at least one table cell
        await page.wait_for_function(
            """
            () => {
                const rows = document.querySelectorAll('table tr');
                return rows.length > 1 && rows[1].querySelectorAll('td').length > 0;
            }
        """,
            timeout=300000,
        )

        # Get stock data from table
        stock_data = []
        rows = await page.query_selector_all("table tr")

        print(f"\nProcessing account: {account_name}")
        print("Table rows found:", len(rows))

        if len(rows) > 1:  # Skip header row
            for i, row in enumerate(rows[1:], 1):
                try:
                    # # Print entire row content for debugging
                    # all_cells = await row.query_selector_all("td")
                    # raw_row_data = []
                    # for cell in all_cells:
                    #     content = await cell.text_content()
                    #     raw_row_data.append(content.strip())
                    # print(f"Row {i} raw data:", raw_row_data)

                    symbol = await row.query_selector("td:nth-child(1)")
                    total_amount_of_money = await row.query_selector("td:nth-child(7)")
                    gain_pct = await row.query_selector("td:nth-child(8)")
                    # print(await symbol.text_content(), await last_price.text_content(), await gain_pct.text_content())
                    if symbol and total_amount_of_money and gain_pct:
                        symbol_text = (await symbol.text_content()).strip()
                        price_text = (
                            await total_amount_of_money.text_content()
                        ).strip()
                        gain_text = (await gain_pct.text_content()).strip()
                        # Clean up gain percentage text
                        gain_text = gain_text.replace("\n", "").replace(" ", "")
                        gain_parts = gain_text.split("(")
                        if len(gain_parts) > 1:
                            gain_text = gain_parts[1].replace(")", "")
                        if symbol_text and price_text and gain_text:
                            stock_data.append([symbol_text, price_text, gain_text])
                            print(
                                f"Processed stock for {account_name}: {symbol_text}____{price_text}____ {gain_text}"
                            )
                except Exception as e:
                    print(f"Error parsing row: {e}")
                    continue

        # if not stock_data:
        #     # Take a screenshot if no stocks are discovered
        #     timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        #     screenshot_path = os.path.join(
        #         SCREENSHOT_DIR, f"no_stocks_{timestamp}_{url.split('/')[-1]}.png"
        #     )
        #     await page.screenshot(path=screenshot_path, full_page=True)
        #     stock_data = []

        return account_name.strip(), [
            account_value,
            url.strip(),
            stock_data,
        ]  # Added strip()
    except Exception as e:
        print(f"Error processing account {url}: {str(e)}")
        with open("logs/log.txt", "a") as file:
            file.write(f"Error processing account {url}: {str(e)}, {datetime.now()}\n")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        screenshot_path = os.path.join(
            SCREENSHOT_DIR, f"error_{timestamp}_{url.split('/')[-1]}.png"
        )
        await page.screenshot(path=screenshot_path, full_page=True)
        return "retry"
    finally:
        await page.close()  # Close tab instead of browser


async def get_account_information():
    """Returns a dictionary with all of the account values within it"""
    account_information = {}
    urls = []

    with open("./backend/portfolios/portfolios.txt", "r") as file:
        urls = [line.strip() for line in file]

    # Create semaphore to limit concurrent tabs
    semaphore = asyncio.Semaphore(8)  # Reduced from 16 since we're using tabs

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=get_random_user_agent())

        async def process_with_semaphore(url):
            async with semaphore:
                res = await process_single_account(context, url)
                while res == "retry":
                    print("Retrying...", url)
                    res = await process_single_account(context, url)
                return res

        try:
            tasks = [process_with_semaphore(url) for url in urls]
            results = await asyncio.gather(*tasks)

            for result in results:
                if result:
                    account_name, account_data = result
                    account_information[account_name] = account_data
        finally:
            await browser.close()

    return account_information


# Main execution block
async def main():
    tz_NY = pytz.timezone("America/New_York")
    curr_time = datetime.now(tz_NY)

    if curr_time.weekday() < 5:
        is_trading_hours = (
            curr_time.hour > 9 or (curr_time.hour == 9 and curr_time.minute >= 30)
        ) and curr_time.hour < 16

        if (
            is_trading_hours or os.environ.get("FORCE_UPDATE") == "True"
        ) and os.environ.get("DONT_UPDATE") != "True":
            account_values = await get_account_information()

            file_name = f"./backend/leaderboards/out_of_time/leaderboard-{curr_time.strftime('%Y-%m-%d-%H_%M')}.json"
            if is_trading_hours:
                file_name = f"./backend/leaderboards/in_time/leaderboard-{curr_time.strftime('%Y-%m-%d-%H_%M')}.json"

            with open("./backend/leaderboards/leaderboard-latest.json", "w") as file:
                json.dump(account_values, file)

            with open(file_name, "w") as file:
                json.dump(account_values, file)

            # Add 2 minute delay if outside trading hours
            if not is_trading_hours:
                time.sleep(120)  # 2 minutes in seconds
        else:
            print("Update disabled")

        # Update index.html
        with open("index.html", "w") as file:
            file.write(make_index_page())

        # Update about.html
        with open("about.html", "w") as file:
            file.write(make_about_page())

        # Generate combined chart page
        with open("cometogether.html", "w") as file:
            file.write(make_combined_chart())

        # Read usernames and generate all pages at once
        with open("./backend/portfolios/usernames.txt", "r") as file:
            usernames = [user.strip() for user in file.readlines()]
            make_user_pages(usernames)
    elif os.environ.get("MAKE_WEBPAGE") == "True":
        # Update index.html
        with open("index.html", "w") as file:
            file.write(make_index_page())

        # Update about.html
        with open("about.html", "w") as file:
            file.write(make_about_page())

        # Read usernames and generate all pages at once
        with open("./backend/portfolios/usernames.txt", "r") as file:
            usernames = [user.strip() for user in file.readlines()]
            make_user_pages(usernames)

    # Generate podcast after leaderboard update only at end of trading day ±15 minutes
    end_of_day = curr_time.replace(hour=13, minute=0, second=0, microsecond=0)
    time_diff = abs((curr_time - end_of_day).total_seconds())
    if time_diff <= 15 * 60 or os.environ.get("FORCE_PODCAST") == "True":
        # Check last podcast generation time
        last_podcast_file = "last_podcast_update.txt"
        if os.path.exists(last_podcast_file):
            with open(last_podcast_file, "r") as f:
                last_update_str = f.read().strip()
                last_update = datetime.strptime(last_update_str, "%Y-%m-%d").date()
            if (
                last_update < curr_time.date()
                or os.environ.get("FORCE_PODCAST") == "True"
            ):
                generate_podcast_audio()
                with open(last_podcast_file, "w") as f:
                    f.write(curr_time.strftime("%Y-%m-%d"))
        else:
            generate_podcast_audio()
            with open(last_podcast_file, "w") as f:
                f.write(curr_time.strftime("%Y-%m-%d"))


if __name__ == "__main__":
    asyncio.run(main())
