import argparse
import bisect
import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


FEATURE_COLUMNS = [
    "window_end",
    "hour",
    "is_night",
    "fridge_door_open_count_10m",
    "fridge_door_open_count_30m",
    "fridge_door_open_count_1h",
    "fridge_door_toggle_count_10m",
    "fridge_door_toggle_count_30m",
    "fridge_door_toggle_count_1h",
    "fridge_night_open_count_1h",
    "door_lock_unlock_count_10m",
    "door_lock_unlock_count_30m",
    "door_lock_unlock_count_1h",
    "door_lock_lock_toggle_count_10m",
    "door_lock_lock_toggle_count_30m",
    "door_lock_lock_toggle_count_1h",
    "door_lock_night_unlock_count_1h",
    "microwave_start_count_10m",
    "microwave_start_count_30m",
    "microwave_start_count_1h",
    "microwave_night_start_count_1h",
    "microwave_operation_change_count_30m",
    "microwave_operation_change_count_1h",
    "washer_operation_change_count_30m",
    "washer_operation_change_count_1h",
    "washer_start_count_2h",
    "washer_done_to_restart_count_2h",
    "dryer_operation_change_count_30m",
    "dryer_operation_change_count_1h",
    "dryer_start_count_2h",
    "dryer_done_to_restart_count_2h",
    "air_purifier_power_toggle_count_30m",
    "air_purifier_mode_change_count_30m",
    "air_purifier_speed_change_count_30m",
    "air_purifier_mode_change_count_1h",
    "air_purifier_speed_change_count_1h",
    "air_purifier_mode_event_count_30m",
    "air_purifier_mode_event_count_1h",
    "air_purifier_speed_event_count_30m",
    "air_purifier_speed_event_count_1h",
    "air_conditioner_power_toggle_count_30m",
    "air_conditioner_mode_change_count_30m",
    "air_conditioner_mode_change_count_1h",
    "air_conditioner_temperature_change_count_30m",
    "air_conditioner_temperature_change_count_1h",
    "air_conditioner_temperature_event_count_30m",
    "air_conditioner_temperature_event_count_1h",
]


def parse_time(value):
    value = str(value).strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def timestamp(value):
    return value.timestamp()


def count_between(times, end_ts, minutes):
    start_ts = end_ts - minutes * 60
    left = bisect.bisect_right(times, start_ts)
    right = bisect.bisect_right(times, end_ts)
    return right - left


def change_count(times, actions, end_ts, minutes):
    start_ts = end_ts - minutes * 60
    left = bisect.bisect_right(times, start_ts)
    right = bisect.bisect_right(times, end_ts)
    if right - left <= 1:
        return 0

    count = 0
    prev = actions[left]
    for action in actions[left + 1:right]:
        if action != prev:
            count += 1
        prev = action
    return count


def done_to_restart_count(times, actions, end_ts, minutes):
    start_ts = end_ts - minutes * 60
    left = bisect.bisect_right(times, start_ts)
    right = bisect.bisect_right(times, end_ts)

    count = 0
    seen_done = False
    for action in actions[left:right]:
        if action == "done":
            seen_done = True
        elif seen_done and action == "running":
            count += 1
            seen_done = False
    return count


def empty_series():
    return [], []


def load_events(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "time": parse_time(row["event_time"]),
                "device_type": str(row["device_type"]).strip(),
                "signal_type": str(row["signal_type"]).strip(),
                "action": str(row["action"]).strip().lower(),
            })
    return sorted(rows, key=lambda row: row["time"])


def build_indexes(events):
    event_times = defaultdict(list)
    signal_times = defaultdict(list)
    signal_actions = defaultdict(list)

    for row in events:
        ts = timestamp(row["time"])
        device = row["device_type"]
        signal = row["signal_type"]
        action = row["action"]

        event_times[(device, signal, action)].append(ts)
        signal_times[(device, signal)].append(ts)
        signal_actions[(device, signal)].append(action)

    return event_times, signal_times, signal_actions


def event_count(event_times, end_ts, minutes, device, signal, action):
    return count_between(event_times.get((device, signal, action), []), end_ts, minutes)


def signal_change_count(signal_times, signal_actions, end_ts, minutes, device, signal):
    times, actions = (
        signal_times.get((device, signal), []),
        signal_actions.get((device, signal), []),
    )
    return change_count(times, actions, end_ts, minutes)


def signal_done_to_restart(signal_times, signal_actions, end_ts, minutes, device):
    times, actions = (
        signal_times.get((device, "operation"), []),
        signal_actions.get((device, "operation"), []),
    )
    return done_to_restart_count(times, actions, end_ts, minutes)


def build_features(events):
    if not events:
        return []

    event_times, signal_times, signal_actions = build_indexes(events)
    start = events[0]["time"].replace(second=0, microsecond=0)
    end = events[-1]["time"].replace(second=0, microsecond=0)

    rows = []
    current = start
    while current <= end:
        end_ts = timestamp(current)
        hour = current.hour
        is_night = int(hour >= 21 or hour < 6)
        fridge_open_1h = event_count(
            event_times,
            end_ts,
            60,
            "fridge",
            "door",
            "open",
        )

        row = {
            "window_end": current.strftime("%Y-%m-%d %H:%M:%S"),
            "hour": hour,
            "is_night": is_night,
            "fridge_door_open_count_10m": event_count(event_times, end_ts, 10, "fridge", "door", "open"),
            "fridge_door_open_count_30m": event_count(event_times, end_ts, 30, "fridge", "door", "open"),
            "fridge_door_open_count_1h": fridge_open_1h,
            "fridge_door_toggle_count_10m": signal_change_count(signal_times, signal_actions, end_ts, 10, "fridge", "door"),
            "fridge_door_toggle_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "fridge", "door"),
            "fridge_door_toggle_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "fridge", "door"),
            "fridge_night_open_count_1h": fridge_open_1h if is_night else 0,
            "door_lock_unlock_count_10m": event_count(event_times, end_ts, 10, "door_lock", "lock", "unlock"),
            "door_lock_unlock_count_30m": event_count(event_times, end_ts, 30, "door_lock", "lock", "unlock"),
            "door_lock_unlock_count_1h": event_count(event_times, end_ts, 60, "door_lock", "lock", "unlock"),
            "door_lock_lock_toggle_count_10m": signal_change_count(signal_times, signal_actions, end_ts, 10, "door_lock", "lock"),
            "door_lock_lock_toggle_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "door_lock", "lock"),
            "door_lock_lock_toggle_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "door_lock", "lock"),
            "door_lock_night_unlock_count_1h": event_count(event_times, end_ts, 60, "door_lock", "lock", "unlock") if is_night else 0,
            "microwave_start_count_10m": event_count(event_times, end_ts, 10, "microwave", "operation", "running"),
            "microwave_start_count_30m": event_count(event_times, end_ts, 30, "microwave", "operation", "running"),
            "microwave_start_count_1h": event_count(event_times, end_ts, 60, "microwave", "operation", "running"),
            "microwave_night_start_count_1h": event_count(event_times, end_ts, 60, "microwave", "operation", "running") if is_night else 0,
            "microwave_operation_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "microwave", "operation"),
            "microwave_operation_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "microwave", "operation"),
            "washer_operation_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "washer", "operation"),
            "washer_operation_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "washer", "operation"),
            "washer_start_count_2h": event_count(event_times, end_ts, 120, "washer", "operation", "running"),
            "washer_done_to_restart_count_2h": signal_done_to_restart(signal_times, signal_actions, end_ts, 120, "washer"),
            "dryer_operation_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "dryer", "operation"),
            "dryer_operation_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "dryer", "operation"),
            "dryer_start_count_2h": event_count(event_times, end_ts, 120, "dryer", "operation", "running"),
            "dryer_done_to_restart_count_2h": signal_done_to_restart(signal_times, signal_actions, end_ts, 120, "dryer"),
            "air_purifier_power_toggle_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "air_purifier", "power"),
            "air_purifier_mode_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "air_purifier", "mode"),
            "air_purifier_speed_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "air_purifier", "speed"),
            "air_purifier_mode_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "air_purifier", "mode"),
            "air_purifier_speed_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "air_purifier", "speed"),
            "air_purifier_mode_event_count_30m": count_between(signal_times.get(("air_purifier", "mode"), []), end_ts, 30),
            "air_purifier_mode_event_count_1h": count_between(signal_times.get(("air_purifier", "mode"), []), end_ts, 60),
            "air_purifier_speed_event_count_30m": count_between(signal_times.get(("air_purifier", "speed"), []), end_ts, 30),
            "air_purifier_speed_event_count_1h": count_between(signal_times.get(("air_purifier", "speed"), []), end_ts, 60),
            "air_conditioner_power_toggle_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "air_conditioner", "power"),
            "air_conditioner_mode_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "air_conditioner", "mode"),
            "air_conditioner_mode_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "air_conditioner", "mode"),
            "air_conditioner_temperature_change_count_30m": signal_change_count(signal_times, signal_actions, end_ts, 30, "air_conditioner", "temperature"),
            "air_conditioner_temperature_change_count_1h": signal_change_count(signal_times, signal_actions, end_ts, 60, "air_conditioner", "temperature"),
            "air_conditioner_temperature_event_count_30m": count_between(signal_times.get(("air_conditioner", "temperature"), []), end_ts, 30),
            "air_conditioner_temperature_event_count_1h": count_between(signal_times.get(("air_conditioner", "temperature"), []), end_ts, 60),
        }
        rows.append(row)
        current += timedelta(minutes=1)

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    events = load_events(args.input)
    rows = build_features(events)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"saved: {output_path}")
    print(f"rows: {len(rows)}")
    print(f"columns: {len(FEATURE_COLUMNS)}")


if __name__ == "__main__":
    main()
