import json

# Read usernames from txt file
with open("./backend/portfolios/usernames.txt", "r") as f:
    usernames = set(line.strip() for line in f.readlines())

# Read leaderboard data
with open("./backend/leaderboards/leaderboard-latest.json", "r") as f:
    leaderboard = json.load(f)

# Get set of usernames from leaderboard
leaderboard_usernames = set(leaderboard.keys())

# Find missing usernames (in txt but not in leaderboard)
missing_usernames = usernames - leaderboard_usernames

if missing_usernames:
    print("Missing usernames in leaderboard:")
    for username in sorted(missing_usernames):
        print(username)
else:
    print("No missing usernames found!")
