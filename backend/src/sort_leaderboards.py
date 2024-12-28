import os
import shutil
from datetime import datetime
import pytz


def get_time_from_filename(filename):
    # Extract the date and time from the filename, assume format: leaderboard-YYYY-mm-dd-HH_MM.json
    try:
        base_name = os.path.basename(filename)
        date_time = datetime.strptime(base_name, "leaderboard-%Y-%m-%d-%H_%M.json")
        return date_time
    except (IndexError, ValueError) as e:
        print(f"Error parsing filename {filename}: {e}")
        return None


def sort_files_in_directory(directory, destination_in_time, destination_out_of_time):
    for filename in os.listdir(directory):
        if filename.endswith(".json"):
            full_path = os.path.join(directory, filename)
            file_time = get_time_from_filename(full_path)
            if file_time:
                # Convert to New York timezone
                tz_NY = pytz.timezone("America/New_York")
                file_time = tz_NY.localize(file_time)

                # Check if the file date is a weekday
                if file_time.weekday() < 5:  # 0 = Monday, 4 = Friday
                    if (
                        file_time.hour > 9
                        or (file_time.hour == 9 and file_time.minute >= 30)
                    ) and file_time.hour < 16:
                        destination = destination_in_time
                    else:
                        destination = destination_out_of_time
                    print(file_time, file_time.weekday)
                else:
                    destination = destination_out_of_time

                # Move the file to the appropriate directory
                shutil.move(full_path, os.path.join(destination, filename))
                print(f"Moved {filename} to {destination}")


# Directories for sorting
in_time_dir = "./backend/leaderboards/in_time"
out_of_time_dir = "./backend/leaderboards/out_of_time"

# Sort files in the base directory, properly this time
sort_files_in_directory("./backend/leaderboards/", in_time_dir, out_of_time_dir)
