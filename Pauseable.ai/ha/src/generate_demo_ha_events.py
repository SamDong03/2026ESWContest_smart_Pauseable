import csv
import random
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"


def add_toggle(events, when, device_type, signal_type, open_action, close_action, hold_seconds):
    events.append([when, device_type, signal_type, open_action])
    events.append([when + timedelta(seconds=hold_seconds), device_type, signal_type, close_action])


def add_state(events, when, device_type, signal_type, action):
    events.append([when, device_type, signal_type, action])


def add_fridge_routine(events, day, rng):
    meal_blocks = [
        (7, 10, rng.randint(1, 3)),
        (12, 5, rng.randint(1, 2)),
        (18, 20, rng.randint(2, 4)),
    ]

    if rng.random() < 0.25:
        meal_blocks.append((21, rng.randint(0, 20), 1))

    for hour, minute, count in meal_blocks:
        base = day.replace(hour=hour, minute=minute, second=0)
        for idx in range(count):
            when = base + timedelta(minutes=idx * rng.randint(3, 8), seconds=rng.randint(0, 40))
            hold = rng.randint(15, 75)
            add_toggle(events, when, "fridge", "door", "open", "close", hold)


def add_laundry_routine(events, day, rng):
    if rng.random() >= 0.28:
        return

    start = day.replace(hour=rng.choice([9, 10, 14, 19]), minute=rng.randint(0, 20), second=0)
    add_state(events, start, "washer", "operation", "running")
    add_state(events, start + timedelta(minutes=rng.randint(45, 75)), "washer", "operation", "done")
    add_state(events, start + timedelta(minutes=rng.randint(80, 110)), "washer", "operation", "idle")

    if rng.random() < 0.65:
        dryer_start = start + timedelta(minutes=rng.randint(90, 130))
        add_state(events, dryer_start, "dryer", "operation", "running")
        add_state(events, dryer_start + timedelta(minutes=rng.randint(50, 80)), "dryer", "operation", "done")
        add_state(events, dryer_start + timedelta(minutes=rng.randint(85, 115)), "dryer", "operation", "idle")


def add_air_purifier_routine(events, day, rng):
    morning = day.replace(hour=8, minute=rng.randint(0, 20), second=0)
    night = day.replace(hour=22, minute=rng.randint(0, 20), second=0)

    if rng.random() < 0.55:
        add_state(events, morning, "air_purifier", "power", "on")
    if rng.random() < 0.25:
        add_state(events, morning + timedelta(minutes=rng.randint(5, 40)), "air_purifier", "mode", rng.choice(["auto", "sleep", "normal"]))
    if rng.random() < 0.2:
        add_state(events, night, "air_purifier", "mode", "sleep")


def generate_normal(start_date, days, seed):
    rng = random.Random(seed)
    events = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        add_fridge_routine(events, day, rng)
        add_laundry_routine(events, day, rng)
        add_air_purifier_routine(events, day, rng)
    return sorted(events, key=lambda row: row[0])


def add_repeated_fridge_anomaly(events, start):
    for idx in range(8):
        when = start + timedelta(seconds=idx * 65)
        add_toggle(events, when, "fridge", "door", "open", "close", 20)


def add_laundry_anomaly(events, start):
    for idx in range(4):
        when = start + timedelta(minutes=idx * 8)
        add_state(events, when, "washer", "operation", "running")
        add_state(events, when + timedelta(minutes=3), "washer", "operation", "idle")


def add_air_purifier_anomaly(events, start):
    modes = ["auto", "sleep", "normal", "turbo"]
    for idx in range(10):
        add_state(events, start + timedelta(minutes=idx * 2), "air_purifier", "mode", modes[idx % len(modes)])


def generate_abnormal(start_date, seed):
    events = generate_normal(start_date, 3, seed)
    day_1 = start_date + timedelta(days=1)
    day_2 = start_date + timedelta(days=2)
    add_repeated_fridge_anomaly(events, day_1.replace(hour=22, minute=5, second=0))
    add_laundry_anomaly(events, day_2.replace(hour=23, minute=10, second=0))
    add_air_purifier_anomaly(events, day_2.replace(hour=2, minute=0, second=0))
    return sorted(events, key=lambda row: row[0])


def write_csv(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["event_time", "device_type", "signal_type", "action"])
        for when, device_type, signal_type, action in events:
            writer.writerow([when.strftime("%Y-%m-%d %H:%M:%S"), device_type, signal_type, action])


def main():
    normal_start = datetime(2026, 8, 1)
    abnormal_start = datetime(2026, 8, 31)

    normal_events = generate_normal(normal_start, days=30, seed=20260830)
    abnormal_events = generate_abnormal(abnormal_start, seed=20260831)

    normal_path = RAW_DIR / "normal_events_30d.csv"
    abnormal_path = RAW_DIR / "abnormal_events_test.csv"
    write_csv(normal_path, normal_events)
    write_csv(abnormal_path, abnormal_events)

    print(f"wrote {normal_path} ({len(normal_events)} events)")
    print(f"wrote {abnormal_path} ({len(abnormal_events)} events)")


if __name__ == "__main__":
    main()
