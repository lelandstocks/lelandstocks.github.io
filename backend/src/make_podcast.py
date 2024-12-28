from podcastfy.client import generate_podcast
import os
from dotenv import load_dotenv
import json
import glob
from datetime import datetime, timedelta
from fpdf import FPDF
from collections import defaultdict
import csv
import shutil

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

tech_debate_config = {
    "word_count": 10000,  # Longer content for in-depth discussions
    "conversation_style": ["analytical", "news channel", "insulting", "toxic"],
    "roles_person1": "Botswana's Biggest Fan",
    "roles_person2": "Bearish Stock Trader",
    "dialogue_structure": [
        "Stock Game Introduction",
        "Analysis of the Stock Game",
        "A look at the prior trends within the stock game",
        "Deepdive into a trader named Joshua Yan",
        "Future Traders to look out for",
    ],
    "podcast_name": "Quicksilver Podcast",
    "podcast_tagline": "Where Innovation Meets Mr. Miller's class",
    "output_language": "English",
    "engagement_techniques": [
        "statistics",
        "large changes in stock prices",
        "references to Botswana",
    ],
    "creativity": 0.3,  # Lower creativity for more factual content
}


def merge_json_to_pdf(json_directory, output_pdf):
    # Remove old videos and transcripts
    data_dir = "./data/"
    if os.path.exists(data_dir):
        for filename in os.listdir(data_dir):
            file_path = os.path.join(data_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}. Reason: {e}")

    one_week_ago = datetime.now() - timedelta(weeks=1)
    json_files = glob.glob(os.path.join(json_directory, "*.json"))
    recent_json_files = [
        file
        for file in json_files
        if datetime.fromtimestamp(os.path.getmtime(file)) >= one_week_ago
    ]

    # Ensure CSV directory exists
    csv_dir = "./backend/leaderboards/csvs/"
    os.makedirs(csv_dir, exist_ok=True)

    # Select earliest and latest JSON files per day
    files_by_date = defaultdict(list)
    for file in recent_json_files:
        file_date = datetime.fromtimestamp(os.path.getmtime(file)).date()
        files_by_date[file_date].append(file)

    selected_files = []
    for date, files in files_by_date.items():
        sorted_files = sorted(files, key=lambda x: os.path.getmtime(x))
        selected_files.append(sorted_files[-1])  # Latest

    # Convert each JSON file to its own CSV
    for file in selected_files:
        csv_filename = os.path.join(
            csv_dir, f"{os.path.basename(file).replace('.json', '.csv')}"
        )
        with open(file, "r") as f_json, open(csv_filename, "w", newline="") as f_csv:
            data = json.load(f_json)
            writer = csv.DictWriter(f_csv, fieldnames=["filename", "data"])
            writer.writeheader()
            writer.writerow(
                {"filename": os.path.basename(file), "data": json.dumps(data)}
            )

    # Convert selected JSON files to a single CSV
    csv_file = "./backend/leaderboards/weekly_summary.csv"
    with open(csv_file, "w", newline="") as csvfile:
        fieldnames = ["filename", "data"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for file in selected_files:
            with open(file, "r") as f:
                data = json.load(f)
            writer.writerow(
                {"filename": os.path.basename(file), "data": json.dumps(data)}
            )

    # Convert CSV to PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    with open(csv_file, "r") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            pdf.cell(200, 10, txt=row[0], ln=True, align="C")
            pdf.multi_cell(0, 10, txt=row[1])
            pdf.ln()

    pdf.output(output_pdf)


def generate_podcast_audio():
    # Convert JSON files to PDF
    merge_json_to_pdf(
        "./backend/leaderboards/in_time/", "./backend/leaderboards/weekly_summary.pdf"
    )

    # Generate podcast from PDF
    generate_podcast(
        urls=["./backend/leaderboards/weekly_summary.pdf"],
        conversation_config=tech_debate_config,
        llm_model_name="gpt-4o",
        api_key_label="OPENAI_API_KEY",
    )
    # Optionally, handle the generated audio_file if needed


if __name__ == "__main__":
    generate_podcast_audio()
