import argparse
from datetime import datetime, timedelta
import os
import math
from zoneinfo import ZoneInfo

import pandas as pd


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
    "dishwasher_operation_change_count_30m",
    "dishwasher_operation_change_count_1h",
    "dishwasher_start_count_2h",
    "dishwasher_done_to_restart_count_2h",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
]


def parse_time(value):
    value = str(value).strip()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is not None:
            result = result.astimezone(ZoneInfo(os.getenv("HA_TIMEZONE", "Asia/Seoul")))
        return result.replace(tzinfo=None)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def count_events(df, end_time, minutes, device=None, signal=None, action=None):
    start_time = end_time - timedelta(minutes=minutes)
    q = df[(df["time"] > start_time) & (df["time"] <= end_time)]
    if "_countable" in q:
        q = q[q["_countable"]]

    if device is not None:
        q = q[q["device_type"] == device]
    if signal is not None:
        q = q[q["signal_type"] == signal]
    if action is not None:
        if isinstance(action, (list, tuple, set)):
            q = q[q["action"].isin(action)]
        else:
            q = q[q["action"] == action]

    return int(len(q))


def count_changes(df, end_time, minutes, device, signal):
    start_time = end_time - timedelta(minutes=minutes)
    q = df[
        (df["time"] > start_time)
        & (df["time"] <= end_time)
        & (df["device_type"] == device)
        & (df["signal_type"] == signal)
    ].sort_values("time")

    if "_transition" in q:
        return int(q["_transition"].sum())
    if len(q) <= 1:
        return 0

    return int((q["action"] != q["action"].shift()).sum() - 1)


def done_to_restart_count(df, end_time, minutes, device):
    start_time = end_time - timedelta(minutes=minutes)
    q = df[
        (df["time"] > start_time)
        & (df["time"] <= end_time)
        & (df["device_type"] == device)
        & (df["signal_type"] == "operation")
    ].sort_values("time")

    count = 0
    groups = q.groupby("_stream") if "_stream" in q else [("legacy", q)]
    for _, group in groups:
        seen_done = False
        for _, row in group.iterrows():
            if row.get("record_type") == "state_snapshot":
                continue
            if row["action"] == "done":
                seen_done = True
            elif seen_done and row["action"] == "running":
                count += 1
                seen_done = False

    return count


def prepare_events(events):
    events = events.copy()
    events["time"] = events["event_time"].apply(parse_time)
    if "record_type" not in events:
        events["record_type"] = "state_changed_event"
    snapshots = events["record_type"].eq("state_snapshot")
    if "recorded_at" in events:

        for index in events.index[snapshots]:
            value = events.at[index, "recorded_at"]
            if pd.notna(value) and str(value):
                events.at[index, "time"] = parse_time(value)
    for column in ("device_type", "signal_type", "action"):
        events[column] = events[column].astype(str).str.lower()
    if "entity_id" not in events:
        events["entity_id"] = ""
    events["entity_id"] = events["entity_id"].fillna("")
    events["_stream"] = events["entity_id"].where(events["entity_id"].ne(""), events["device_type"]) + ":" + events["signal_type"]
    events = events.sort_values("time", kind="stable")
    previous = events.groupby("_stream")["action"].shift()
    actual = events["record_type"].ne("state_snapshot")
    changed = events["action"].ne(previous)
    events["_countable"] = actual & changed
    events["_transition"] = actual & changed & previous.notna()
    return events


def night_count(events, current, device, signal, action):
    hours = events["time"].dt.hour
    night = events[(hours >= 21) | (hours < 6)]
    return count_events(night, current, 60, device, signal, action)


def build_features(events, start_time=None, end_time=None, step_minutes=1):
    if step_minutes <= 0:
        raise ValueError('step_minutes must be positive')
    rows = []
    if events.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    if "_countable" not in events:
        if "event_time" not in events:
            events = events.assign(event_time=events["time"].astype(str))
        events = prepare_events(events)
    start = start_time or events["time"].min().replace(second=0, microsecond=0)
    end = end_time or events["time"].max().ceil("min").to_pydatetime()

    current = start
    while current <= end:
        hour = current.hour
        is_night = int(hour >= 21 or hour < 6)

        row = {
            "window_end": current.strftime("%Y-%m-%d %H:%M:%S"),
            "hour": hour,
            "is_night": is_night,
            "hour_sin": math.sin(2 * math.pi * (current.hour + current.minute / 60) / 24),
            "hour_cos": math.cos(2 * math.pi * (current.hour + current.minute / 60) / 24),
            "weekday_sin": math.sin(2 * math.pi * current.weekday() / 7),
            "weekday_cos": math.cos(2 * math.pi * current.weekday() / 7),

            "fridge_door_open_count_10m": count_events(events, current, 10, "fridge", "door", "open"),
            "fridge_door_open_count_30m": count_events(events, current, 30, "fridge", "door", "open"),
            "fridge_door_open_count_1h": count_events(events, current, 60, "fridge", "door", "open"),
            "fridge_door_toggle_count_10m": count_changes(events, current, 10, "fridge", "door"),
            "fridge_door_toggle_count_30m": count_changes(events, current, 30, "fridge", "door"),
            "fridge_door_toggle_count_1h": count_changes(events, current, 60, "fridge", "door"),
            "fridge_night_open_count_1h": night_count(events, current, "fridge", "door", "open"),

            "door_lock_unlock_count_10m": count_events(events, current, 10, "door_lock", "lock", "unlock"),
            "door_lock_unlock_count_30m": count_events(events, current, 30, "door_lock", "lock", "unlock"),
            "door_lock_unlock_count_1h": count_events(events, current, 60, "door_lock", "lock", "unlock"),
            "door_lock_lock_toggle_count_10m": count_changes(events, current, 10, "door_lock", "lock"),
            "door_lock_lock_toggle_count_30m": count_changes(events, current, 30, "door_lock", "lock"),
            "door_lock_lock_toggle_count_1h": count_changes(events, current, 60, "door_lock", "lock"),
            "door_lock_night_unlock_count_1h": night_count(events, current, "door_lock", "lock", "unlock"),

            "microwave_start_count_10m": count_events(events, current, 10, "microwave", "operation", "running"),
            "microwave_start_count_30m": count_events(events, current, 30, "microwave", "operation", "running"),
            "microwave_start_count_1h": count_events(events, current, 60, "microwave", "operation", "running"),
            "microwave_night_start_count_1h": night_count(events, current, "microwave", "operation", "running"),
            "microwave_operation_change_count_30m": count_changes(events, current, 30, "microwave", "operation"),
            "microwave_operation_change_count_1h": count_changes(events, current, 60, "microwave", "operation"),

            "washer_operation_change_count_30m": count_changes(events, current, 30, "washer", "operation"),
            "washer_operation_change_count_1h": count_changes(events, current, 60, "washer", "operation"),
            "washer_start_count_2h": count_events(events, current, 120, "washer", "operation", "running"),
            "washer_done_to_restart_count_2h": done_to_restart_count(events, current, 120, "washer"),

            "dryer_operation_change_count_30m": count_changes(events, current, 30, "dryer", "operation"),
            "dryer_operation_change_count_1h": count_changes(events, current, 60, "dryer", "operation"),
            "dryer_start_count_2h": count_events(events, current, 120, "dryer", "operation", "running"),
            "dryer_done_to_restart_count_2h": done_to_restart_count(events, current, 120, "dryer"),

            "air_purifier_power_toggle_count_30m": count_changes(events, current, 30, "air_purifier", "power"),
            "air_purifier_mode_change_count_30m": count_changes(events, current, 30, "air_purifier", "mode"),
            "air_purifier_speed_change_count_30m": count_changes(events, current, 30, "air_purifier", "speed"),
            "air_purifier_mode_change_count_1h": count_changes(events, current, 60, "air_purifier", "mode"),
            "air_purifier_speed_change_count_1h": count_changes(events, current, 60, "air_purifier", "speed"),
            "air_purifier_mode_event_count_30m": count_events(events, current, 30, "air_purifier", "mode"),
            "air_purifier_mode_event_count_1h": count_events(events, current, 60, "air_purifier", "mode"),
            "air_purifier_speed_event_count_30m": count_events(events, current, 30, "air_purifier", "speed"),
            "air_purifier_speed_event_count_1h": count_events(events, current, 60, "air_purifier", "speed"),

            "air_conditioner_power_toggle_count_30m": count_changes(events, current, 30, "air_conditioner", "power"),
            "air_conditioner_mode_change_count_30m": count_changes(events, current, 30, "air_conditioner", "mode"),
            "air_conditioner_mode_change_count_1h": count_changes(events, current, 60, "air_conditioner", "mode"),
            "air_conditioner_temperature_change_count_30m": count_changes(events, current, 30, "air_conditioner", "temperature"),
            "air_conditioner_temperature_change_count_1h": count_changes(events, current, 60, "air_conditioner", "temperature"),
            "air_conditioner_temperature_event_count_30m": count_events(events, current, 30, "air_conditioner", "temperature"),
            "air_conditioner_temperature_event_count_1h": count_events(events, current, 60, "air_conditioner", "temperature"),
            "dishwasher_operation_change_count_30m": count_changes(events, current, 30, "dishwasher", "operation"),
            "dishwasher_operation_change_count_1h": count_changes(events, current, 60, "dishwasher", "operation"),
            "dishwasher_start_count_2h": count_events(events, current, 120, "dishwasher", "operation", "running"),
            "dishwasher_done_to_restart_count_2h": done_to_restart_count(events, current, 120, "dishwasher"),
        }

        rows.append(row)
        current += timedelta(minutes=step_minutes)

    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    args = parser.parse_args()
    df = pd.read_csv(args.input)
    features = build_features(df, parse_time(args.window_start) if args.window_start else None,
                              parse_time(args.window_end) if args.window_end else None)
    features.to_csv(args.output, index=False)
    print(f"saved: {args.output}")
    print(f"rows: {len(features)}")
    print(f"columns: {len(features.columns)}")


if __name__ == "__main__":
    main()
