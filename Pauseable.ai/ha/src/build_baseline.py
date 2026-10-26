import argparse
import json
from pathlib import Path

import pandas as pd


EXCLUDE_COLUMNS = {
    "window_end",
    "risk_score",
    "level",
    "primary_pattern",
    "reasons",
}

TIME_BANDS = {
    "deep_night": (0, 5),
    "morning": (6, 11),
    "afternoon": (12, 17),
    "evening": (18, 20),
    "night": (21, 23),
}


def percentile(series, q):
    return float(series.quantile(q))


def feature_stats(values):
    values = pd.to_numeric(values, errors="coerce").fillna(0)
    q1 = percentile(values, 0.25)
    median = percentile(values, 0.50)
    q3 = percentile(values, 0.75)
    iqr = q3 - q1

    return {
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "min": float(values.min()),
        "max": float(values.max()),
        "q1": q1,
        "median": median,
        "q3": q3,
        "iqr": iqr,
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "upper_iqr_1_0": q3 + 1.0 * iqr,
        "upper_iqr_1_5": q3 + 1.5 * iqr,
        "upper_iqr_2_0": q3 + 2.0 * iqr,
        "nonzero_count": int((values > 0).sum()),
        "nonzero_rate": float((values > 0).mean()),
    }


def learning_status(window_count, observed_day_count):
    if observed_day_count >= 30:
        status = "stable"
    elif observed_day_count >= 14:
        status = "warming_up"
    else:
        status = "cold_start"

    return {
        "status": status,
        "observed_day_count": int(observed_day_count),
        "window_count": int(window_count),
        "rule": "stable after at least 30 observed days; warming_up after 14 days",
    }


def time_band_for_hour(hour):
    hour = int(hour)
    for name, (start, end) in TIME_BANDS.items():
        if start <= hour <= end:
            return name
    return "unknown"


def build_time_band_features(df, feature_columns):
    if "hour" not in df.columns:
        return {}

    with_bands = df.copy()
    with_bands["hour"] = pd.to_numeric(with_bands["hour"], errors="coerce")
    with_bands = with_bands.dropna(subset=["hour"])
    with_bands["time_band"] = with_bands["hour"].astype(int).apply(time_band_for_hour)

    band_features = {}
    behavior_columns = [c for c in feature_columns if c not in {"hour", "is_night"}]
    for band_name in TIME_BANDS:
        subset = with_bands[with_bands["time_band"] == band_name]
        band_features[band_name] = {
            "window_count": int(len(subset)),
            "features": {},
        }
        if subset.empty:
            continue
        for col in behavior_columns:
            band_features[band_name]["features"][col] = feature_stats(subset[col])

    return band_features


def build_baseline(df):
    feature_columns = [c for c in df.columns if c not in EXCLUDE_COLUMNS]
    observed_day_count = 0
    baseline = {
        "version": 2,
        "description": "Personal HA baseline from normal feature windows with quantile and IQR bounds",
        "feature_count": len(feature_columns),
        "window_count": int(len(df)),
        "policy": {
            "recommended_learning_days": 14,
            "stable_learning_days": 30,
            "main_rule": "Use Q1/Q3/IQR with p95/p99/max as supporting statistics",
            "update_rule": "Only normal windows should be used for future baseline updates",
        },
        "features": {},
        "time_band_policy": {
            "enabled": True,
            "bands": {
                name: f"{start:02d}:00-{end:02d}:59"
                for name, (start, end) in TIME_BANDS.items()
            },
            "note": "Time-band statistics are stored for evaluation and later tuning; current infer logic still uses global baseline plus explicit night weights.",
        },
    }

    if "window_end" in df.columns:
        times = pd.to_datetime(df["window_end"], errors="coerce")
        if times.notna().any():
            baseline["observed_start"] = str(times.min())
            baseline["observed_end"] = str(times.max())
            observed_day_count = int(times.dt.date.nunique())

    baseline["learning_status"] = learning_status(
        baseline["window_count"],
        observed_day_count,
    )

    for col in feature_columns:
        baseline["features"][col] = feature_stats(df[col])

    baseline["time_band_features"] = build_time_band_features(df, feature_columns)

    return baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    df = pd.read_csv(input_path)
    baseline = build_baseline(df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)

    print(f"baseline saved: {output_path}")
    print(f"windows: {baseline['window_count']}")
    print(f"features: {baseline['feature_count']}")
    print(f"baseline version: {baseline['version']}")
    print(f"learning status: {baseline['learning_status']['status']}")


if __name__ == "__main__":
    main()
