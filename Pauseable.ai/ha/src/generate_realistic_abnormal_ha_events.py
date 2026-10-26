from datetime import datetime, timedelta
from pathlib import Path
import csv

out = Path("data/raw/abnormal_events_realistic.csv")
out.parent.mkdir(parents=True, exist_ok=True)

events = []

def add(t, device, signal, action):
    events.append([
        t.strftime("%Y-%m-%d %H:%M:%S"),
        device,
        signal,
        action,
    ])

base = datetime(2026, 9, 1, 7, 0, 0)


for day in range(2):
    d = base + timedelta(days=day)

    for hour in [7, 12, 18]:
        t = d.replace(hour=hour, minute=10)
        add(t, "fridge", "door", "open")
        add(t + timedelta(minutes=1), "fridge", "door", "close")

    add(d.replace(hour=9, minute=0), "washer", "operation", "running")
    add(d.replace(hour=10, minute=5), "washer", "operation", "done")
    add(d.replace(hour=10, minute=10), "washer", "operation", "idle")

    add(d.replace(hour=11, minute=0), "dryer", "operation", "running")
    add(d.replace(hour=12, minute=0), "dryer", "operation", "done")
    add(d.replace(hour=12, minute=5), "dryer", "operation", "idle")

    add(d.replace(hour=14, minute=0), "air_purifier", "mode", "auto")
    add(d.replace(hour=22, minute=0), "air_purifier", "mode", "sleep")


t0 = datetime(2026, 9, 1, 22, 10, 0)
for m in [0, 2, 4, 6, 9]:
    add(t0 + timedelta(minutes=m), "fridge", "door", "open")
    add(t0 + timedelta(minutes=m, seconds=40), "fridge", "door", "close")


t1 = datetime(2026, 9, 2, 2, 16, 0)
modes = ["auto", "sleep", "strong", "auto", "sleep", "strong"]
for i, mode in enumerate(modes):
    add(t1 + timedelta(minutes=i * 4), "air_purifier", "mode", mode)


add(datetime(2026, 9, 2, 21, 30, 0), "washer", "operation", "running")
add(datetime(2026, 9, 2, 22, 20, 0), "washer", "operation", "done")
add(datetime(2026, 9, 2, 22, 30, 0), "washer", "operation", "running")
add(datetime(2026, 9, 2, 23, 20, 0), "washer", "operation", "done")
add(datetime(2026, 9, 2, 23, 35, 0), "washer", "operation", "running")

events.sort(key=lambda row: row[0])

with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["event_time", "device_type", "signal_type", "action"])
    writer.writerows(events)

print(f"saved: {out}")
print(f"rows: {len(events)}")
