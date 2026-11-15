
import csv
import os
from datetime import datetime, timezone

filename = "history.csv"

file_exists = os.path.exists(filename)

with open(filename, "a", newline="") as file:
    writer = csv.writer(file)

    if not file_exists:
        writer.writerow(["Timestamp", "Message"])

    timestamp = datetime.now(timezone.utc).isoformat()

    writer.writerow([timestamp, "Hello World!"])

print("Hello World!")
print("CSV updated successfully!")
