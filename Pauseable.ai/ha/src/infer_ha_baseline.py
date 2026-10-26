import argparse
import csv
import json
import math
from pathlib import Path

import pandas as pd


SKIP_FEATURES = {
    "hour",
    "is_night",
    "air_purifier_mode_event_count_30m",
    "air_purifier_mode_event_count_1h",
    "air_purifier_speed_event_count_30m",
    "air_purifier_speed_event_count_1h",
    "microwave_night_start_count_1h",
    "air_conditioner_temperature_event_count_30m",
    "air_conditioner_temperature_event_count_1h",
}

MIN_MEANINGFUL_COUNTS = {
    "fridge_door_open_count_10m": 4,
    "fridge_door_open_count_30m": 5,
    "fridge_door_open_count_1h": 7,
    "fridge_door_toggle_count_10m": 6,
    "fridge_door_toggle_count_30m": 8,
    "fridge_door_toggle_count_1h": 12,
    "fridge_night_open_count_1h": 5,
    "washer_operation_change_count_30m": 5,
    "washer_operation_change_count_1h": 6,
    "washer_start_count_2h": 3,
    "washer_done_to_restart_count_2h": 1,
    "dryer_operation_change_count_30m": 4,
    "dryer_operation_change_count_1h": 4,
    "dryer_start_count_2h": 3,
    "dryer_done_to_restart_count_2h": 1,
    "air_purifier_power_toggle_count_30m": 2,
    "air_purifier_mode_change_count_30m": 3,
    "air_purifier_speed_change_count_30m": 3,
    "air_purifier_mode_change_count_1h": 3,
    "air_purifier_speed_change_count_1h": 3,
    "air_purifier_mode_event_count_30m": 3,
    "air_purifier_mode_event_count_1h": 3,
    "air_purifier_speed_event_count_30m": 3,
    "air_purifier_speed_event_count_1h": 3,
    "door_lock_unlock_count_10m": 2,
    "door_lock_unlock_count_30m": 3,
    "door_lock_unlock_count_1h": 3,
    "door_lock_lock_toggle_count_10m": 3,
    "door_lock_lock_toggle_count_30m": 4,
    "door_lock_lock_toggle_count_1h": 5,
    "door_lock_night_unlock_count_1h": 2,
    "microwave_start_count_10m": 2,
    "microwave_start_count_30m": 2,
    "microwave_start_count_1h": 2,
    "microwave_night_start_count_1h": 1,
    "microwave_operation_change_count_30m": 3,
    "microwave_operation_change_count_1h": 4,
    "air_conditioner_power_toggle_count_30m": 2,
    "air_conditioner_mode_change_count_30m": 3,
    "air_conditioner_mode_change_count_1h": 3,
    "air_conditioner_temperature_change_count_30m": 3,
    "air_conditioner_temperature_change_count_1h": 3,
    "air_conditioner_temperature_event_count_30m": 3,
    "air_conditioner_temperature_event_count_1h": 3,
}


def as_float(value, default=0.0):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def row_value(row, name):
    return as_float(row.get(name, 0))


def stat_value(stats, name, default=0.0):
    return as_float(stats.get(name, default), default)


def min_meaningful_count(name):
    if name in MIN_MEANINGFUL_COUNTS:
        return MIN_MEANINGFUL_COUNTS[name]
    if "done_to_restart" in name:
        return 1
    if "toggle_count" in name or "change_count" in name:
        return 3
    if "open_count" in name or "start_count" in name:
        return 2
    return 1


def robust_limit(stats, iqr_key, quantile_key):
    return max(stat_value(stats, iqr_key), stat_value(stats, quantile_key))


def baseline_count_limit(baseline, name, stat_name, hard_min, add=0):
    stats = baseline.get("features", {}).get(name, {})
    return max(hard_min, math.floor(stat_value(stats, stat_name)) + add)


def pattern_for_feature(name):
    if name.startswith("fridge_"):
        return "fridge_repeated_check"
    if name.startswith("washer_"):
        if "done_to_restart" in name:
            return "washer_restart_after_done"
        return "washer_repeated_operation"
    if name.startswith("dryer_"):
        if "done_to_restart" in name:
            return "dryer_restart_after_done"
        return "dryer_repeated_operation"
    if name.startswith("dishwasher_"):
        if "done_to_restart" in name:
            return "dishwasher_restart_after_done"
        return "dishwasher_repeated_operation"
    if name.startswith("air_purifier_"):
        return "air_purifier_repeated_control"
    if name.startswith("door_lock_"):
        return "door_lock_repeated_unlock"
    if name.startswith("microwave_"):
        return "microwave_repeated_use"
    if name.startswith("air_conditioner_"):
        return "air_conditioner_repeated_control"
    return "feature_anomaly"


def score_feature(name, value, stats):
    if value < min_meaningful_count(name):
        return 0, ""

    mild = robust_limit(stats, "upper_iqr_1_0", "p90")
    strong = robust_limit(stats, "upper_iqr_1_5", "p95")
    extreme = robust_limit(stats, "upper_iqr_2_0", "p99")

    if value > extreme:
        return 14, f"{name}={value:g} above IQR x2.0 / p99 bound ({extreme:g})"
    if value > strong:
        return 9, f"{name}={value:g} above IQR x1.5 / p95 bound ({strong:g})"
    if value > mild:
        return 5, f"{name}={value:g} above IQR x1.0 / p90 bound ({mild:g})"
    return 0, ""


def night_bonus(row):
    hour = int(row_value(row, "hour"))
    is_night = int(row_value(row, "is_night"))

    if 0 <= hour < 5:
        return 12, "deep night context"
    if is_night or hour >= 21 or hour < 6:
        return 8, "night-time context"
    return 0, ""


def infer_row(row, baseline):
    score = 0
    reasons = []
    pattern_scores = {}
    strong_conditions = 0

    def add(points, pattern, reason, strong=False):
        nonlocal score, strong_conditions
        score += points
        pattern_scores[pattern] = pattern_scores.get(pattern, 0) + points
        if strong:
            strong_conditions += 1
        if reason:
            reasons.append(reason)

    features = baseline.get("features", {})
    for name, stats in features.items():
        if name in SKIP_FEATURES:
            continue
        value = row_value(row, name)
        points, reason = score_feature(name, value, stats)
        if points:
            add(points, pattern_for_feature(name), reason, strong=points >= 14)

    fridge_open_10m = row_value(row, "fridge_door_open_count_10m")
    fridge_open_30m = row_value(row, "fridge_door_open_count_30m")
    fridge_toggle_10m = row_value(row, "fridge_door_toggle_count_10m")
    fridge_toggle_30m = row_value(row, "fridge_door_toggle_count_30m")
    fridge_night_1h = row_value(row, "fridge_night_open_count_1h")

    fridge_open_limit = baseline_count_limit(
        baseline, "fridge_door_open_count_10m", "p95", hard_min=4, add=1
    )
    fridge_toggle_limit = baseline_count_limit(
        baseline, "fridge_door_toggle_count_10m", "p95", hard_min=6, add=1
    )
    fridge_short_burst = (
        fridge_open_10m >= fridge_open_limit
        and fridge_toggle_10m >= fridge_toggle_limit
    )
    fridge_sustained = (
        fridge_open_30m >= 5
        or fridge_toggle_30m >= 8
        or fridge_night_1h >= 5
    )

    if fridge_short_burst:
        add(
            25,
            "fridge_repeated_check",
            "fridge door repeated in a short 10-minute window",
            strong=True,
        )
        if fridge_sustained:
            add(
                12,
                "fridge_repeated_check",
                "fridge repetition also persists across 30-minute or 1-hour features",
                strong=True,
            )

    air_mode_30m = row_value(row, "air_purifier_mode_change_count_30m")
    air_mode_1h = row_value(row, "air_purifier_mode_change_count_1h")
    air_speed_30m = row_value(row, "air_purifier_speed_change_count_30m")
    air_speed_1h = row_value(row, "air_purifier_speed_change_count_1h")
    air_power_30m = row_value(row, "air_purifier_power_toggle_count_30m")
    air_mode_event_30m = row_value(row, "air_purifier_mode_event_count_30m")
    air_mode_event_1h = row_value(row, "air_purifier_mode_event_count_1h")
    air_speed_event_30m = row_value(row, "air_purifier_speed_event_count_30m")
    air_speed_event_1h = row_value(row, "air_purifier_speed_event_count_1h")

    air_mode_limit = baseline_count_limit(
        baseline, "air_purifier_mode_change_count_30m", "p95", hard_min=3, add=1
    )
    air_speed_limit = baseline_count_limit(
        baseline, "air_purifier_speed_change_count_30m", "p95", hard_min=3, add=1
    )

    if air_mode_30m >= air_mode_limit and air_mode_1h >= 3:
        add(
            30,
            "air_purifier_repeated_control",
            "air purifier mode changed repeatedly across 30-minute and 1-hour features",
            strong=True,
        )
        if air_mode_30m >= 5 or air_mode_1h >= 5:
            add(
                15,
                "air_purifier_repeated_control",
                "air purifier mode repetition is sustained",
                strong=True,
            )

    if air_mode_event_30m >= 3 and air_mode_event_1h >= 3 and air_mode_30m < air_mode_limit:
        add(
            35,
            "air_purifier_repeated_control",
            "air purifier mode was operated several times, but change count stayed borderline",
        )

    if air_speed_30m >= air_speed_limit and air_speed_1h >= 3:
        add(
            25,
            "air_purifier_repeated_control",
            "air purifier speed changed repeatedly across 30-minute and 1-hour features",
            strong=True,
        )

    if air_speed_event_30m >= 3 and air_speed_event_1h >= 3 and air_speed_30m < air_speed_limit:
        add(
            30,
            "air_purifier_repeated_control",
            "air purifier speed was operated several times, but change count stayed borderline",
        )

    if air_power_30m >= 3:
        add(
            20,
            "air_purifier_repeated_control",
            "air purifier power toggled repeatedly",
            strong=True,
        )

    door_unlock_10m = row_value(row, "door_lock_unlock_count_10m")
    door_unlock_30m = row_value(row, "door_lock_unlock_count_30m")
    door_toggle_10m = row_value(row, "door_lock_lock_toggle_count_10m")
    door_toggle_30m = row_value(row, "door_lock_lock_toggle_count_30m")
    door_night_1h = row_value(row, "door_lock_night_unlock_count_1h")

    door_unlock_limit = baseline_count_limit(
        baseline, "door_lock_unlock_count_10m", "p95", hard_min=2, add=1
    )
    door_toggle_limit = baseline_count_limit(
        baseline, "door_lock_lock_toggle_count_10m", "p95", hard_min=3, add=1
    )

    if door_unlock_10m >= door_unlock_limit and door_toggle_10m >= door_toggle_limit:
        add(
            28,
            "door_lock_repeated_unlock",
            "door lock was unlocked and locked repeatedly in a short 10-minute window",
            strong=True,
        )
        if door_unlock_30m >= 3 or door_toggle_30m >= 4:
            add(
                14,
                "door_lock_repeated_unlock",
                "door lock repetition also persists across the 30-minute feature",
                strong=True,
            )

    if door_night_1h >= 2:
        add(
            26,
            "door_lock_repeated_unlock",
            "door lock was unlocked repeatedly during night-time",
            strong=True,
        )

    microwave_start_30m = row_value(row, "microwave_start_count_30m")
    microwave_start_1h = row_value(row, "microwave_start_count_1h")
    microwave_night_1h = row_value(row, "microwave_night_start_count_1h")
    microwave_change_30m = row_value(row, "microwave_operation_change_count_30m")

    if microwave_night_1h >= 1:
        add(
            20,
            "microwave_repeated_use",
            "microwave was used during night-time",
        )

    if microwave_start_1h >= 2 and microwave_change_30m >= 3:
        add(
            28,
            "microwave_repeated_use",
            "microwave was started repeatedly with several operation changes",
            strong=True,
        )

    if microwave_start_30m >= 2:
        add(
            16,
            "microwave_repeated_use",
            "microwave was started more than once within 30 minutes",
        )

    aircon_power_30m = row_value(row, "air_conditioner_power_toggle_count_30m")
    aircon_mode_30m = row_value(row, "air_conditioner_mode_change_count_30m")
    aircon_mode_1h = row_value(row, "air_conditioner_mode_change_count_1h")
    aircon_temp_30m = row_value(row, "air_conditioner_temperature_change_count_30m")
    aircon_temp_1h = row_value(row, "air_conditioner_temperature_change_count_1h")

    aircon_mode_limit = baseline_count_limit(
        baseline, "air_conditioner_mode_change_count_30m", "p95", hard_min=3, add=1
    )
    aircon_temp_limit = baseline_count_limit(
        baseline, "air_conditioner_temperature_change_count_30m", "p95", hard_min=3, add=1
    )

    if aircon_mode_30m >= aircon_mode_limit and aircon_mode_1h >= 3:
        add(
            26,
            "air_conditioner_repeated_control",
            "air conditioner mode changed repeatedly across 30-minute and 1-hour features",
            strong=True,
        )

    if aircon_temp_30m >= aircon_temp_limit and aircon_temp_1h >= 3:
        add(
            26,
            "air_conditioner_repeated_control",
            "air conditioner target temperature changed repeatedly across 30-minute and 1-hour features",
            strong=True,
        )

    if aircon_power_30m >= 3:
        add(
            20,
            "air_conditioner_repeated_control",
            "air conditioner power toggled repeatedly",
            strong=True,
        )

    if aircon_mode_30m >= 3 and aircon_temp_30m >= 3:
        add(
            14,
            "air_conditioner_repeated_control",
            "air conditioner mode and temperature were both changed repeatedly",
            strong=True,
        )

    for device in ("washer", "dryer", "dishwasher"):
        restart_2h = row_value(row, f"{device}_done_to_restart_count_2h")
        start_2h = row_value(row, f"{device}_start_count_2h")
        change_30m = row_value(row, f"{device}_operation_change_count_30m")
        change_1h = row_value(row, f"{device}_operation_change_count_1h")

        restart_pattern = f"{device}_restart_after_done"
        repeated_pattern = f"{device}_repeated_operation"

        if restart_2h >= 1:
            add(
                35,
                restart_pattern,
                f"{device} restarted after a done state within 2 hours",
                strong=True,
            )
            if start_2h >= 2:
                add(
                    12,
                    restart_pattern,
                    f"{device} has multiple starts in 2 hours",
                    strong=True,
                )
            if restart_2h >= 2:
                add(
                    20,
                    restart_pattern,
                    f"{device} restarted after done more than once",
                    strong=True,
                )

        change_30m_limit = baseline_count_limit(
            baseline, f"{device}_operation_change_count_30m", "p95", hard_min=4, add=1
        )
        change_1h_limit = baseline_count_limit(
            baseline, f"{device}_operation_change_count_1h", "p95", hard_min=4, add=1
        )
        if change_30m >= change_30m_limit and change_1h >= change_1h_limit:
            add(
                25,
                repeated_pattern,
                f"{device} operation state changed repeatedly across 30-minute and 1-hour features",
                strong=True,
            )

    if score > 0:
        points, reason = night_bonus(row)
        if points:
            score += points
            reasons.append(reason)

    score = min(int(round(score)), 100)

    if pattern_scores:
        primary_pattern = max(pattern_scores.items(), key=lambda item: item[1])[0]
    else:
        primary_pattern = ""

    if score >= 70 or (strong_conditions >= 2 and score >= 60):
        level = "risk"
        score = max(score, 70)
    elif score >= 35:
        level = "attention"
    else:
        level = "normal"

    return {
        "window_end": row["window_end"],
        "risk_score": score,
        "level": level,
        "primary_pattern": primary_pattern,
        "reasons": "; ".join(dict.fromkeys(reasons)),
        "_strong_conditions": strong_conditions,
    }


def infer_dataframe(df, baseline):
    rows = []
    last_alert_time = None
    last_pattern = None
    run_count = 0

    for _, row in df.iterrows():
        result = infer_row(row, baseline)
        current_time = pd.to_datetime(result["window_end"], errors="coerce")
        is_alert = result["level"] != "normal"
        same_pattern = result["primary_pattern"] == last_pattern
        close_to_last = (
            last_alert_time is not None
            and pd.notna(current_time)
            and (current_time - last_alert_time).total_seconds() <= 120
        )

        if is_alert:
            if same_pattern and close_to_last:
                run_count += 1
            else:
                run_count = 1

            if (
                result["level"] == "attention"
                and run_count >= 4
                and result["risk_score"] >= 45
            ):
                result["level"] = "risk"
                result["risk_score"] = max(result["risk_score"], 70)
                sustained_reason = (
                    f"sustained attention pattern for {run_count} consecutive windows"
                )
                result["reasons"] = "; ".join(
                    [part for part in [result["reasons"], sustained_reason] if part]
                )

            last_alert_time = current_time
            last_pattern = result["primary_pattern"]
        else:
            last_alert_time = None
            last_pattern = None
            run_count = 0

        result.pop("_strong_conditions", None)
        rows.append(result)

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.features)
    with open(args.baseline, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = infer_dataframe(df, baseline)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "window_end",
                "risk_score",
                "level",
                "primary_pattern",
                "reasons",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"saved: {output_path}")
    if rows:
        print(pd.DataFrame(rows)["level"].value_counts().to_string())
    else:
        print("level")
        print("(no feature rows)")


if __name__ == "__main__":
    main()
