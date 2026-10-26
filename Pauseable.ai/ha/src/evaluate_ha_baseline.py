import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd


BASE = Path(__file__).resolve().parents[1]
LEVEL_RANK = {"normal": 0, "attention": 1, "risk": 2}
BOOTSTRAP_BASELINE_SCENARIOS = {
    "normal_regular_day",
    "normal_night_single_fridge",
}


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else BASE / path


def run_pipeline(input_csv, prefix, baseline):
    cmd = [
        sys.executable,
        BASE / "src/run_ha_pipeline.py",
        "--input", input_csv,
        "--prefix", prefix,
        "--baseline", baseline,
    ]
    result = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        result.check_returncode()


def run_quiet(cmd):
    result = subprocess.run(
        [str(part) for part in cmd],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        result.check_returncode()


def bootstrap_baseline_if_missing(manifest, baseline_path):
    if baseline_path.exists():
        return

    print(f"baseline not found; bootstrapping demo baseline: {baseline_path}")
    frames = []
    missing = []

    for _, scenario in manifest.iterrows():
        scenario_id = scenario["scenario_id"]
        if scenario_id not in BOOTSTRAP_BASELINE_SCENARIOS:
            continue

        input_csv = str(resolve_path(scenario["input_csv"]))
        prefix = f"bootstrap_{scenario_id}"
        missing_baseline = BASE / "outputs" / "__missing_baseline.json"

        run_quiet([
            sys.executable,
            BASE / "src/run_ha_pipeline.py",
            "--input", input_csv,
            "--prefix", prefix,
            "--baseline", missing_baseline,
        ])

        feature_csv = BASE / "data/features" / f"{prefix}_features.csv"
        if feature_csv.exists():
            frames.append(pd.read_csv(feature_csv))
        else:
            missing.append(str(feature_csv))

    if missing or not frames:
        raise FileNotFoundError(
            "could not bootstrap demo baseline. Missing feature files: "
            + ", ".join(missing)
        )

    feature_path = BASE / "data/features/eval_demo_baseline_features.csv"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_csv(feature_path, index=False)

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    run_quiet([
        sys.executable,
        BASE / "src/build_baseline.py",
        "--input", feature_path,
        "--output", baseline_path,
    ])


def max_level(result_csv):
    df = pd.read_csv(result_csv)
    if df.empty:
        return "normal", 0
    levels = df["level"].astype(str).str.lower()
    actual = max(levels, key=lambda x: LEVEL_RANK.get(x, -1))
    max_score = int(pd.to_numeric(df["risk_score"], errors="coerce").fillna(0).max())
    return actual, max_score


def episode_count(summary_csv):
    if not summary_csv.exists():
        return 0
    return len(pd.read_csv(summary_csv))


def is_pass(expected, actual, ep_count, ep_min, ep_max):
    if LEVEL_RANK[actual] != LEVEL_RANK[expected]:
        return "review"
    if ep_count < ep_min or ep_count > ep_max:
        return "review"
    return "pass"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/raw/baseline_scenarios/manifest.csv")
    parser.add_argument("--baseline", default="models/user_001_real_baseline_v2.json")
    parser.add_argument("--output", default="outputs/baseline_scenario_eval_summary.csv")
    args = parser.parse_args()

    manifest = pd.read_csv(resolve_path(args.manifest))
    baseline_path = resolve_path(args.baseline)
    bootstrap_baseline_if_missing(manifest, baseline_path)
    baseline = str(baseline_path)
    rows = []

    for _, scenario in manifest.iterrows():
        scenario_id = scenario["scenario_id"]
        input_csv = str(resolve_path(scenario["input_csv"]))
        prefix = f"eval_{scenario_id}"

        print(f"running scenario: {scenario_id}")
        run_pipeline(input_csv, prefix, baseline)

        result_csv = BASE / "outputs" / f"{prefix}_result.csv"
        summary_csv = BASE / "outputs" / f"{prefix}_episode_summary.csv"

        actual_level, score = max_level(result_csv)
        episodes = episode_count(summary_csv)
        expected = str(scenario["expected_max_level"]).lower()
        ep_min = int(scenario["expected_episode_min"])
        ep_max = int(scenario["expected_episode_max"])

        rows.append({
            "scenario_id": scenario_id,
            "expected_max_level": expected,
            "actual_max_level": actual_level,
            "max_score": score,
            "episode_count": episodes,
            "result": is_pass(expected, actual_level, episodes, ep_min, ep_max),
            "comment": scenario.get("notes", ""),
        })

    output_path = resolve_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(rows)
    result.to_csv(output_path, index=False)

    print(f"saved: {output_path}")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
