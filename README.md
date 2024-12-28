# 📈 Leland High School Stock Trading Leaderboard

Welcome to the **Leland High School Stock Trading Leaderboard**! This tool provides near real-time updates to your trading leaderboard, offering faster updates compared to traditional platforms like Investopedia.

## 🚀 Features

- **Real-Time Leaderboard**: Updates are processed quickly, so you're always viewing the latest rankings.
- **Discord Integration**: Automatically post updates to your selected Discord channel.

## 📋 Prerequisites

1. **Discord Bot**: Create a Discord application and bot.
2. **Browser Access**: You’ll need to download leaderboard HTML pages manually (future updates may automate this).
3. **Dependencies**: Ensure your environment meets the necessary requirements to run the bot.

## 🛠️ Setup and Usage

### 1. Download the Leaderboard HTML

Using your browser, download the full leaderboard pages as HTML files. For 128 players, this should be approximately **3 pages** with 50 entries each. You only need to perform this step **once**.

### 2. Configure Your Environment

1. **.env File**: Fill in the provided `.env.example` file with your login credentials and the number of leaderboard pages. Rename it to `.env` when done.
2. **Discord Bot Setup**:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
   - Navigate to the "Bot" section, create a bot, and copy the **Bot Token** into your `.env` file.

3. **Get the Discord Channel ID**:
   - Right-click on the channel where you want the bot to post updates and select **Copy ID**. Paste this into the `.env` file.

### 3. Add Your Bot to a Server

1. In the Discord Developer Portal, go to the **OAuth2** tab and copy your **Client ID**.
2. Replace `<CLIENT_ID_HERE>` in the URL below, then visit the link to invite the bot to your server:

   ```plaintext
   https://discordapp.com/api/oauth2/authorize?client_id=<CLIENT_ID_HERE>&permissions=8&scope=bot
   ```

### 4. Run the Bot

Run the bot using:

```bash
pixi run all
```

## 📌 Notes

- **Future Updates**: We hope to automate the leaderboard download step soon.
- **Support**: If you encounter any issues, feel free to contribute or raise an issue.

---

Happy trading, and enjoy the fast updates!
