
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random

import pandas as pd

REGISTRY = Path(__file__).resolve().parents[1] / "deploy/research/evidence.json"
FIELDS = ["event_time", "device_type", "signal_type", "action", "entity_id", "record_type"]
PAIRS = [("fridge_recheck", "normal_meal_prep"), ("microwave_restart", "normal_batch_cooking"),
         ("washer_power_recheck", "normal_washer_setup")]


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def scenario(case_id, intensity="medium", seed=42, hour=12, day=0):
    registry = load_registry()
    spec = next((s for s in registry["scenarios"] if s["id"] == case_id), None)
    if spec is None or intensity not in registry["parameters"]["count_by_intensity"]:
        raise ValueError("Unknown scenario or intensity")
    if not 0 <= hour <= 23 or day < 0:
        raise ValueError("Invalid clock context")
    params = registry["parameters"]
    rng = random.Random(seed)
    at = datetime(2026, 4, 1) + timedelta(days=day, hours=hour)
    if case_id == "normal_night_snack":
        at = at.replace(hour=2)
    count = params["count_by_intensity"][intensity]
    rows = []

    def emit(when, device, signal, action, snapshot=False):
        rows.append(dict(zip(FIELDS, [when.isoformat(), device, signal, action,
                                     f"research.{device}_{signal}",
                                     "state_snapshot" if snapshot else "state_changed_event"])))

    def fridge(when, seconds=2):
        emit(when, "fridge", "door", "open")
        emit(when + timedelta(seconds=seconds), "fridge", "door", "close")

    def microwave(when, seconds=90):
        emit(when, "microwave", "operation", "running")
        emit(when + timedelta(seconds=seconds), "microwave", "operation", "done")
        emit(when + timedelta(seconds=seconds + 1), "microwave", "operation", "idle")


    origin = at - timedelta(hours=2)
    emit(origin, "fridge", "door", "close", True)
    emit(origin, "microwave", "operation", "idle", True)
    if case_id.startswith("washer_") or case_id.startswith("normal_washer"):
        emit(origin, "washer", "operation", "idle", True)
    if case_id in ("fridge_recheck", "normal_meal_prep"):
        current = at
        for _ in range(count):
            fridge(current, rng.randint(*params["fridge_open_seconds"]))
            current += timedelta(seconds=rng.randint(*params["fridge_gap_seconds"]))
    elif case_id in ("microwave_restart", "normal_batch_cooking", "caregiver_visit"):
        current = at
        for _ in range(max(2, count // 2)):
            fridge(current)
            duration = rng.randint(*params["microwave_run_seconds"])
            microwave(current + timedelta(seconds=10), duration)
            current += timedelta(seconds=duration + 11 + rng.randint(*params["microwave_idle_gap_seconds"]))
    elif case_id == "task_omission":
        fridge(at)
    elif case_id == "prolonged_heating":
        fridge(at)
        microwave(at + timedelta(seconds=10), 20 * 60)
    elif case_id == "sensor_dropout":
        emit(at, "fridge", "door", "open")
    elif case_id == "fridge_distributed_rechecks":
        for index in range(count):
            fridge(at + timedelta(minutes=index * params["distributed_fridge_gap_minutes"]))
    elif case_id == "normal_slow_meal":
        for minute in (0, 20, 40):
            fridge(at + timedelta(minutes=minute))
        microwave(at + timedelta(minutes=55))
    elif case_id in ("washer_power_recheck", "normal_washer_setup"):
        current = at
        for _ in range(count):
            duration = rng.randint(*params["washer_power_on_seconds"])
            emit(current, "washer", "operation", "running")
            emit(current + timedelta(seconds=duration), "washer", "operation", "idle")
            current += timedelta(seconds=duration + rng.randint(*params["washer_setup_gap_seconds"]))
    elif case_id == "normal_washer_full_cycle":
        emit(at, "washer", "operation", "running")
        done = at + timedelta(minutes=params["washer_cycle_minutes"])
        emit(done, "washer", "operation", "done")
        emit(done + timedelta(seconds=1), "washer", "operation", "idle")
    else:
        fridge(at)
        microwave(at + timedelta(seconds=10))
    rows.sort(key=lambda row: row["event_time"])
    if case_id == "sensor_duplicate":
        rows = [dict(row) for row in rows for _ in range(3)]
    frame = pd.DataFrame(rows, columns=FIELDS)
    meta = {**spec, "seed": seed, "intensity": intensity, "source_type": "synthetic",
            "production_eligible": False, "diagnosis": None, "clinical_ground_truth": False,
            "history_complete": int(case_id != "sensor_dropout"),
            "observation_start": origin.isoformat(), "assessment_start": at.isoformat(),
            "assessment_end": (at + timedelta(minutes=params["distributed_assessment_minutes"]
                               if case_id in {"fridge_distributed_rechecks", "normal_slow_meal", "normal_washer_full_cycle"}
                               else params["assessment_minutes"])).isoformat(),
            "signal_semantics": ("power_toggles_adapted_to_operation" if case_id in
                                 {"washer_power_recheck", "normal_washer_setup"} else "simulated_physical_state"),
            "parameter_basis": params["basis"],
            "event_sha256": hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()}
    return frame, meta


def choose_hour(seed, reference=None):
    rng = random.Random(seed)
    if reference is None:
        return rng.choice([7, 12, 18, 21])
    weights = reference["fridge_hour_weights"]
    if len(weights) != 24 or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("Invalid hourly reference")
    return rng.choices(range(24), weights=weights, k=1)[0]


def summarize_observation(events):
    pass
    durations, unresolved = {}, {}
    for (_, signal), group in events.drop_duplicates().groupby(["entity_id", "signal_type"]):
        previous, began = None, None
        for row in group.sort_values("event_time").to_dict("records"):
            action = row["action"]
            when = datetime.fromisoformat(row["event_time"])
            if action == previous:
                continue
            if began is not None:
                durations.setdefault(f"{row['device_type']}_{previous}_seconds", []).append(
                    (when - began).total_seconds())
            previous = action
            began = when if row["record_type"] != "state_snapshot" and action in {"open", "running"} else None
        if began is not None:
            unresolved[f"{group.iloc[0]['device_type']}_{signal}"] = True
    return {"completed_state_durations_seconds": durations, "unclosed_observed_states": sorted(unresolved),
            "purpose": "Research diagnostics only; durations are not new IF/AE model inputs",
            "clinical_ground_truth": False}
