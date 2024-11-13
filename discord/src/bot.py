import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import json
import pandas as pd
from pytz import timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up Discord bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Initialize bot instance with command prefix
bot = commands.Bot(command_prefix='$', intents=intents)

def get_user_info(df, username):
    """
    Retrieve and format information for a specific user from the DataFrame.
    """
    df["Money In Account"] = pd.to_numeric(df["Money In Account"], errors="coerce")
    user_row = df[df["Account Name"] == username]
    if user_row.empty:
        return None
    user_data = user_row.iloc[0]
    user_name = user_data["Account Name"]
    user_money = user_data["Money In Account"]
    user_stocks = user_data["Stocks Invested In"]
    formatted_holdings = "\n".join(
        [f"{stock[0]}: {stock[1]} ({stock[2]})" for stock in user_stocks]
    )
    return user_name, user_money, formatted_holdings

def get_latest_in_time_leaderboard():
    """
    Get the most recent leaderboard file from the in_time directory.
    """
    in_time_dir = "./backend/leaderboards/in_time"
    files = [f for f in os.listdir(in_time_dir) if f.endswith('.json')]
    if not files:
        return None
    latest_file = max(files, key=lambda x: os.path.getctime(os.path.join(in_time_dir, x)))
    return os.path.join(in_time_dir, latest_file)

async def compare_stock_changes(channel):
    """
    Compare current leaderboard with previous snapshot to detect stock changes, and send updates to the Discord channel as embeds.
    """
    try:
        # Load the latest snapshot from in_time directory
        latest_in_time = get_latest_in_time_leaderboard()
        if not latest_in_time:
            await channel.send("No historical data found")
            return

        # Load both leaderboards
        with open(latest_in_time, 'r') as f:
            previous_data = json.load(f)
        with open("./backend/leaderboards/leaderboard-latest.json", 'r') as f:
            current_data = json.load(f)

        any_changes = False
        # Compare holdings for each user
        for username in current_data:
            if username not in previous_data:
                continue

            # Get current and previous stock symbols
            current_stocks = set(stock[0] for stock in current_data[username][2])
            previous_stocks = set(stock[0] for stock in previous_data[username][2])

            # Find new and removed stocks
            new_stocks = current_stocks - previous_stocks
            removed_stocks = previous_stocks - current_stocks

            if new_stocks or removed_stocks:
                any_changes = True
                description = ""
                for stock in new_stocks:
                    description += f"+ Bought {stock}\n"
                for stock in removed_stocks:
                    description += f"- Sold {stock}\n"

                embed = discord.Embed(
                    colour=discord.Colour.green(),
                    title=f"Stock Changes for {username}",
                    description=description,
                    timestamp=discord.utils.utcnow()
                )
                await channel.send(embed=embed)

        if not any_changes:
            embed = discord.Embed(
                colour=discord.Colour.greyple(),
                title="No Stock Changes Detected",
                timestamp=discord.utils.utcnow()
            )
            await channel.send(embed=embed)

        # Update the snapshot with current data
        snapshot_path = "./backend/leaderboards/in_time/leaderboard-snapshot.json"
        with open(snapshot_path, 'w') as f:
            json.dump(current_data, f)

    except Exception as e:
        await channel.send(f"Error comparing stock changes: {str(e)}")
        import traceback
        traceback.print_exc()

# Load usernames from file
with open("./backend/portfolios/usernames.txt", "r") as f:
    usernames_list = [line.strip() for line in f.readlines()]

class UserInfo(commands.Cog):
    """
    Cog to handle user information related commands.
    """
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Get user information")
    @app_commands.describe(username="Select a username")
    async def userinfo(self, interaction: discord.Interaction, username: str):
        """
        Respond to the /userinfo command with the user's information.
        """
        await interaction.response.defer()
        try:
            with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
                data = json.load(file)
            df = pd.DataFrame.from_dict(data, orient="index")
            df.reset_index(inplace=True)
            df.columns = ["Account Name", "Money In Account", "Investopedia Link", "Stocks Invested In"]

            user_info = get_user_info(df, username)
            if user_info is None:
                await interaction.followup.send(f"User '{username}' not found.")
                return

            user_name, user_money, user_holdings = user_info
            embed = discord.Embed(
                colour=discord.Colour.blue(),
                title=f"Information for {user_name}",
                description=(
                    f"**Current Money:** {user_money}\n\n"
                    f"**Current Holdings:**\n{user_holdings}"
                ),
                timestamp=discord.utils.utcnow(),
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error fetching user info: {str(e)}")

    @userinfo.autocomplete("username")
    async def username_autocomplete(self, interaction: discord.Interaction, current: str):
        """
        Provide autocomplete suggestions for usernames based on current input.
        """
        return [
            app_commands.Choice(name=username, value=username)
            for username in usernames_list if current.lower() in username.lower()
        ][:25]

async def setup(bot):
    """
    Add the UserInfo cog to the bot.
    """
    await bot.add_cog(UserInfo(bot))

async def setup_hook():
    """
    Run setup when the bot is ready.
    """
    await setup(bot)

bot.setup_hook = setup_hook

@bot.tree.command(name="leaderboard", description="Get current leaderboard")
async def leaderboard(interaction: discord.Interaction):
    """
    Respond to the /leaderboard command with the top-ranked user's info.
    """
    await interaction.response.defer()
    try:
        with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
            data = json.load(file)
        df = pd.DataFrame.from_dict(data, orient="index")
        df.reset_index(inplace=True)
        df.columns = ["Account Name", "Money In Account", "Investopedia Link", "Stocks Invested In"]
        df.sort_values(by="Money In Account", ascending=False, inplace=True)

        top_ranked_name, top_ranked_money, top_ranked_stocks = get_user_info(df, df.iloc[0]["Account Name"])
        embed = discord.Embed(
            colour=discord.Colour.dark_red(),
            title="Current Leaderboard",
            description=(
                f"**Top Ranked Person:** {top_ranked_name}\n\n"
                f"**Current Money:** {top_ranked_money}\n\n"
                f"**Current Holdings:**\n{top_ranked_stocks}"
            ),
            timestamp=discord.utils.utcnow(),
        )
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Error fetching leaderboard: {str(e)}")

@tasks.loop(minutes=1)
async def send_leaderboard():
    """
    Periodically send the leaderboard update to the Discord channels during trading hours.
    """
    now = datetime.datetime.now(timezone("US/Eastern"))
    if now.weekday() < 5:
        start_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        end_time = now.replace(hour=16, minute=15, second=0, microsecond=0)
        if start_time <= now <= end_time:
            try:
                with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
                    data = json.load(file)
                df = pd.DataFrame.from_dict(data, orient="index")
                df.reset_index(inplace=True)
                df.columns = ["Account Name", "Money In Account", "Investopedia Link", "Stocks Invested In"]
                df.sort_values(by="Money In Account", ascending=False, inplace=True)

                top_ranked_name, top_ranked_money, top_ranked_stocks = get_user_info(df, df.iloc[0]["Account Name"])
                leaderboard_channel_id = int(os.environ.get("DISCORD_CHANNEL_ID_Leaderboard"))
                stocks_channel_id = int(os.environ.get("DISCORD_CHANNEL_ID_Stocks"))
                leaderboard_channel = bot.get_channel(leaderboard_channel_id)
                stocks_channel = bot.get_channel(stocks_channel_id)

                if leaderboard_channel:
                    embed = discord.Embed(
                        colour=discord.Colour.dark_red(),
                        title="Leaderboard Update!",
                        description=(
                            f"**Top Ranked Person:** {top_ranked_name}\n\n"
                            f"**Current Money:** {top_ranked_money}\n\n"
                            f"**Current Holdings:**\n{top_ranked_stocks}"
                        ),
                        timestamp=discord.utils.utcnow(),
                    )
                    await leaderboard_channel.send(embed=embed)

                if stocks_channel:
                    await compare_stock_changes(stocks_channel)

            except Exception as e:
                print(f"Error in send_leaderboard: {str(e)}")

@bot.event
async def on_ready():
    """
    Actions to perform when the bot is fully ready.
    """
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        send_leaderboard.start()
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# Run the bot with the provided token from environment variables
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
bot.run(DISCORD_BOT_TOKEN)
