import os

from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

final_hrefs = []
for i in range(1, int(os.environ.get("INVESTOPEDIA_NUM_LEADERBOARDS")) + 1):
    # Replace "your_html_file.html" with the actual path to your file
    with open(
        f"./backend/profile-leaderboards/leaderboard{i}.html", "r"
    ) as f:  # Assuming
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # Find all anchor tags (<a>)
    links = soup.find_all("a")

    # Filter links with desired href structure
    desired_hrefs = []
    for link in links:
        href = link.get("href")
        if href and href.startswith(
            "https://www.investopedia.com/simulator/games/user-portfolio?portfolio="
        ):
            desired_hrefs.append(href)

    # Print the extracted hrefs
    print(desired_hrefs)

    # add to overall list of hrefs
    final_hrefs.extend(desired_hrefs)

# remove nonunique hrefs
final_hrefs = list(
    dict.fromkeys(final_hrefs)
)  # sort but maintain order: https://stackoverflow.com/a/7961390

with open("./backend/portfolios/portfolios.txt", "w") as output:
    output.write("\n".join(final_hrefs))
