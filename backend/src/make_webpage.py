import json
import os
from datetime import datetime, timedelta
from glob import glob
from multiprocessing import cpu_count, get_context

import flask
import polars as pl  # Replace pandas with polars
from babel.numbers import format_currency
from flask import render_template
from scipy.stats import zscore
from zoneinfo import ZoneInfo
import yfinance as yf

# this whole file is to render the html table
app = flask.Flask("leaderboard")

# Set multiprocessing to use 'spawn' for Polars compatibility
MULTIPROCESSING_CONTEXT = get_context("spawn")


def get_five_number_summary(df):
    # Update summary statistics using polars
    money_series = df.get_column("Money In Account")
    average_money = money_series.mean()
    q1_money = money_series.quantile(0.25)
    median_money = money_series.quantile(0.5)
    q3_money = money_series.quantile(0.75)
    std_money = money_series.std()
    return average_money, q1_money, median_money, q3_money, std_money


def generate_trading_timestamps(start_date, end_date):
    """Generate 5-minute interval timestamps during trading hours (9:30 AM - 4:00 PM EST)"""
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


def make_index_page():
    with app.app_context():
        leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))

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
        stock_values = {}  # Track value and performance for each stock
        total_investment = 0

        for stocks in df.get_column("Stocks Invested In"):
            if isinstance(stocks, str):
                continue
            for stock in stocks:
                symbol = stock[0]
                current_price = float(stock[1].replace("$", "").replace(",", ""))
                pct_change = float(stock[2].replace("%", "")) / 100

                # Calculate initial price based on percent change
                initial_price = (
                    current_price
                    if pct_change == -1
                    else current_price / (1 + pct_change)
                )

                if symbol not in stock_values:
                    stock_values[symbol] = {"count": 0, "current": 0, "initial": 0}

                stock_values[symbol]["count"] += 1
                stock_values[symbol]["current"] += current_price
                stock_values[symbol]["initial"] += initial_price
                total_investment += current_price

        # Convert to format expected by template
        stock_cnt = [
            (
                symbol,
                data["count"],
                data["current"],
                data["initial"],
                ((data["current"] / data["initial"]) - 1) * 100
                if data["initial"] > 0
                else 0,
            )
            for symbol, data in stock_values.items()
        ]
        stock_cnt.sort(key=lambda x: x[1], reverse=True)  # Sort by count
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
        rendered = render_template(
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


def process_single_user(args):
    """Helper function to process a single user's page"""
    (
        player_name,
        labels,
        all_dfs,
        sp500_prices,
        tqqq_prices,
        nvda_prices,
        djt_prices,
        latest_df,
    ) = args

    if player_name not in latest_df.get_column("Account Name").to_list():
        return None

    player_money = []
    rankings = []

    # Extract data for this player from all timepoints
    for df in all_dfs:
        if player_name in df.get_column("Account Name").to_list():
            player_row = df.filter(pl.col("Account Name") == player_name)
            rankings.append(float(player_row.get_column("Ranking")[0]))
            player_money.append(float(player_row.get_column("Money In Account")[0]))

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

    with app.app_context():
        rendered = render_template(
            "player.html",
            labels=labels,
            player_money=player_money,
            player_name=player_name,
            investopedia_link=investopedia_link,
            player_stocks=player_stocks,
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
    """Generate HTML pages for multiple users in parallel"""
    with app.app_context():
        leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))
        labels = []
        all_dfs = []
        timestamps = []
        sp500_prices = []
        tqqq_prices = []
        nvda_prices = []
        djt_prices = []

        # Get initial prices from August 20th, 2024 market close
        initial_date = datetime(2024, 8, 20, tzinfo=ZoneInfo("America/New_York"))
        initial_date = get_previous_trading_day(initial_date)
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

        # Collect timestamps and process files
        for file in leaderboard_files:
            file_name = os.path.basename(file)
            date_time_str = file_name[len("leaderboard-") : -len(".json")]
            date_time = datetime.strptime(
                date_time_str.replace("_", ":"), "%Y-%m-%d-%H:%M"
            )
            timestamps.append(date_time)

        # Fetch price data
        start_date = min(timestamps).date()
        end_date = max(timestamps).date() + timedelta(days=1)
        price_data = yf.download(
            ["SPY", "TQQQ", "NVDA", "DJT"],
            start=start_date,
            end=end_date,
            interval="15m",
        )

        # Process each timestamp
        for file, timestamp in zip(leaderboard_files, timestamps):
            date_time_str = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
            labels.append(date_time_str)

            # Get prices
            date_for_price = timestamp.date()
            try:
                current_sp500_price = float(
                    price_data["Close"]["SPY"].loc[date_for_price]
                )
                current_tqqq_price = float(
                    price_data["Close"]["TQQQ"].loc[date_for_price]
                )
                current_nvda_price = float(
                    price_data["Close"]["NVDA"].loc[date_for_price]
                )
                current_djt_price = float(
                    price_data["Close"]["DJT"].loc[date_for_price]
                )

                sp500_price = 100000 * (current_sp500_price / initial_sp500_price)
                tqqq_price = 100000 * (current_tqqq_price / initial_tqqq_price)
                nvda_price = 100000 * (current_nvda_price / initial_nvda_price)
                djt_price = 100000 * (current_djt_price / initial_djt_price)
            except KeyError:
                previous_dates = price_data.index[
                    price_data.index.date <= date_for_price
                ]
                if len(previous_dates) > 0:
                    current_sp500_price = float(
                        price_data["Close"]["SPY"].loc[previous_dates[-1]]
                    )
                    current_tqqq_price = float(
                        price_data["Close"]["TQQQ"].loc[previous_dates[-1]]
                    )
                    current_nvda_price = float(
                        price_data["Close"]["NVDA"].loc[previous_dates[-1]]
                    )
                    current_djt_price = float(
                        price_data["Close"]["DJT"].loc[previous_dates[-1]]
                    )

                    sp500_price = 100000 * (current_sp500_price / initial_sp500_price)
                    tqqq_price = 100000 * (current_tqqq_price / initial_tqqq_price)
                    nvda_price = 100000 * (current_nvda_price / initial_nvda_price)
                    djt_price = 100000 * (current_djt_price / initial_djt_price)
                else:
                    sp500_price = tqqq_price = nvda_price = djt_price = None

            sp500_prices.append(sp500_price)
            tqqq_prices.append(tqqq_price)
            nvda_prices.append(nvda_price)
            djt_prices.append(djt_price)

            # Process leaderboard data
            with open(file, "r") as f:
                dict_leaderboard = json.load(f)
            # ...existing DataFrame processing code...
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
                    pl.Series(
                        name="Stocks Invested In", values=[0 for i in range(len(df))]
                    )
                )
            df = df.with_columns(
                pl.Series(name="Ranking", values=range(1, len(df) + 1))
            )
            all_dfs.append(df)

        # Get latest df for stock information
        latest_df = all_dfs[-1]

        # Process each user using the pre-processed data
        for player_name in usernames:
            player_money = []
            rankings = []

            # Check if player exists in latest data
            if player_name not in latest_df.get_column("Account Name").to_list():
                continue

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

            # Render template
            rendered = render_template(
                "player.html",
                labels=labels,
                player_money=player_money,
                player_name=player_name,
                investopedia_link=investopedia_link,
                player_stocks=player_stocks,
                update_time=datetime.utcnow()
                .astimezone(ZoneInfo("US/Pacific"))
                .strftime("%H:%M:%S %m-%d-%Y"),
                sp500_prices=sp500_prices,
                tqqq_prices=tqqq_prices,
                nvda_prices=nvda_prices,
                djt_prices=djt_prices,
                zip=zip,
            )

            with open(f"players/{player_name}.html", "w") as f:
                f.write(rendered)

        # Prepare arguments for parallel processing
        latest_df = all_dfs[-1]
        process_args = [
            (
                name,
                labels,
                all_dfs,
                sp500_prices,
                tqqq_prices,
                nvda_prices,
                djt_prices,
                latest_df,
            )
            for name in usernames
        ]

        # Process users in parallel using spawn context
        num_processes = min(
            cpu_count(), len(usernames)
        )  # Don't create more processes than users
        with MULTIPROCESSING_CONTEXT.Pool(processes=num_processes) as pool:
            results = pool.map(process_single_user, process_args)

        # Write results to files
        for result in results:
            if result is not None:
                player_name, rendered = result
                with open(f"players/{player_name}.html", "w") as f:
                    f.write(rendered)


def make_combined_chart():
    """Generate a page showing all players' performance on one chart"""
    with app.app_context():
        leaderboard_files = sorted(glob("./backend/leaderboards/in_time/*"))
        labels = []
        all_data = {}

        # Process each leaderboard file
        for file in leaderboard_files:
            file_name = os.path.basename(file)
            date_time_str = file_name[len("leaderboard-") : -len(".json")]
            date_time = datetime.strptime(
                date_time_str.replace("_", ":"), "%Y-%m-%d-%H:%M"
            )
            labels.append(date_time.strftime("%Y-%m-%dT%H:%M:%S"))

            # Load and process the leaderboard data
            with open(file, "r") as f:
                dict_leaderboard = json.load(f)

            for player, data in dict_leaderboard.items():
                if player not in all_data:
                    all_data[player] = []
                # Fix: data is a list where the first element is the account value
                money = float(str(data[0]).replace("$", "").replace(",", ""))
                all_data[player].append(money)

        # Create datasets for Chart.js
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

        # Render template
        rendered = render_template(
            "cometogether.html", labels=labels, datasets=datasets
        )
        return rendered


def make_about_page():
    """Generate the about page HTML"""
    with app.app_context():
        rendered = render_template("about.html")
        return rendered


if __name__ == "__main__":
    with app.app_context():
        ### This whole section makes the chart shown at the top of the page!
        print(make_index_page())
        # Generate the combined chart page
        with open("cometogether.html", "w") as f:
            f.write(make_combined_chart())
