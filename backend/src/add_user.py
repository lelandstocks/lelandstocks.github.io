import json
from glob import glob


def add_user(username, portfolio_url):
    """Add a new user to the system."""

    # Add portfolio URL to portfolios.txt
    with open("./backend/portfolios/portfolios.txt", "a") as f:
        f.write(f"{portfolio_url}\n")

    # Add username to usernames.txt
    with open("./backend/portfolios/usernames.txt", "a") as f:
        f.write(f"{username}\n")

    # Update latest leaderboard with initial data
    leaderboard_path = "./backend/leaderboards/leaderboard-latest.json"
    with open(leaderboard_path, "r") as f:
        leaderboard = json.load(f)

    # Add new user with initial values
    leaderboard[username] = [
        100000.00,  # Initial account value
        portfolio_url,  # Portfolio URL
        [],  # Empty stock holdings
    ]

    # Write updated leaderboard
    with open(leaderboard_path, "w") as f:
        json.dump(leaderboard, f)

    # Update all leaderboard files in 'in_time' folder
    leaderboard_files = glob("./backend/leaderboards/in_time/*.json")
    for lb_file in leaderboard_files:
        with open(lb_file, "r") as f:
            lb_data = json.load(f)

        # If user does not exist, add them with initial values
        if username not in lb_data:
            lb_data[username] = [
                100000.00,  # Initial account value
                portfolio_url,  # Portfolio URL
                [],  # Empty stock holdings
            ]
            # Write updated leaderboard
            with open(lb_file, "w") as f:
                json.dump(lb_data, f)


if __name__ == "__main__":
    # Add the all_in_tqqq user
    add_user(
        "all_in_tqqq",
        "https://www.investopedia.com/simulator/games/user-portfolio?portfolio=10701005",
    )
