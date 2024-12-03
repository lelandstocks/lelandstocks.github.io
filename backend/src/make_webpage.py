import json
import os
from collections import Counter
from datetime import datetime, timedelta
from glob import glob
from multiprocessing import cpu_count, get_context
import functools
import pickle
from concurrent.futures import ThreadPoolExecutor

import flask
import polars as pl  # Replace pandas with polars
from babel.numbers import format_currency
from flask import render_template
from scipy.stats import zscore
from zoneinfo import ZoneInfo
import yfinance as yf
from tqdm import tqdm

# this whole file is to render the html table
app = flask.Flask("leaderboard")

# Set multiprocessing to use 'spawn' for Polars compatibility
MULTIPROCESSING_CONTEXT = get_context("spawn")

# Add cache directory
CACHE_DIR = "./backend/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Add cache for rendered pages
RENDER_CACHE_DIR = "./backend/cache/rendered"
os.makedirs(RENDER_CACHE_DIR, exist_ok=True)


def cache_result(cache_key, expire_hours=1):
    """Decorator to cache function results"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_file = os.path.join(CACHE_DIR, f"{cache_key}.pickle")

            # Check if cache exists and is fresh
            if os.path.exists(cache_file):
                cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
                if datetime.now() - cache_time < timedelta(hours=expire_hours):
                    with open(cache_file, "rb") as f:
                        return pickle.load(f)

            # Execute function and cache result
            result = func(*args, **kwargs)
            with open(cache_file, "wb") as f:
                pickle.dump(result, f)
            return result

        return wrapper

    return decorator


def cache_rendered_page(page_name, content, expire_hours=1):
    """Cache rendered page content"""
    cache_file = os.path.join(RENDER_CACHE_DIR, f"{page_name}.html")
    with open(cache_file, "w") as f:
        f.write(content)


def get_cached_page(page_name, expire_hours=1):
    """Get cached page content if fresh"""
    cache_file = os.path.join(RENDER_CACHE_DIR, f"{page_name}.html")
    if os.path.exists(cache_file):
        cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.now() - cache_time < timedelta(hours=expire_hours):
            with open(cache_file, "r") as f:
                return f.read()
    return None


def render_parallel(template_name, **kwargs):
    """Render template with caching"""
    cache_key = f"{template_name}_{hash(str(kwargs))}"

    # Check cache first
    cached = get_cached_page(cache_key)
    if cached:
        return cached

    # Render if not cached
    with app.app_context():
        rendered = render_template(template_name, **kwargs)
        cache_rendered_page(cache_key, rendered)
        return rendered


@cache_result("price_data")
def fetch_price_data(start_date, end_date, symbols):
    """Fetch and cache price data for multiple symbols"""
    return yf.download(symbols, start=start_date, end=end_date, interval="15m")


@cache_result("trading_timestamps")
def generate_trading_timestamps(start_date, end_date):
    """Cache trading timestamps to avoid regeneration"""
    timestamps = []
    current = start_date.replace(hour=9, minute=30, second=0, microsecond=0)

    while current <= end_date:
        # Skip weekends
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            # Add timestamps for the trading day (9:30 AM - 4:00 PM EST)
            day_time = current
            while day_time.hour < 16 or (day_time.hour == 16 and day_time.minute == 0):
                timestamps.append(day_time)
                day_time += timedelta(minutes=5)

        # Move to next day
        current = (current + timedelta(days=1)).replace(
            hour=9, minute=30, second=0, microsecond=0
        )

    return timestamps


def get_five_number_summary(df):
    # Update summary statistics using polars
    money_series = df.get_column("Money In Account")
    average_money = money_series.mean()
    q1_money = money_series.quantile(0.25)
    median_money = money_series.quantile(0.5)
    q3_money = money_series.quantile(0.75)
    std_money = money_series.std()
    return average_money, q1_money, median_money, q3_money, std_money


def interpolate_value(timestamps, data_times, data_values, target_time):
    """Interpolate value for a given timestamp using surrounding data points"""
    if not data_times or not data_values:
        return None

    # Find the closest points before and after target_time
    before_idx = None
    after_idx = None

    for i, time in enumerate(data_times):
        if time <= target_time:
            before_idx = i
        if time >= target_time:
            after_idx = i
            break

    if before_idx is None or after_idx is None:
        return (
            data_values[before_idx]
            if before_idx is not None
            else data_values[after_idx]
        )

    if before_idx == after_idx:
        return data_values[before_idx]

    # Linear interpolation
    time_diff = (data_times[after_idx] - data_times[before_idx]).total_seconds()
    target_diff = (target_time - data_times[before_idx]).total_seconds()
    ratio = target_diff / time_diff

    return data_values[before_idx] + ratio * (
        data_values[after_idx] - data_values[before_idx]
    )


def get_previous_trading_day(date):
    """Get the previous trading day for a given date"""
    current = date
    while current.weekday() > 4:  # Saturday = 5, Sunday = 6
        current -= timedelta(days=1)
    return current


def get_leaderboard_data():
    """Centralized function to load and process leaderboard data"""
    leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))
    all_dfs = []
    timestamps = []

    for file in leaderboard_files:
        with open(file, "r") as f:
            dict_leaderboard = json.load(f)

        df = pl.DataFrame(
            [
                {
                    "Account Name": k,
                    "Money In Account": v[0],
                    "Investopedia Link": v[1],
                    "Stocks Invested In": v[2] if len(v) > 2 else [],
                }
                for k, v in dict_leaderboard.items()
            ]
        )

        df = df.sort("Money In Account", descending=True)
        if len(df.columns) == 3:
            df = df.with_columns(
                pl.Series(name="Stocks Invested In", values=[0 for i in range(len(df))])
            )
        df = df.with_columns(pl.Series(name="Ranking", values=range(1, len(df) + 1)))

        file_name = os.path.basename(file)
        date_time_str = file_name[len("leaderboard-") : -len(".json")]
        date_time = datetime.strptime(date_time_str.replace("_", ":"), "%Y-%m-%d-%H:%M")

        all_dfs.append(df)
        timestamps.append(date_time)

    return all_dfs, timestamps


@cache_result("analyzed_data")
def analyze_leaderboard_data():
    """Centralized analysis of leaderboard data that can be reused across functions"""
    all_dfs = []
    timestamps = []
    stock_cnt = []
    total_investment = 0

    try:
        all_dfs, timestamps = get_leaderboard_data()
        leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))

        # Load latest data
        with open("backend/leaderboards/leaderboard-latest.json", "r") as file:
            latest_data = json.load(file)

        # ...existing code...

        # Process latest DataFrame with error handling
        latest_df = (
            pl.DataFrame(
                [
                    {
                        "Account Name": k,
                        "Money In Account": v[0],
                        "Investopedia Link": v[1],
                        "Stocks Invested In": v[2] if len(v) > 2 else [],
                    }
                    for k, v in latest_data.items()
                ]
            )
            if latest_data
            else pl.DataFrame()
        )

        if not latest_df.is_empty():
            latest_df = latest_df.sort("Money In Account", descending=True)
            latest_df = latest_df.with_columns(
                pl.Series(name="Ranking", values=range(1, len(latest_df) + 1))
            )
            summary_stats = get_five_number_summary(latest_df)
        else:
            summary_stats = (0, 0, 0, 0, 0)  # Default values if no data

    except Exception as e:
        print(f"Error in analyze_leaderboard_data: {e}")
        latest_df = pl.DataFrame()
        summary_stats = (0, 0, 0, 0, 0)

    return {
        "all_dfs": all_dfs,
        "timestamps": timestamps,
        "leaderboard_files": leaderboard_files
        if "leaderboard_files" in locals()
        else [],
        "latest_df": latest_df,
        "stock_cnt": stock_cnt,
        "summary_stats": summary_stats,
        "total_investment": total_investment,
    }


def make_index_page():
    with app.app_context():
        # Get analyzed data
        data = analyze_leaderboard_data()
        df = data["latest_df"]
        stock_cnt = data["stock_cnt"]
        average_money, q1_money, median_money, q3_money, std_money = data[
            "summary_stats"
        ]

        all_dfs, timestamps = get_leaderboard_data()
        leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))

        # Load latest leaderboard first
        with open("backend/leaderboards/leaderboard-latest.json", "r") as file:
            latest_data = json.load(file)

        # Initialize all_stocks list
        all_stocks = []
        stock_values = {}
        total_investment = 0

        # Process all stocks from latest data
        for player_data in latest_data.values():
            try:
                stocks = player_data[2]  # Get stock holdings
                if stocks:  # Add stocks to all_stocks list
                    all_stocks.extend([stock[0] for stock in stocks])
                for stock in stocks:
                    symbol = stock[0]
                    current_price = float(stock[1].replace("$", "").replace(",", ""))
                    pct_change = (
                        float(stock[2].replace("%", "")) / 100
                    )  # Convert to decimal

                    # Guard against division by zero
                    if pct_change == -1:  # Edge case where percent change is -100%
                        initial_price = current_price  # Use current price as initial
                    else:
                        initial_price = current_price / (
                            1 + pct_change
                        )  # Calculate initial price

                    if symbol not in stock_values:
                        stock_values[symbol] = {"current": 0, "initial": 0}
                    stock_values[symbol]["current"] += current_price
                    stock_values[symbol]["initial"] += initial_price
                    total_investment += current_price

            except (IndexError, ValueError, TypeError):
                continue

        # Add initial and current values to stock_cnt data
        stock_data = []
        for symbol, values in stock_values.items():
            current_value = values["current"]
            initial_value = values["initial"]
            if initial_value > 0:
                percent_change = ((current_value / initial_value) - 1) * 100
                stock_data.append(
                    (symbol, current_value, initial_value, percent_change)
                )

        # Create stock_cnt with all required data
        stock_counter = Counter(all_stocks).most_common()
        stock_cnt = []
        for stock, count in stock_counter:
            stock_info = next((s for s in stock_data if s[0] == stock), None)
            if stock_info:
                stock_cnt.append(
                    (
                        stock,
                        count,
                        stock_info[1],  # Current value
                        stock_info[2],  # Initial value
                        stock_info[3],  # Percent change
                    )
                )
            else:
                stock_cnt.append((stock, count, 0, 0, 0))

        # Continue with existing code
        # First collect all raw timestamps and data
        raw_timestamps = []
        raw_data = {"min": [], "max": [], "q1": [], "median": [], "q3": [], "sp500": []}

        # Get initial S&P 500 price from August 20th, 2024 market close
        initial_date = datetime(2024, 8, 20, tzinfo=ZoneInfo("America/New_York"))
        initial_date = get_previous_trading_day(initial_date)
        sp500_initial = yf.download(
            "SPY",
            start=initial_date,
            end=initial_date + timedelta(days=1),
            interval="1h",  # Changed from 1d to 1h
        )
        initial_sp500_price = float(sp500_initial["Close"].iloc[0])

        # First pass to collect timestamps
        for file in leaderboard_files:
            file_name = os.path.basename(file)
            date_time_str = file_name[len("leaderboard-") : -len(".json")]
            date_time = datetime.strptime(
                date_time_str.replace("_", ":"), "%Y-%m-%d-%H:%M"
            ).replace(tzinfo=ZoneInfo("America/Los_Angeles"))  # Add timezone info
            raw_timestamps.append(date_time)

        if raw_timestamps:
            start_date = min(raw_timestamps)
            end_date = max(raw_timestamps)
            # Add timezone info to yfinance download
            sp500 = yf.download(
                "SPY",
                start=start_date.astimezone(
                    ZoneInfo("America/New_York")
                ),  # Convert to NY time for market hours
                end=end_date.astimezone(ZoneInfo("America/New_York")),
                interval="15m",  # Changed from 10m to 15m
            )
            # Convert SP500 index to Pacific time
            if not sp500.index.tzinfo:
                sp500.index = sp500.index.tz_localize(
                    "America/New_York"
                )  # Localize to NY time
            sp500.index = sp500.index.tz_convert("America/Los_Angeles")

        # Second pass to collect data
        for file, timestamp in zip(leaderboard_files, raw_timestamps):
            with open(file, "r") as f:
                dict_leaderboard = json.load(f)

            # Process leaderboard data
            df = pl.DataFrame(
                [
                    {
                        "Account Name": k,
                        "Money In Account": v[0],
                        "Investopedia Link": v[1],
                        "Stocks Invested In": v[2] if len(v) > 2 else [],
                    }
                    for k, v in dict_leaderboard.items()
                ]
            )
            df = df.sort("Money In Account", descending=True)
            if (
                len(df.columns) == 3
            ):  # IF the file has only 3 columns, then add a new column to the dataframe as a place holder
                df = df.with_columns(
                    pl.Series(
                        name="Stocks Invested In", values=[0 for i in range(len(df))]
                    )
                )
            _1, q1_money, median_money, q3_money, _2 = get_five_number_summary(
                df
            )  # get some key numbers for the charts
            raw_data["min"].append(int(df.get_column("Money In Account").min()))
            raw_data["max"].append(int(df.get_column("Money In Account").max()))
            raw_data["q1"].append(int(q1_money))
            raw_data["median"].append(int(median_money))
            raw_data["q3"].append(int(q3_money))

            # Get S&P 500 price for this timestamp
            try:
                # Find closest timestamp
                closest_idx = sp500.index.get_indexer([timestamp], method="nearest")[0]
                closest_time = sp500.index[closest_idx]
                current_sp500_price = float(sp500.loc[closest_time, "Close"].iloc[0])
                relative_return = current_sp500_price / initial_sp500_price
                sp500_price = 100000 * relative_return
            except (KeyError, IndexError):
                sp500_price = None
            raw_data["sp500"].append(sp500_price)

        # Generate complete set of 5-minute interval timestamps
        if raw_timestamps:
            start_date = min(raw_timestamps)
            end_date = max(raw_timestamps)
            complete_timestamps = generate_trading_timestamps(start_date, end_date)

            # Interpolate values for each timestamp
            labels = []
            min_monies = []
            max_monies = []
            q1_monies = []
            median_monies = []
            q3_monies = []
            sp500_prices = []

            for timestamp in complete_timestamps:
                labels.append(timestamp.strftime("%Y-%m-%dT%H:%M:%S"))

                # Interpolate each metric
                min_monies.append(
                    interpolate_value(
                        raw_timestamps, raw_timestamps, raw_data["min"], timestamp
                    )
                )
                max_monies.append(
                    interpolate_value(
                        raw_timestamps, raw_timestamps, raw_data["max"], timestamp
                    )
                )
                q1_monies.append(
                    interpolate_value(
                        raw_timestamps, raw_timestamps, raw_data["q1"], timestamp
                    )
                )
                median_monies.append(
                    interpolate_value(
                        raw_timestamps, raw_timestamps, raw_data["median"], timestamp
                    )
                )
                q3_monies.append(
                    interpolate_value(
                        raw_timestamps, raw_timestamps, raw_data["q3"], timestamp
                    )
                )
                sp500_prices.append(
                    interpolate_value(
                        raw_timestamps, raw_timestamps, raw_data["sp500"], timestamp
                    )
                )
        else:
            # If no data, initialize empty lists
            labels = []
            min_monies = []
            max_monies = []
            q1_monies = []
            median_monies = []
            q3_monies = []
            sp500_prices = []
        ### This whole section makes the Individual Statistics
        # Load json as dictionary, then organise it properly: https://stackoverflow.com/a/44607210
        with open("backend/leaderboards/leaderboard-latest.json", "r") as file:
            dict_leaderboard = json.load(file)
        df = pl.DataFrame(
            [
                {
                    "Account Name": k,
                    "Money In Account": v[0],
                    "Investopedia Link": v[1],
                    "Stocks Invested In": v[2] if len(v) > 2 else [],
                }
                for k, v in dict_leaderboard.items()
            ]
        )
        df = df.sort("Money In Account", descending=True)
        df = df.with_columns(pl.Series(name="Ranking", values=range(1, len(df) + 1)))

        # Keep only the stock_cnt with performance data from earlier
        df = df.with_columns(
            pl.col("Stocks Invested In").map_elements(
                lambda x: ", ".join([stock[0] for stock in x]), return_dtype=pl.Utf8
            )
        )

        df = df.with_columns(
            pl.Series(
                name="Z-Score",
                values=zscore(df.get_column("Money In Account").to_numpy()),
            )
        )
        df = df.with_columns(
            pl.struct(["Account Name"])
            .map_elements(
                lambda x: f'<a href="/players/{x["Account Name"]}.html" class="underline text-blue-600 hover:text-blue-800 visited:text-purple-600 {x["Account Name"]}" target="_blank">{x["Account Name"]}</a>',
                return_dtype=pl.Utf8,
            )
            .alias("Account Link")
        )

        # This gets the location of the the GOAT himself, Mr. Miller
        miller_location = df.filter(pl.col("Account Name") == "teachermiller")[
            "Ranking"
        ][0]

        # Drop the old Account Name and Investopedia Link columns
        df = df.drop(["Account Name", "Investopedia Link"])

        # Rearrange columns with Account Link
        df = df.select(
            [
                "Ranking",
                "Account Link",
                "Money In Account",
                "Stocks Invested In",
                "Z-Score",
            ]
        )

        # Update column_names
        column_names = [
            "Ranking",
            "Account Link",
            "Money In Account",
            "Stocks Invested In",
            "Z-Score",
        ]
        # This rearranges the columns to make things be in the right order
        average_money, q1_money, median_money, q3_money, std_money = (
            get_five_number_summary(df)
        )
        df = df.with_columns(
            pl.col("Money In Account").map_elements(
                lambda x: format_currency(x, currency="USD", locale="en_US"),
                return_dtype=pl.Utf8,
            )
        )

        # Modify this section to retrieve a single podcast audio file
        audio_directory = "./data/audio"
        podcast_file = None
        if os.path.exists(audio_directory):
            podcast_files = sorted(glob(os.path.join(audio_directory, "*.mp3")))
            if podcast_files:
                podcast_file = os.path.basename(
                    podcast_files[0]
                )  # Assuming only one file

        # Render the html template as shown here: https://stackoverflow.com/a/56296451
        rendered = render_parallel(
            "index.html",
            average_money="${:,.2f}".format(average_money),
            q1_money="${:,.2f}".format(q1_money),
            median_money="${:,.2f}".format(median_money),
            q3_money="${:,.2f}".format(q3_money),
            std_money="${:,.2f}".format(std_money),
            column_names=column_names,  # Updated column names
            row_data=df.to_numpy().tolist(),
            link_column="Account Link",  # Update link column
            update_time=datetime.utcnow()
            .astimezone(ZoneInfo("US/Pacific"))
            .strftime("%H:%M:%S %m-%d-%Y"),
            labels=labels,
            miller_location=miller_location,
            min_monies=min_monies,
            max_monies=max_monies,
            q1_monies=q1_monies,
            median_monies=median_monies,
            q3_monies=q3_monies,
            stock_cnt=stock_cnt,
            sp500_prices=sp500_prices,  # Add S&P 500 prices
            podcast_file=podcast_file,  # Pass single file
            zip=zip,
        )
        # print("all done with the index page")
        return rendered


@cache_result("player_data")
def process_all_player_data(all_dfs, latest_df):
    """Process all player data at once and cache results"""
    print("Processing player data...")
    player_data = {}

    players = latest_df.get_column("Account Name").to_list()
    with tqdm(total=len(players), desc="Processing players") as pbar:
        for player_name in players:
            player_money = []
            rankings = []

            # Extract data for this player from all timepoints
            for df in all_dfs:
                if player_name in df.get_column("Account Name").to_list():
                    player_row = df.filter(pl.col("Account Name") == player_name)
                    rankings.append(float(player_row.get_column("Ranking")[0]))
                    player_money.append(
                        float(player_row.get_column("Money In Account")[0])
                    )

            # Get player details from latest data
            player_row = latest_df.filter(pl.col("Account Name") == player_name)
            investopedia_link = player_row.get_column("Investopedia Link")[0]
            player_stocks_data = player_row.get_column("Stocks Invested In")[0]

            # Process stock data
            player_stocks = [
                [
                    stock[0],
                    float(stock[1].replace("$", "").replace(",", "")),
                    float(stock[2].replace("%", "")),
                ]
                for stock in player_stocks_data
            ]

            player_data[player_name] = {
                "money": player_money,
                "rankings": rankings,
                "investopedia_link": investopedia_link,
                "stocks": player_stocks,
            }
            pbar.update(1)

    return player_data


def process_single_user(args):
    """Modified to use pre-processed player data"""
    (
        player_name,
        labels,
        player_data,
        sp500_prices,
        tqqq_prices,
        nvda_prices,
        djt_prices,
    ) = args

    if player_name not in player_data:
        return None

    player_info = player_data[player_name]

    with app.app_context():
        rendered = render_template(
            "player.html",
            labels=labels,
            player_money=player_info["money"],
            player_name=player_name,
            investopedia_link=player_info["investopedia_link"],
            player_stocks=player_info["stocks"],
            update_time=datetime.utcnow()
            .astimezone(ZoneInfo("US/Pacific"))
            .strftime("%H:%M:%S %m-%d-%Y"),
            sp500_prices=sp500_prices,
            tqqq_prices=tqqq_prices,
            nvda_prices=nvda_prices,
            djt_prices=djt_prices,
            zip=zip,
        )

    return player_name, rendered


def make_user_pages(usernames):
    """Modified to use centralized player data processing"""
    with app.app_context():
        # Get analyzed data
        data = analyze_leaderboard_data()
        all_dfs = data["all_dfs"]
        timestamps = data["timestamps"]
        latest_df = data["latest_df"]

        if not timestamps:
            print("No data available")
            return

        # Process all player data once
        player_data = process_all_player_data(all_dfs, latest_df)

        # Price data processing remains the same
        print("Fetching price data...")
        start_date = min(timestamps).date()
        end_date = max(timestamps).date() + timedelta(days=1)
        initial_date = datetime(2024, 8, 20, tzinfo=ZoneInfo("America/New_York"))
        initial_date = get_previous_trading_day(initial_date)

        # Get initial prices
        initial_prices = yf.download(
            ["SPY", "TQQQ", "NVDA", "DJT"],
            start=initial_date,
            end=initial_date + timedelta(days=1),
            interval="1h",
        )
        initial_sp500_price = float(initial_prices["Close"]["SPY"].iloc[0])
        initial_tqqq_price = float(initial_prices["Close"]["TQQQ"].iloc[0])
        initial_nvda_price = float(initial_prices["Close"]["NVDA"].iloc[0])
        initial_djt_price = float(initial_prices["Close"]["DJT"].iloc[0])

        # Get price data for date range
        price_data = fetch_price_data(
            start_date, end_date, ["SPY", "TQQQ", "NVDA", "DJT"]
        )

        # Initialize price lists
        labels = []
        sp500_prices = []
        tqqq_prices = []
        nvda_prices = []
        djt_prices = []

        print("Processing timestamps...")
        with tqdm(total=len(timestamps), desc="Processing timestamps") as pbar:
            for timestamp in timestamps:
                date_time_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
                labels.append(date_time_str)

                # Calculate relative prices
                try:
                    current_sp500_price = float(
                        price_data["Close"]["SPY"].loc[timestamp]
                    )
                    current_tqqq_price = float(
                        price_data["Close"]["TQQQ"].loc[timestamp]
                    )
                    current_nvda_price = float(
                        price_data["Close"]["NVDA"].loc[timestamp]
                    )
                    current_djt_price = float(price_data["Close"]["DJT"].loc[timestamp])

                    sp500_prices.append(
                        100000 * (current_sp500_price / initial_sp500_price)
                    )
                    tqqq_prices.append(
                        100000 * (current_tqqq_price / initial_tqqq_price)
                    )
                    nvda_prices.append(
                        100000 * (current_nvda_price / initial_nvda_price)
                    )
                    djt_prices.append(100000 * (current_djt_price / initial_djt_price))
                except (KeyError, IndexError):
                    sp500_prices.append(None)
                    tqqq_prices.append(None)
                    nvda_prices.append(None)
                    djt_prices.append(None)

                pbar.update(1)

        latest_df = all_dfs[-1] if all_dfs else None
        if latest_df is None or latest_df.is_empty():  # Proper way to check DataFrame
            print("No data available in latest DataFrame")
            return

        # Process users with progress bar
        print("Processing parallel user pages...")
        process_args = [
            (
                name,
                labels,
                player_data,
                sp500_prices,
                tqqq_prices,
                nvda_prices,
                djt_prices,
            )
            for name in usernames
        ]

        num_processes = min(cpu_count(), len(usernames))
        with MULTIPROCESSING_CONTEXT.Pool(processes=num_processes) as pool:
            results = list(
                tqdm(
                    pool.imap(process_single_user, process_args),
                    total=len(usernames),
                    desc="Parallel processing",
                )
            )

        print("Writing results to files...")
        with tqdm(total=len(results), desc="Writing files") as pbar:
            for result in results:
                if result is not None:
                    player_name, rendered = result
                    with open(f"players/{player_name}.html", "w") as f:
                        f.write(rendered)
                pbar.update(1)


def make_combined_chart():
    """Generate a page showing all players' performance on one chart"""
    with app.app_context():
        # Get analyzed data
        data = analyze_leaderboard_data()
        leaderboard_files = data["leaderboard_files"]

        # Continue with chart generation
        print("Loading leaderboard files...")
        leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))
        labels = []
        all_data = {}

        print("Processing leaderboard data...")
        with tqdm(total=len(leaderboard_files), desc="Processing leaderboards") as pbar:
            for file in leaderboard_files:
                file_name = os.path.basename(file)
                date_time_str = file_name[len("leaderboard-") : -len(".json")]
                date_time = datetime.strptime(
                    date_time_str.replace("_", ":"), "%Y-%m-%d-%H:%M"
                )
                labels.append(date_time.strftime("%Y-%m-%dT%H:%M:%S"))

                with open(file, "r") as f:
                    dict_leaderboard = json.load(f)

                for player, data in dict_leaderboard.items():
                    if player not in all_data:
                        all_data[player] = []
                    money = float(str(data[0]).replace("$", "").replace(",", ""))
                    all_data[player].append(money)
                pbar.update(1)

        print("Creating datasets...")
        colors = [
            "#FF6384",
            "#36A2EB",
            "#FFCE56",
            "#4BC0C0",
            "#9966FF",
            "#FF9F40",
            "#00FF00",
            "#C9CBCF",
            "#4B0082",
            "#800000",
            "#FFB6C1",
            "#00CED1",
            "#FF4500",
            "#32CD32",
            "#BA55D3",
        ]

        datasets = []
        with tqdm(total=len(all_data), desc="Creating datasets") as pbar:
            for idx, (player, values) in enumerate(all_data.items()):
                color = colors[idx % len(colors)]
                datasets.append(
                    {
                        "label": player,
                        "data": values,
                        "borderColor": color,
                        "backgroundColor": color,
                        "fill": False,
                        "tension": 0.1,
                    }
                )
                pbar.update(1)

        return render_parallel("cometogether.html", labels=labels, datasets=datasets)


def make_about_page():
    """Generate the about page HTML"""
    return render_parallel("about.html")


def make_pages_parallel():
    """Generate all pages in parallel"""
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Start all page generations
        index_future = executor.submit(make_index_page)
        about_future = executor.submit(make_about_page)
        chart_future = executor.submit(make_combined_chart)

        # Get results and write if not None
        for future, filename in [
            (index_future, "index.html"),
            (about_future, "about.html"),
            (chart_future, "cometogether.html"),
        ]:
            content = future.result()
            if content:
                with open(filename, "w") as f:
                    f.write(content)


if __name__ == "__main__":
    with app.app_context():
        ### This whole section makes the chart shown at the top of the page!
        print(make_index_page())
        # Generate the combined chart page
        with open("cometogether.html", "w") as f:
            f.write(make_combined_chart())
