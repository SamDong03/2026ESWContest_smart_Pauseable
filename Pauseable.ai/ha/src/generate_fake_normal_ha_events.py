import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

OUTPUT_PATH = Path("data/raw/fake_normal_ha_events.csv")
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

random.seed(42)

start = datetime(2026, 8, 1, 0, 0, 0)
days = 7

events = []

for d in range(days):
    day = start + timedelta(days=d)

    for hour in [7, 12, 18, 22]:
        count = random.randint(0, 3)
        for i in range(count):
            t = day + timedelta(hours=hour, minutes=random.randint(0, 50))
            events.append([t, "fridge", "door", "open"])
            events.append([t + timedelta(seconds=20), "fridge", "door", "close"])

    if random.random() < 0.5:
        t = day + timedelta(hours=random.choice([9, 14, 20]), minutes=random.randint(0, 30))
        events.append([t, "washer", "status", "change"])
        events.append([t + timedelta(minutes=1), "washer", "operation", "change"])

    if random.random() < 0.4:
        t = day + timedelta(hours=random.choice([10, 15, 21]), minutes=random.randint(0, 30))
        events.append([t, "dryer", "status", "change"])
        events.append([t + timedelta(minutes=1), "dryer", "operation", "change"])

    if random.random() < 0.6:
        t = day + timedelta(hours=random.choice([8, 19]), minutes=random.randint(0, 30))
        events.append([t, "air_purifier", "power", "power_on"])
        events.append([t + timedelta(minutes=10), "air_purifier", "mode", "change"])

events.sort(key=lambda x: x[0])

with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["event_time", "device_type", "signal_type", "action"])
    for t, device, signal, action in events:
        writer.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), device, signal, action])

print(f"saved: {OUTPUT_PATH}")
print(f"events: {len(events)}")
