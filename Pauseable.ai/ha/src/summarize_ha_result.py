import argparse
import csv
from pathlib import Path

import pandas as pd


ALERT_LEVELS = {"attention", "risk"}
LEVEL_RANK = {"normal": 0, "attention": 1, "risk": 2}

FIELDNAMES = [
    "episode_id",
    "start_time",
    "end_time",
    "duration_minutes",
    "level",
    "max_score",
    "peak_time",
    "primary_pattern",
    "window_count",
    "reasons",
]


def normalize_level(value):
    return str(value or "").strip().lower()


def infer_pattern(row):
    pattern = str(row.get("primary_pattern", "") or "").strip()
    if pattern:
        return pattern

    reasons = str(row.get("reasons", "") or "").lower()
    if "fridge" in reasons:
        return "fridge_repeated_check"
    if "washer" in reasons and "restart" in reasons:
        return "washer_restart_after_done"
    if "dryer" in reasons and "restart" in reasons:
        return "dryer_restart_after_done"
    if "air purifier" in reasons:
        return "air_purifier_repeated_control"
    if "washer" in reasons:
        return "washer_repeated_operation"
    if "dryer" in reasons:
        return "dryer_repeated_operation"
    return "unknown"


def split_reasons(value):
    return [
        normalize_reason(part.strip())
        for part in str(value or "").split(";")
        if part and part.strip()
    ]


def normalize_reason(reason):
    if reason.startswith("sustained attention pattern for "):
        return "sustained attention pattern across consecutive windows"
    return reason


def unique_join(items, limit=6):
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return "; ".join(seen[:limit])


def finish_episode(episode_id, rows):
    start_time = rows[0]["window_end"]
    end_time = rows[-1]["window_end"]
    max_row = max(rows, key=lambda row: int(row["risk_score"]))
    max_level = max(rows, key=lambda row: LEVEL_RANK[row["level"]])["level"]
    duration = int(((end_time - start_time).total_seconds() // 60) + 1)

    reasons = []
    for row in rows:
        reasons.extend(split_reasons(row.get("reasons", "")))

    return {
        "episode_id": episode_id,
        "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_minutes": duration,
        "level": max_level,
        "max_score": int(max_row["risk_score"]),
        "peak_time": max_row["window_end"].strftime("%Y-%m-%d %H:%M:%S"),
        "primary_pattern": max_row["primary_pattern"],
        "window_count": len(rows),
        "reasons": unique_join(reasons),
    }


def summarize(df, max_gap_minutes):
    if df.empty:
        return []

    df = df.copy()
    df["level"] = df["level"].apply(normalize_level)
    df = df[df["level"].isin(ALERT_LEVELS)].copy()
    if df.empty:
        return []

    df["window_end"] = pd.to_datetime(df["window_end"], errors="coerce")
    df["risk_score"] = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0).astype(int)
    df["primary_pattern"] = df.apply(infer_pattern, axis=1)
    df = df.dropna(subset=["window_end"]).sort_values("window_end")

    episodes = []
    current_rows = []
    episode_id = 1
    max_gap_seconds = max_gap_minutes * 60

    for row in df.to_dict("records"):
        if not current_rows:
            current_rows = [row]
            continue

        prev = current_rows[-1]
        gap_seconds = (row["window_end"] - prev["window_end"]).total_seconds()
        same_pattern = row["primary_pattern"] == prev["primary_pattern"]

        if same_pattern and gap_seconds <= max_gap_seconds:
            current_rows.append(row)
        else:
            episodes.append(finish_episode(episode_id, current_rows))
            episode_id += 1
            current_rows = [row]

    if current_rows:
        episodes.append(finish_episode(episode_id, current_rows))

    return episodes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-gap-minutes", type=int, default=2)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    episodes = summarize(df, args.max_gap_minutes)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(episodes)

    print(f"saved: {output_path}")
    print(f"episodes: {len(episodes)}")


if __name__ == "__main__":
    main()
