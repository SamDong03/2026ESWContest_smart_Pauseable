
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd


def summarize(frame):
    required = {"household", "start_date", "device_type", "activity"}
    if not required.issubset(frame):
        raise ValueError("Expected MINDER event table, not source/sink transition table")
    frame = frame[list(sorted(required))].copy()
    if frame.isna().any().any():
        raise ValueError("Missing household/time/device values")
    frame["time"] = pd.to_datetime(frame["start_date"], errors="raise")
    if frame["time"].dt.tz is not None:
        raise ValueError("Expected the released naive timestamps; do not silently change timezone")
    frame["activity"] = frame["activity"].astype(str).str.strip().str.lower()
    frame["day"] = frame["time"].dt.normalize()
    frame["hour"] = frame["time"].dt.hour
    histograms, holdout_histograms, diagnostics = [], [], []
    for _, group in frame.groupby("household"):
        days = sorted(group["day"].unique())
        if len(days) < 10:
            continue
        cutoff = pd.Timestamp(days[int(len(days) * .7)])
        train = group[group["day"] < cutoff]
        holdout = group[group["day"] >= cutoff + pd.Timedelta(days=1)]
        fridge = train[train["activity"].eq("fridge door")]
        test_fridge = holdout[holdout["activity"].eq("fridge door")]
        if fridge.empty or test_fridge.empty:
            continue

        hourly = fridge["hour"].value_counts().reindex(range(24), fill_value=0).to_numpy(dtype=float)
        test_hourly = test_fridge["hour"].value_counts().reindex(range(24), fill_value=0).to_numpy(dtype=float)
        histograms.append(hourly / hourly.sum())
        holdout_histograms.append(test_hourly / test_hourly.sum())
        daily = fridge.groupby("day").size()
        diagnostics.append({"fit_days_with_any_sensor": train["day"].nunique(),
                            "holdout_days_with_any_sensor": holdout["day"].nunique(),
                            "fridge_recorded_events_per_active_day_median": float(daily.median())})
    if not histograms:
        raise ValueError("No household has sufficient fit and holdout fridge events")
    weights = np.mean(histograms, axis=0)
    holdout_weights = np.mean(holdout_histograms, axis=0)
    return {"source_type": "public", "production_eligible": False, "clinical_ground_truth": False,
            "source_url": "https://github.com/NVFL/Markov-Chain-Model",
            "rows": len(frame), "households_used": len(histograms),
            "record_categories": frame["activity"].value_counts().to_dict(),
            "sensor_categories": frame["device_type"].value_counts().to_dict(),
            "exact_key_duplicate_rows_retained": int(frame.duplicated(["household", "start_date", "device_type", "activity"]).sum()),
            "fridge_hour_weights": weights.tolist(),
            "holdout_hour_total_variation": float(np.abs(weights - holdout_weights).sum() / 2),
            "median_household_fridge_events_per_active_day": float(np.median([d["fridge_recorded_events_per_active_day_median"] for d in diagnostics])),
            "split": "First 70% of observed days per household; next calendar day purged; remaining days untouched for drift comparison",
            "weighting": "Each eligible household contributes one normalized hourly distribution",
            "used_by_simulator": "Only hour-of-day sampling for scenario start; NOT counts, open duration, clinical labels or production baseline",
            "limitations": ["Dementia/MCI cohort with possible co-occupant events, not a normal-labelled cohort.",
                            "Recorded event counts are not measured fridge opening counts; timezone is unspecified.",
                            "Observed/active days are not proof of continuous sensor coverage.",
                            "No raw rows or household identifiers exported; aggregates are not a formal privacy guarantee.",
                            "Oven-use is not mapped to microwave. No patient records copied into synthetic events."]}


def profile_archive(path):
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        candidates = [n for n in archive.namelist() if n.endswith(".csv")
                      and not n.startswith("__MACOSX/") and not Path(n).name.startswith("._")]
        if len(candidates) != 1:
            raise ValueError("Expected exactly one event CSV in the ZIP")
        with archive.open(candidates[0]) as stream:
            frame = pd.read_csv(stream, usecols=["household", "start_date", "device_type", "activity"])
    result = summarize(frame)
    with path.open("rb") as stream:
        result["archive_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-zip", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = profile_archive(args.input_zip)
    destination = Path(args.output)
    if destination.exists():
        parser.error("Use a new output path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
