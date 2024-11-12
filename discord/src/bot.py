import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import json
import pandas as pd
from pytz import timezone
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='$', intents=intents)

def get_user_info(df, username):
    # Ensure the "Money In Account" column is numeric
    df["Money In Account"] = pd.to_numeric(df["Money In Account"], errors="coerce")
    # Find the user in the DataFrame
    user_row = df[df["Account Name"] == username]
    if user_row.empty:
        return None
    user_data = user_row.iloc[0]
    user_name = user_data["Account Name"]
    user_money = user_data["Money In Account"]
    user_stocks = user_data["Stocks Invested In"]
    # Format holdings
    formatted_holdings = "\n".join(
        [f"{stock[0]}: {stock[1]} ({stock[2]})" for stock in user_stocks]
    )
    return user_name, user_money, formatted_holdings

# Load usernames from usernames.txt
with open("./backend/portfolios/usernames.txt", "r") as f:
    usernames_list = [line.strip() for line in f.readlines()]

class UserInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Get user information")
    @app_commands.describe(username="Select a username")
    async def userinfo(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer()
        try:
            with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
                data = json.load(file)
            df = pd.DataFrame.from_dict(data, orient="index")
            df.reset_index(inplace=True)
            df.columns = [
                "Account Name",
                "Money In Account",
                "Investopedia Link",
                "Stocks Invested In",
            ]
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
        return [
            app_commands.Choice(name=username, value=username)
            for username in usernames_list if current.lower() in username.lower()
        ][:25]

async def setup(bot):
    await bot.add_cog(UserInfo(bot))

# Fix setup_hook implementation
async def setup_hook():
    await setup(bot)

bot.setup_hook = setup_hook

@bot.tree.command(name="leaderboard", description="Get current leaderboard")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
            data = json.load(file)
        df = pd.DataFrame.from_dict(data, orient="index")
        df.reset_index(inplace=True)
        df.columns = [
            "Account Name",
            "Money In Account",
            "Investopedia Link",
            "Stocks Invested In",
        ]
        # Sort the DataFrame by "Money In Account" in descending order
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

# Convert send_leaderboard to a task
@tasks.loop(minutes=1)
async def send_leaderboard():
    now = datetime.datetime.now(timezone("US/Eastern"))
    if now.weekday() < 5:  # Monday-Friday are 0-4
        start_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        end_time = now.replace(hour=16, minute=15, second=0, microsecond=0)
        if start_time <= now <= end_time:
            try:
                with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
                    data = json.load(file)
                df = pd.DataFrame.from_dict(data, orient="index")
                df.reset_index(inplace=True)
                df.columns = [
                    "Account Name", 
                    "Money In Account",
                    "Investopedia Link",
                    "Stocks Invested In"
                ]
                # Sort the DataFrame by "Money In Account" in descending order
                df.sort_values(by="Money In Account", ascending=False, inplace=True)
                top_ranked_name, top_ranked_money, top_ranked_stocks = get_user_info(df, df.iloc[0]["Account Name"])
                channel_id = int(os.environ.get("DISCORD_CHANNEL_ID"))
                channel = bot.get_channel(channel_id)
                if channel:
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
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error in send_leaderboard: {str(e)}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        # Start the task after sync
        send_leaderboard.start()
    except Exception as e:
        print(f"Failed to sync commands: {e}")

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
bot.run(DISCORD_BOT_TOKEN)