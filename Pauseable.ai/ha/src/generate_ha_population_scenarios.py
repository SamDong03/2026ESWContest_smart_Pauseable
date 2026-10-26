import argparse
import csv
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
STANDARD_FIELDS = ["event_time", "device_type", "signal_type", "action"]

MODES = ["auto", "clean", "circulator", "dual_clean"]
SPEEDS = ["low", "mid", "high", "auto"]
AIRCON_MODES = ["auto", "cool", "dry", "fan"]

PROFILE_TEMPLATES = [
    {
        "profile": "regular_daytime",
        "meal_hours": [7.4, 12.2, 18.5],
        "extra_fridge": (1, 3),
        "active_hours": (7.0, 22.0),
        "night_fridge_prob": 0.03,
        "air_mode_prob": 0.25,
        "air_speed_prob": 0.25,
        "air_power_prob": 0.60,
        "washer_weekly": 2.0,
        "dryer_after_washer_prob": 0.75,
    },
    {
        "profile": "early_bird",
        "meal_hours": [5.8, 11.4, 17.4],
        "extra_fridge": (1, 2),
        "active_hours": (5.2, 20.5),
        "night_fridge_prob": 0.01,
        "air_mode_prob": 0.20,
        "air_speed_prob": 0.20,
        "air_power_prob": 0.55,
        "washer_weekly": 1.5,
        "dryer_after_washer_prob": 0.70,
    },
    {
        "profile": "night_owl_normal",
        "meal_hours": [10.2, 14.3, 20.4],
        "extra_fridge": (2, 4),
        "active_hours": (10.0, 24.8),
        "night_fridge_prob": 0.45,
        "night_fridge_hour": 23.4,
        "air_mode_prob": 0.35,
        "air_speed_prob": 0.30,
        "air_power_prob": 0.65,
        "washer_weekly": 1.8,
        "dryer_after_washer_prob": 0.70,
    },
    {
        "profile": "frequent_fridge_user",
        "meal_hours": [7.5, 10.2, 12.5, 15.8, 18.8, 21.1],
        "extra_fridge": (3, 6),
        "active_hours": (7.0, 22.5),
        "night_fridge_prob": 0.10,
        "air_mode_prob": 0.25,
        "air_speed_prob": 0.20,
        "air_power_prob": 0.60,
        "washer_weekly": 2.0,
        "dryer_after_washer_prob": 0.75,
    },
    {
        "profile": "low_activity",
        "meal_hours": [8.5, 12.8, 18.2],
        "extra_fridge": (0, 1),
        "active_hours": (8.0, 20.0),
        "night_fridge_prob": 0.01,
        "air_mode_prob": 0.10,
        "air_speed_prob": 0.10,
        "air_power_prob": 0.35,
        "washer_weekly": 0.8,
        "dryer_after_washer_prob": 0.55,
    },
    {
        "profile": "air_purifier_active",
        "meal_hours": [7.6, 12.0, 18.6],
        "extra_fridge": (1, 3),
        "active_hours": (7.0, 22.0),
        "night_fridge_prob": 0.04,
        "air_mode_prob": 0.75,
        "air_speed_prob": 0.75,
        "air_power_prob": 0.90,
        "washer_weekly": 1.4,
        "dryer_after_washer_prob": 0.60,
    },
    {
        "profile": "laundry_heavy",
        "meal_hours": [7.8, 12.4, 18.6],
        "extra_fridge": (1, 3),
        "active_hours": (7.0, 22.0),
        "night_fridge_prob": 0.04,
        "air_mode_prob": 0.25,
        "air_speed_prob": 0.25,
        "air_power_prob": 0.65,
        "washer_weekly": 4.5,
        "dryer_after_washer_prob": 0.90,
    },
    {
        "profile": "irregular_schedule",
        "meal_hours": [8.8, 13.4, 19.4],
        "extra_fridge": (0, 5),
        "active_hours": (6.0, 23.8),
        "night_fridge_prob": 0.18,
        "night_fridge_hour": 0.4,
        "air_mode_prob": 0.40,
        "air_speed_prob": 0.35,
        "air_power_prob": 0.70,
        "washer_weekly": 2.2,
        "dryer_after_washer_prob": 0.70,
    },
    {
        "profile": "weekend_laundry",
        "meal_hours": [8.0, 12.2, 18.4],
        "extra_fridge": (1, 3),
        "active_hours": (7.5, 22.0),
        "night_fridge_prob": 0.04,
        "air_mode_prob": 0.30,
        "air_speed_prob": 0.25,
        "air_power_prob": 0.60,
        "washer_weekly": 2.8,
        "dryer_after_washer_prob": 0.85,
        "weekend_laundry_bias": True,
    },
    {
        "profile": "sleep_fragmented",
        "meal_hours": [7.5, 12.1, 18.2],
        "extra_fridge": (1, 3),
        "active_hours": (7.0, 21.5),
        "night_fridge_prob": 0.30,
        "night_fridge_hour": 2.2,
        "air_mode_prob": 0.30,
        "air_speed_prob": 0.25,
        "air_power_prob": 0.65,
        "washer_weekly": 1.5,
        "dryer_after_washer_prob": 0.60,
    },
    {
        "profile": "caregiver_visit_days",
        "meal_hours": [7.2, 12.1, 18.1],
        "extra_fridge": (1, 4),
        "active_hours": (7.0, 22.0),
        "night_fridge_prob": 0.05,
        "air_mode_prob": 0.30,
        "air_speed_prob": 0.30,
        "air_power_prob": 0.70,
        "washer_weekly": 2.5,
        "dryer_after_washer_prob": 0.75,
        "caregiver_visit_prob": 0.22,
    },
    {
        "profile": "appliance_power_user",
        "meal_hours": [7.3, 12.6, 18.7],
        "extra_fridge": (2, 4),
        "active_hours": (7.0, 22.4),
        "night_fridge_prob": 0.08,
        "air_mode_prob": 0.55,
        "air_speed_prob": 0.55,
        "air_power_prob": 0.95,
        "washer_weekly": 2.4,
        "dryer_after_washer_prob": 0.80,
    },
]

TEST_CASES = [
    {
        "case_id": "normal_profile_day",
        "expected_min_level": "normal",
        "expected_max_level": "normal",
        "expected_primary_pattern": "",
        "expected_episode_min": 0,
        "expected_episode_max": 0,
        "notes": "Typical day from the user's own learned profile.",
    },
    {
        "case_id": "normal_busy_day",
        "expected_min_level": "normal",
        "expected_max_level": "normal",
        "expected_primary_pattern": "",
        "expected_episode_min": 0,
        "expected_episode_max": 0,
        "notes": "Busy but spread-out appliance use should not become an alert.",
    },
    {
        "case_id": "normal_single_night_activity",
        "expected_min_level": "normal",
        "expected_max_level": "normal",
        "expected_primary_pattern": "",
        "expected_episode_min": 0,
        "expected_episode_max": 0,
        "notes": "A single night event is not enough for dementia-risk behavior.",
    },
    {
        "case_id": "attention_air_mode_day",
        "expected_min_level": "attention",
        "expected_max_level": "risk",
        "expected_primary_pattern": "air_purifier_repeated_control",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Borderline daytime air purifier mode repetition.",
    },
    {
        "case_id": "attention_air_speed_day",
        "expected_min_level": "attention",
        "expected_max_level": "risk",
        "expected_primary_pattern": "air_purifier_repeated_control",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Borderline daytime air purifier speed repetition.",
    },
    {
        "case_id": "attention_ac_temperature_loop_day",
        "expected_min_level": "attention",
        "expected_max_level": "risk",
        "expected_primary_pattern": "air_conditioner_repeated_control",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Borderline daytime air conditioner target-temperature repetition.",
    },
    {
        "case_id": "attention_washer_operation_loop_day",
        "expected_min_level": "attention",
        "expected_max_level": "risk",
        "expected_primary_pattern": "washer_repeated_operation",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Daytime washer state loop without done-to-restart.",
    },
    {
        "case_id": "borderline_day_fridge_recheck",
        "expected_min_level": "normal",
        "expected_max_level": "risk",
        "expected_primary_pattern": "fridge_repeated_check",
        "expected_episode_min": 0,
        "expected_episode_max": 8,
        "notes": "Daytime fridge rechecking is borderline; personalization may keep it normal for users with frequent fridge activity.",
    },
    {
        "case_id": "risk_night_fridge_recheck",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "fridge_repeated_check",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Night fridge rechecking with short-window and sustained support.",
    },
    {
        "case_id": "risk_dawn_door_unlock_loop",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "door_lock_repeated_unlock",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Deep-night repeated door-lock checking.",
    },
    {
        "case_id": "risk_night_microwave_reuse",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "microwave_repeated_use",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Night microwave reuse with repeated operation states.",
    },
    {
        "case_id": "risk_dawn_air_mode_loop",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "air_purifier_repeated_control",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Deep-night repeated air purifier control.",
    },
    {
        "case_id": "risk_dawn_ac_mode_loop",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "air_conditioner_repeated_control",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Deep-night repeated air conditioner mode and temperature control.",
    },
    {
        "case_id": "risk_washer_restart_after_done",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "washer_restart_after_done",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Washer restart after a done state at night.",
    },
    {
        "case_id": "risk_dryer_restart_after_done",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "dryer_restart_after_done",
        "expected_episode_min": 1,
        "expected_episode_max": 8,
        "notes": "Dryer restart after a done state at night.",
    },
    {
        "case_id": "risk_multi_device_night_loop",
        "expected_min_level": "risk",
        "expected_max_level": "risk",
        "expected_primary_pattern": "",
        "expected_episode_min": 1,
        "expected_episode_max": 12,
        "notes": "Night fridge checking and air purifier loop happen together.",
    },
]


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else BASE / path


def relative_to_base(path):
    try:
        return path.resolve().relative_to(BASE.resolve()).as_posix()
    except ValueError:
        return str(path)


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def time_at(day, hour_value, rng, jitter_minutes=0):
    whole_hour = int(hour_value)
    minute = int(round((hour_value - whole_hour) * 60))
    base = datetime.combine(day, time()) + timedelta(hours=whole_hour, minutes=minute)
    if jitter_minutes:
        base += timedelta(minutes=rng.randint(-jitter_minutes, jitter_minutes))
    return base.replace(second=rng.randint(0, 50), microsecond=0)


def random_hour(rng, active_hours):
    start, end = active_hours
    return rng.uniform(start, end)


def add_event(events, event_time, device_type, signal_type, action):
    events.append({
        "event_time": event_time.strftime("%Y-%m-%d %H:%M:%S"),
        "device_type": device_type,
        "signal_type": signal_type,
        "action": action,
    })


def add_fridge_use(events, event_time, rng, duration_seconds=None):
    if duration_seconds is None:
        duration_seconds = rng.randint(12, 75)
    add_event(events, event_time, "fridge", "door", "open")
    add_event(
        events,
        event_time + timedelta(seconds=duration_seconds),
        "fridge",
        "door",
        "close",
    )


def add_laundry_cycle(events, day, device, start_hour, rng, restart_after_done=False):
    start = time_at(day, start_hour, rng, jitter_minutes=12)
    duration = rng.randint(45, 95)
    done = start + timedelta(minutes=duration)
    idle = done + timedelta(minutes=rng.randint(3, 10))

    add_event(events, start, device, "operation", "running")
    add_event(events, done, device, "operation", "done")
    add_event(events, idle, device, "operation", "idle")

    if restart_after_done:
        restart = done + timedelta(minutes=rng.randint(12, 28))
        done_again = restart + timedelta(minutes=rng.randint(30, 65))
        add_event(events, restart, device, "operation", "running")
        add_event(events, done_again, device, "operation", "done")
        add_event(events, done_again + timedelta(minutes=5), device, "operation", "idle")

    return idle


def add_air_normal(events, day, profile, rng):
    if rng.random() > profile["air_power_prob"]:
        return

    start_hour, end_hour = profile["active_hours"]
    on_time = time_at(day, start_hour + 0.4, rng, jitter_minutes=18)
    off_hour = min(end_hour, 23.6)
    off_time = time_at(day, off_hour, rng, jitter_minutes=18)

    add_event(events, on_time, "air_purifier", "power", "on")
    add_event(events, on_time + timedelta(minutes=1), "air_purifier", "mode", "auto")

    if rng.random() < profile["air_speed_prob"]:
        add_event(
            events,
            on_time + timedelta(minutes=rng.randint(3, 20)),
            "air_purifier",
            "speed",
            rng.choice(SPEEDS),
        )

    if rng.random() < profile["air_mode_prob"]:
        change_time = time_at(day, random_hour(rng, profile["active_hours"]), rng, 20)
        add_event(events, change_time, "air_purifier", "mode", rng.choice(MODES))

    if rng.random() < profile["air_speed_prob"] * 0.6:
        change_time = time_at(day, random_hour(rng, profile["active_hours"]), rng, 20)
        add_event(events, change_time, "air_purifier", "speed", rng.choice(SPEEDS))

    add_event(events, off_time, "air_purifier", "power", "off")


def add_door_lock_cycle(events, event_time, rng, stay_minutes=None):
    if stay_minutes is None:
        stay_minutes = rng.randint(2, 12)
    add_event(events, event_time, "door_lock", "lock", "unlock")
    add_event(events, event_time + timedelta(minutes=stay_minutes), "door_lock", "lock", "lock")


def add_door_lock_loop(events, day, start_hour, rng, cycles, gap_minutes=3):
    start = time_at(day, start_hour, rng, jitter_minutes=1)
    for i in range(cycles):
        unlock_time = start + timedelta(minutes=i * gap_minutes)
        add_event(events, unlock_time, "door_lock", "lock", "unlock")
        add_event(events, unlock_time + timedelta(seconds=rng.randint(20, 55)), "door_lock", "lock", "lock")


def add_microwave_use(events, event_time, rng, duration_minutes=None):
    if duration_minutes is None:
        duration_minutes = rng.randint(2, 8)
    add_event(events, event_time, "microwave", "power", "on")
    add_event(events, event_time + timedelta(seconds=10), "microwave", "operation", "running")
    done_time = event_time + timedelta(minutes=duration_minutes)
    add_event(events, done_time, "microwave", "operation", "done")
    add_event(events, done_time + timedelta(minutes=1), "microwave", "operation", "idle")
    add_event(events, done_time + timedelta(minutes=1, seconds=20), "microwave", "power", "off")


def add_microwave_reuse(events, day, start_hour, rng, count, gap_minutes=7):
    start = time_at(day, start_hour, rng, jitter_minutes=1)
    for i in range(count):
        add_microwave_use(
            events,
            start + timedelta(minutes=i * gap_minutes),
            rng,
            duration_minutes=rng.randint(1, 3),
        )


def add_air_conditioner_normal(events, day, profile, rng):
    if rng.random() > profile.get("aircon_power_prob", 0.35):
        return

    start_hour, end_hour = profile["active_hours"]
    on_time = time_at(day, max(start_hour + 0.8, 9.0), rng, jitter_minutes=20)
    off_time = time_at(day, min(end_hour, 23.2), rng, jitter_minutes=20)
    target_temp = str(rng.choice([24, 25, 26]))

    add_event(events, on_time, "air_conditioner", "power", "on")
    add_event(events, on_time + timedelta(minutes=1), "air_conditioner", "mode", rng.choice(["auto", "cool"]))
    add_event(events, on_time + timedelta(minutes=2), "air_conditioner", "temperature", target_temp)

    if rng.random() < profile.get("aircon_adjust_prob", 0.20):
        adjust_time = time_at(day, random_hour(rng, profile["active_hours"]), rng, 15)
        add_event(events, adjust_time, "air_conditioner", "temperature", str(rng.choice([23, 24, 25, 26])))

    add_event(events, off_time, "air_conditioner", "power", "off")


def add_air_conditioner_mode_loop(events, day, start_hour, rng, count, gap_minutes=4):
    start = time_at(day, start_hour, rng, jitter_minutes=1)
    for i in range(count):
        add_event(
            events,
            start + timedelta(minutes=i * gap_minutes),
            "air_conditioner",
            "mode",
            AIRCON_MODES[i % len(AIRCON_MODES)],
        )


def add_air_conditioner_temperature_loop(events, day, start_hour, rng, count, gap_minutes=4):
    start = time_at(day, start_hour, rng, jitter_minutes=1)
    temps = ["24", "22", "26", "23", "25"]
    for i in range(count):
        add_event(
            events,
            start + timedelta(minutes=i * gap_minutes),
            "air_conditioner",
            "temperature",
            temps[i % len(temps)],
        )


def add_profile_normal_day(events, day, profile, rng, busy=False):
    for hour in profile["meal_hours"]:
        if rng.random() < 0.95:
            add_fridge_use(events, time_at(day, hour, rng, jitter_minutes=18), rng)

    extra_min, extra_max = profile["extra_fridge"]
    extra_count = rng.randint(extra_min, extra_max)
    if busy:
        extra_count += rng.randint(2, 4)

    for _ in range(extra_count):
        add_fridge_use(
            events,
            time_at(day, random_hour(rng, profile["active_hours"]), rng, 10),
            rng,
        )

    if rng.random() < profile.get("night_fridge_prob", 0.0):
        night_hour = profile.get("night_fridge_hour", rng.choice([22.7, 23.3, 1.6, 2.3]))
        add_fridge_use(events, time_at(day, night_hour, rng, jitter_minutes=12), rng)

    if busy and rng.random() < 0.5:
        for hour in [10.8, 15.3, 20.8]:
            add_fridge_use(events, time_at(day, hour, rng, jitter_minutes=10), rng)

    if profile.get("caregiver_visit_prob", 0) and rng.random() < profile["caregiver_visit_prob"]:
        for hour in [13.5, 14.3, 15.1]:
            add_fridge_use(events, time_at(day, hour, rng, jitter_minutes=8), rng)
        add_door_lock_cycle(events, time_at(day, 13.4, rng, jitter_minutes=8), rng)

    if rng.random() < profile.get("door_lock_daily_prob", 0.75):
        add_door_lock_cycle(events, time_at(day, 8.2, rng, jitter_minutes=25), rng)
    if rng.random() < profile.get("door_lock_evening_prob", 0.50):
        add_door_lock_cycle(events, time_at(day, 18.7, rng, jitter_minutes=25), rng)

    for hour in profile["meal_hours"]:
        if rng.random() < profile.get("microwave_meal_prob", 0.28):
            add_microwave_use(events, time_at(day, hour + 0.05, rng, jitter_minutes=12), rng)

    add_air_normal(events, day, profile, rng)
    add_air_conditioner_normal(events, day, profile, rng)

    laundry_chance = profile["washer_weekly"] / 7.0
    if profile.get("weekend_laundry_bias") and day.weekday() >= 5:
        laundry_chance *= 1.8
    elif profile.get("weekend_laundry_bias"):
        laundry_chance *= 0.45

    cycle_count = 1 if rng.random() < min(laundry_chance, 0.95) else 0
    if busy and rng.random() < 0.25:
        cycle_count += 1

    for cycle_index in range(cycle_count):
        start_hour = rng.uniform(9.0, 17.0) + cycle_index * 3.8
        washer_idle = add_laundry_cycle(events, day, "washer", start_hour, rng)
        if rng.random() < profile["dryer_after_washer_prob"]:
            dryer_start_hour = (
                washer_idle - datetime.combine(day, time())
            ).total_seconds() / 3600.0 + rng.uniform(0.3, 1.2)
            add_laundry_cycle(events, day, "dryer", dryer_start_hour, rng)


def add_fridge_recheck(events, day, start_hour, rng, opens, gap_minutes):
    start = time_at(day, start_hour, rng, jitter_minutes=2)
    for i in range(opens):
        add_fridge_use(
            events,
            start + timedelta(minutes=i * gap_minutes, seconds=i * 3),
            rng,
            duration_seconds=rng.randint(8, 28),
        )


def add_air_mode_loop(events, day, start_hour, rng, count, gap_minutes=4):
    start = time_at(day, start_hour, rng, jitter_minutes=2)
    for i in range(count):
        add_event(
            events,
            start + timedelta(minutes=i * gap_minutes),
            "air_purifier",
            "mode",
            MODES[i % len(MODES)],
        )


def add_air_speed_loop(events, day, start_hour, rng, count, gap_minutes=5):
    start = time_at(day, start_hour, rng, jitter_minutes=2)
    for i in range(count):
        add_event(
            events,
            start + timedelta(minutes=i * gap_minutes),
            "air_purifier",
            "speed",
            SPEEDS[i % len(SPEEDS)],
        )


def add_operation_loop(events, day, device, start_hour, rng, count, gap_minutes=5):
    start = time_at(day, start_hour, rng, jitter_minutes=2)
    actions = ["running", "paused", "running", "idle"]
    for i in range(count):
        add_event(
            events,
            start + timedelta(minutes=i * gap_minutes),
            device,
            "operation",
            actions[i % len(actions)],
        )


def generate_train_events(start_day, train_days, profile, rng):
    events = []
    for offset in range(train_days):
        add_profile_normal_day(
            events,
            start_day + timedelta(days=offset),
            profile,
            rng,
            busy=(rng.random() < 0.12),
        )
    return sorted(events, key=lambda row: row["event_time"])


def generate_test_events(day, profile, case_id, rng):
    events = []
    add_profile_normal_day(
        events,
        day,
        profile,
        rng,
        busy=case_id in {"normal_busy_day"},
    )

    if case_id == "normal_single_night_activity":
        add_fridge_use(events, time_at(day, 2.3, rng, jitter_minutes=4), rng)
    elif case_id == "attention_air_mode_day":
        add_air_mode_loop(events, day, 15.1, rng, count=3, gap_minutes=4)
    elif case_id == "attention_air_speed_day":
        add_air_speed_loop(events, day, 15.4, rng, count=5, gap_minutes=4)
    elif case_id == "attention_ac_temperature_loop_day":
        add_air_conditioner_temperature_loop(events, day, 15.2, rng, count=4, gap_minutes=4)
    elif case_id == "attention_washer_operation_loop_day":
        add_operation_loop(events, day, "washer", 14.7, rng, count=7, gap_minutes=4)
    elif case_id == "borderline_day_fridge_recheck":
        add_fridge_recheck(events, day, 15.4, rng, opens=4, gap_minutes=3)
    elif case_id == "risk_night_fridge_recheck":
        add_fridge_recheck(events, day, 22.25, rng, opens=6, gap_minutes=2)
    elif case_id == "risk_dawn_door_unlock_loop":
        add_door_lock_loop(events, day, 2.15, rng, cycles=4, gap_minutes=3)
    elif case_id == "risk_night_microwave_reuse":
        add_microwave_reuse(events, day, 22.4, rng, count=3, gap_minutes=7)
    elif case_id == "risk_dawn_air_mode_loop":
        add_air_mode_loop(events, day, 2.2, rng, count=8, gap_minutes=4)
        add_air_speed_loop(events, day, 2.28, rng, count=4, gap_minutes=6)
    elif case_id == "risk_dawn_ac_mode_loop":
        add_air_conditioner_mode_loop(events, day, 2.25, rng, count=6, gap_minutes=4)
        add_air_conditioner_temperature_loop(events, day, 2.28, rng, count=5, gap_minutes=4)
    elif case_id == "risk_washer_restart_after_done":
        add_laundry_cycle(events, day, "washer", 22.1, rng, restart_after_done=True)
    elif case_id == "risk_dryer_restart_after_done":
        add_laundry_cycle(events, day, "dryer", 22.2, rng, restart_after_done=True)
    elif case_id == "risk_multi_device_night_loop":
        add_fridge_recheck(events, day, 1.7, rng, opens=5, gap_minutes=3)
        add_air_mode_loop(events, day, 1.85, rng, count=6, gap_minutes=4)

    return sorted(events, key=lambda row: row["event_time"])


def write_standard_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STANDARD_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def profile_for_user(index):
    template = PROFILE_TEMPLATES[index % len(PROFILE_TEMPLATES)].copy()
    cycle = index // len(PROFILE_TEMPLATES)
    if cycle:
        template["profile"] = f"{template['profile']}_v{cycle + 1}"
        template["air_mode_prob"] = min(0.95, template["air_mode_prob"] + cycle * 0.05)
        template["washer_weekly"] = max(0.5, template["washer_weekly"] + (cycle % 3 - 1) * 0.4)
    return template


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/generated/ha_population")
    parser.add_argument("--users", type=int, default=12)
    parser.add_argument("--train-days", type=int, default=21)
    parser.add_argument("--start-date", default="2026-08-01")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    output_dir = resolve_path(args.output_dir)
    start_day = parse_date(args.start_date)
    rng = random.Random(args.seed)

    user_rows = []
    manifest_rows = []
    profiles = []

    for user_index in range(args.users):
        profile = profile_for_user(user_index)
        user_id = f"user_{user_index + 1:03d}"
        user_rng = random.Random(rng.randint(0, 10_000_000))
        user_dir = output_dir / "users" / user_id
        train_csv = user_dir / "train_normal.csv"

        train_events = generate_train_events(start_day, args.train_days, profile, user_rng)
        write_standard_csv(train_csv, train_events)

        user_rows.append({
            "user_id": user_id,
            "profile": profile["profile"],
            "train_days": args.train_days,
            "train_csv": relative_to_base(train_csv),
            "train_event_count": len(train_events),
        })
        profiles.append({"user_id": user_id, **profile})

        test_start = start_day + timedelta(days=args.train_days + 2)
        for case_index, case in enumerate(TEST_CASES):
            case_rng = random.Random(user_rng.randint(0, 10_000_000))
            case_day = test_start + timedelta(days=case_index)
            case_csv = user_dir / "tests" / f"{case['case_id']}.csv"
            test_events = generate_test_events(case_day, profile, case["case_id"], case_rng)
            write_standard_csv(case_csv, test_events)

            manifest_rows.append({
                "user_id": user_id,
                "profile": profile["profile"],
                "case_id": case["case_id"],
                "input_csv": relative_to_base(case_csv),
                "expected_min_level": case["expected_min_level"],
                "expected_max_level": case["expected_max_level"],
                "expected_primary_pattern": case["expected_primary_pattern"],
                "expected_episode_min": case["expected_episode_min"],
                "expected_episode_max": case["expected_episode_max"],
                "event_count": len(test_events),
                "notes": case["notes"],
            })

    write_standard_csv(output_dir / "_placeholder.csv", [])
    (output_dir / "_placeholder.csv").unlink(missing_ok=True)

    users_path = output_dir / "users.csv"
    manifest_path = output_dir / "manifest.csv"
    users_path.parent.mkdir(parents=True, exist_ok=True)

    with users_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=user_rows[0].keys())
        writer.writeheader()
        writer.writerows(user_rows)

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=manifest_rows[0].keys())
        writer.writeheader()
        writer.writerows(manifest_rows)

    with (output_dir / "profiles.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": args.seed,
                "start_date": args.start_date,
                "train_days": args.train_days,
                "users": profiles,
                "test_cases": TEST_CASES,
            },
            f,
            indent=2,
        )

    print(f"generated users: {len(user_rows)}")
    print(f"generated test cases: {len(manifest_rows)}")
    print(f"users file: {users_path}")
    print(f"manifest file: {manifest_path}")


if __name__ == "__main__":
    main()
