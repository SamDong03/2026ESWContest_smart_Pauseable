import csv
from datetime import datetime, timedelta

INPUT_PATH = "data/raw/sample_ha_events.csv"

def parse_time(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

events = []

with open(INPUT_PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        events.append({
            "time": parse_time(row["event_time"]),
            "device": row["device_type"],
            "signal": row["signal_type"],
            "action": row["action"],
        })

if not events:
    raise SystemExit("No events found")

now = max(e["time"] for e in events)

def count_events(device, signal, action, minutes):
    start = now - timedelta(minutes=minutes)
    return sum(
        1 for e in events
        if e["time"] >= start
        and e["device"] == device
        and e["signal"] == signal
        and e["action"] == action
    )

features = {
    "fridge_door_open_count_10m": count_events("fridge", "door", "open", 10),
    "fridge_door_toggle_count_10m": (
        count_events("fridge", "door", "open", 10)
        + count_events("fridge", "door", "close", 10)
    ),
    "washer_status_change_count_30m": count_events("washer", "status", "change", 30),
    "washer_operation_change_count_30m": count_events("washer", "operation", "change", 30),
}

level = "normal"
reasons = []

if features["fridge_door_open_count_10m"] >= 8:
    level = "risk"
    reasons.append("fridge door opened many times in 10 minutes")
elif features["fridge_door_open_count_10m"] >= 5:
    level = "attention"
    reasons.append("fridge door opened more than usual")

if features["fridge_door_toggle_count_10m"] >= 14:
    level = "risk"
    reasons.append("fridge door toggled repeatedly")

print("HA CSV anomaly test")
print("-------------------")
print(f"current_window_end: {now}")

for name, value in features.items():
    print(f"{name}: {value}")

print("-------------------")
print(f"level: {level}")

for reason in reasons:
    print(f"reason: {reason}")
