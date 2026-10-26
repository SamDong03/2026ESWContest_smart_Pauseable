import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE = Path(__file__).resolve().parents[1]
LEVEL_RANK = {"normal": 0, "attention": 1, "risk": 2}
VALIDITY_NOTES = {
    "what_this_validates": [
        "The pipeline runs end-to-end for many personalized baselines.",
        "Normal profile variation can be checked for false alarms.",
        "Injected repeated-control scenarios can be checked for detection recall.",
        "Episode grouping can be checked across many users instead of one demo case.",
    ],
    "what_this_does_not_prove": [
        "It does not prove clinical dementia diagnosis performance.",
        "It does not replace real long-term user data.",
        "It does not prove the synthetic event rates match every household.",
        "It does not validate mmWave and HA fusion yet.",
    ],
    "how_to_strengthen_evidence": [
        "Collect at least 14-30 days of real normal data per target user.",
        "Keep attention/risk windows out of baseline updates until reviewed.",
        "Run sensitivity tests with multiple seeds, user counts, and train-day lengths.",
        "Compare rule-only results against AutoEncoder-assisted results later.",
        "Report false-positive rate on normal synthetic and real self-check data.",
    ],
}


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else BASE / path


def command_text(cmd):
    return " ".join(str(part) for part in cmd)


def run_quiet(cmd, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(part) for part in cmd],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        print(result.stdout)
        raise RuntimeError(f"command failed: {command_text(cmd)}")


def ensure_generated(args):
    generated_dir = resolve_path(args.generated_dir)
    manifest_path = generated_dir / "manifest.csv"
    users_path = generated_dir / "users.csv"

    if args.skip_generate and manifest_path.exists() and users_path.exists():
        return manifest_path, users_path

    if args.skip_generate and (not manifest_path.exists() or not users_path.exists()):
        raise FileNotFoundError(
            "--skip-generate was set, but generated manifest/users files are missing"
        )

    cmd = [
        sys.executable,
        BASE / "src/generate_ha_population_scenarios.py",
        "--output-dir",
        generated_dir,
        "--users",
        args.users,
        "--train-days",
        args.train_days,
        "--start-date",
        args.start_date,
        "--seed",
        args.seed,
    ]
    run_quiet(cmd, resolve_path(args.output_dir) / "logs/generate_population.log")
    return manifest_path, users_path


def max_level(result_csv):
    df = pd.read_csv(result_csv)
    if df.empty:
        return "normal", 0, 0, ""

    levels = df["level"].astype(str).str.lower()
    actual = max(levels, key=lambda x: LEVEL_RANK.get(x, -1))
    scores = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0)
    alert_rows = df[levels.isin(["attention", "risk"])]
    patterns = sorted(
        {
            str(value)
            for value in alert_rows.get("primary_pattern", pd.Series(dtype=str)).fillna("")
            if str(value)
        }
    )

    return actual, int(scores.max()), int(len(alert_rows)), "|".join(patterns)


def episode_summary(summary_csv):
    if not summary_csv.exists():
        return 0, "", ""
    df = pd.read_csv(summary_csv)
    if df.empty:
        return 0, "", ""
    patterns = sorted({str(value) for value in df["primary_pattern"].fillna("") if str(value)})
    max_episode_level = max(
        df["level"].astype(str).str.lower(),
        key=lambda x: LEVEL_RANK.get(x, -1),
    )
    return int(len(df)), "|".join(patterns), max_episode_level


def classify_case(row, actual_level, episode_count, patterns):
    expected_min = str(row["expected_min_level"]).lower()
    expected_max = str(row["expected_max_level"]).lower()
    expected_pattern_value = row.get("expected_primary_pattern", "")
    expected_pattern = "" if pd.isna(expected_pattern_value) else str(expected_pattern_value)
    ep_min = int(row["expected_episode_min"])
    ep_max = int(row["expected_episode_max"])

    actual_rank = LEVEL_RANK.get(actual_level, -1)
    if actual_rank < LEVEL_RANK[expected_min]:
        return "missed"
    if actual_rank > LEVEL_RANK[expected_max]:
        return "over_alert"
    if episode_count < ep_min or episode_count > ep_max:
        return "episode_mismatch"
    if (
        expected_pattern
        and actual_level != "normal"
        and expected_pattern not in patterns.split("|")
    ):
        return "pattern_mismatch"
    return "pass"


def summarize_user(group):
    total = len(group)
    normal = group[group["expected_max_level"] == "normal"]
    attention_or_more = group[
        group["expected_min_level"].map(lambda x: LEVEL_RANK[x]) >= LEVEL_RANK["attention"]
    ]
    risk = group[group["expected_min_level"] == "risk"]

    false_alarms = normal[
        normal["actual_max_level"].map(lambda x: LEVEL_RANK[x]) > LEVEL_RANK["normal"]
    ]
    detected_attention = attention_or_more[
        attention_or_more["actual_max_level"].map(lambda x: LEVEL_RANK[x])
        >= LEVEL_RANK["attention"]
    ]
    detected_risk = risk[
        risk["actual_max_level"].map(lambda x: LEVEL_RANK[x]) >= LEVEL_RANK["risk"]
    ]

    return pd.Series({
        "case_count": total,
        "pass_count": int((group["result"] == "pass").sum()),
        "review_count": int((group["result"] != "pass").sum()),
        "normal_case_count": int(len(normal)),
        "normal_false_alarm_count": int(len(false_alarms)),
        "attention_or_risk_case_count": int(len(attention_or_more)),
        "attention_or_risk_detected_count": int(len(detected_attention)),
        "risk_case_count": int(len(risk)),
        "risk_detected_count": int(len(detected_risk)),
    })


def safe_rate(numerator, denominator):
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def build_user_summary(case_df):
    rows = []
    for (user_id, profile), group in case_df.groupby(["user_id", "profile"]):
        summary = summarize_user(group).to_dict()
        rows.append({"user_id": user_id, "profile": profile, **summary})
    return pd.DataFrame(rows)


def build_overall_summary(case_df, user_df, args):
    normal = case_df[case_df["expected_max_level"] == "normal"]
    attention_or_more = case_df[
        case_df["expected_min_level"].map(lambda x: LEVEL_RANK[x]) >= LEVEL_RANK["attention"]
    ]
    risk = case_df[case_df["expected_min_level"] == "risk"]
    false_alarms = normal[
        normal["actual_max_level"].map(lambda x: LEVEL_RANK[x]) > LEVEL_RANK["normal"]
    ]
    attention_detected = attention_or_more[
        attention_or_more["actual_max_level"].map(lambda x: LEVEL_RANK[x])
        >= LEVEL_RANK["attention"]
    ]
    risk_detected = risk[
        risk["actual_max_level"].map(lambda x: LEVEL_RANK[x]) >= LEVEL_RANK["risk"]
    ]

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "users": int(args.users),
        "train_days": int(args.train_days),
        "seed": int(args.seed),
        "case_count": int(len(case_df)),
        "pass_count": int((case_df["result"] == "pass").sum()),
        "review_count": int((case_df["result"] != "pass").sum()),
        "pass_rate": safe_rate(int((case_df["result"] == "pass").sum()), len(case_df)),
        "normal_case_count": int(len(normal)),
        "normal_false_alarm_count": int(len(false_alarms)),
        "normal_false_alarm_rate": safe_rate(len(false_alarms), len(normal)),
        "attention_or_risk_case_count": int(len(attention_or_more)),
        "attention_or_risk_detected_count": int(len(attention_detected)),
        "attention_or_risk_detection_rate": safe_rate(
            len(attention_detected),
            len(attention_or_more),
        ),
        "risk_case_count": int(len(risk)),
        "risk_detected_count": int(len(risk_detected)),
        "risk_recall": safe_rate(len(risk_detected), len(risk)),
        "profiles": sorted(user_df["profile"].unique().tolist()),
        "validity_notes": VALIDITY_NOTES,
    }


def write_markdown_report(path, overall, review_rows):
    lines = [
        "# HA Population Baseline Validation Report",
        "",
        "## Summary",
        "",
        f"- Users: {overall['users']}",
        f"- Train days per user: {overall['train_days']}",
        f"- Test cases: {overall['case_count']}",
        f"- Pass rate: {overall['pass_rate']}",
        f"- Normal false alarm rate: {overall['normal_false_alarm_rate']}",
        f"- Attention/risk detection rate: {overall['attention_or_risk_detection_rate']}",
        f"- Risk recall: {overall['risk_recall']}",
        "",
        "## What This Validates",
        "",
    ]
    lines.extend(f"- {item}" for item in VALIDITY_NOTES["what_this_validates"])
    lines.extend(["", "## What This Does Not Prove", ""])
    lines.extend(f"- {item}" for item in VALIDITY_NOTES["what_this_does_not_prove"])
    lines.extend(["", "## How To Strengthen Evidence", ""])
    lines.extend(f"- {item}" for item in VALIDITY_NOTES["how_to_strengthen_evidence"])

    lines.extend(["", "## Review Items", ""])
    if review_rows.empty:
        lines.append("- No review items in this run.")
    else:
        for _, row in review_rows.head(30).iterrows():
            lines.append(
                "- "
                f"{row['user_id']} / {row['profile']} / {row['case_id']}: "
                f"expected {row['expected_min_level']}-{row['expected_max_level']}, "
                f"actual {row['actual_max_level']}, result {row['result']}"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-dir", default="data/generated/ha_population")
    parser.add_argument("--output-dir", default="outputs/ha_population_validation")
    parser.add_argument("--users", type=int, default=12)
    parser.add_argument("--train-days", type=int, default=21)
    parser.add_argument("--start-date", default="2026-08-01")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--limit-users", type=int)
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--feature-script", default="src/make_ha_features_fast.py")
    args = parser.parse_args()

    output_dir = resolve_path(args.output_dir)
    feature_dir = output_dir / "features"
    model_dir = output_dir / "models"
    result_dir = output_dir / "results"
    summary_dir = output_dir / "episodes"
    log_dir = output_dir / "logs"
    for path in [feature_dir, model_dir, result_dir, summary_dir, log_dir]:
        path.mkdir(parents=True, exist_ok=True)

    manifest_path, users_path = ensure_generated(args)
    users = pd.read_csv(users_path)
    manifest = pd.read_csv(manifest_path)

    if args.limit_users:
        keep_users = set(users["user_id"].head(args.limit_users))
        users = users[users["user_id"].isin(keep_users)].copy()
        manifest = manifest[manifest["user_id"].isin(keep_users)].copy()

    if args.limit_cases:
        keep_cases = list(manifest["case_id"].drop_duplicates().head(args.limit_cases))
        manifest = manifest[manifest["case_id"].isin(keep_cases)].copy()

    rows = []
    feature_script = resolve_path(args.feature_script)

    for _, user in users.iterrows():
        user_id = user["user_id"]
        train_csv = resolve_path(user["train_csv"])
        train_features = feature_dir / f"{user_id}_train_features.csv"
        baseline_path = model_dir / f"{user_id}_baseline.json"

        print(f"building baseline: {user_id} ({user['profile']})")
        run_quiet(
            [
                sys.executable,
                feature_script,
                "--input",
                train_csv,
                "--output",
                train_features,
            ],
            log_dir / f"{user_id}_train_features.log",
        )
        run_quiet(
            [
                sys.executable,
                BASE / "src/build_baseline.py",
                "--input",
                train_features,
                "--output",
                baseline_path,
            ],
            log_dir / f"{user_id}_build_baseline.log",
        )

        user_cases = manifest[manifest["user_id"] == user_id]
        for _, case in user_cases.iterrows():
            case_id = case["case_id"]
            prefix = f"{user_id}_{case_id}"
            case_csv = resolve_path(case["input_csv"])
            case_features = feature_dir / f"{prefix}_features.csv"
            result_csv = result_dir / f"{prefix}_result.csv"
            episode_csv = summary_dir / f"{prefix}_episode_summary.csv"

            print(f"running case: {prefix}")
            run_quiet(
                [
                    sys.executable,
                    feature_script,
                    "--input",
                    case_csv,
                    "--output",
                    case_features,
                ],
                log_dir / f"{prefix}_features.log",
            )
            run_quiet(
                [
                    sys.executable,
                    BASE / "src/infer_ha_baseline.py",
                    "--features",
                    case_features,
                    "--baseline",
                    baseline_path,
                    "--output",
                    result_csv,
                ],
                log_dir / f"{prefix}_infer.log",
            )
            run_quiet(
                [
                    sys.executable,
                    BASE / "src/summarize_ha_result.py",
                    "--input",
                    result_csv,
                    "--output",
                    episode_csv,
                ],
                log_dir / f"{prefix}_episodes.log",
            )

            actual_level, max_score, alert_windows, result_patterns = max_level(result_csv)
            episode_count, episode_patterns, max_episode_level = episode_summary(episode_csv)
            patterns = "|".join(
                sorted(
                    {
                        pattern
                        for pattern in (result_patterns + "|" + episode_patterns).split("|")
                        if pattern
                    }
                )
            )
            outcome = classify_case(case, actual_level, episode_count, patterns)

            rows.append({
                "user_id": user_id,
                "profile": user["profile"],
                "case_id": case_id,
                "expected_min_level": case["expected_min_level"],
                "expected_max_level": case["expected_max_level"],
                "actual_max_level": actual_level,
                "max_episode_level": max_episode_level,
                "max_score": max_score,
                "alert_window_count": alert_windows,
                "episode_count": episode_count,
                "patterns": patterns,
                "result": outcome,
                "result_csv": str(result_csv),
                "episode_csv": str(episode_csv),
                "notes": case["notes"],
            })

    case_df = pd.DataFrame(rows)
    user_df = build_user_summary(case_df)
    overall = build_overall_summary(case_df, users, args)

    case_summary_path = output_dir / "validation_case_summary.csv"
    user_summary_path = output_dir / "validation_user_summary.csv"
    overall_path = output_dir / "validation_overall_summary.json"
    report_path = output_dir / "validation_report.md"

    case_df.to_csv(case_summary_path, index=False)
    user_df.to_csv(user_summary_path, index=False)
    overall_path.write_text(json.dumps(overall, indent=2), encoding="utf-8")
    write_markdown_report(report_path, overall, case_df[case_df["result"] != "pass"])

    print()
    print(f"case summary: {case_summary_path}")
    print(f"user summary: {user_summary_path}")
    print(f"overall summary: {overall_path}")
    print(f"report: {report_path}")
    print()
    print(
        "pass="
        f"{overall['pass_count']}/{overall['case_count']} "
        f"pass_rate={overall['pass_rate']} "
        f"false_alarm_rate={overall['normal_false_alarm_rate']} "
        f"risk_recall={overall['risk_recall']}"
    )


if __name__ == "__main__":
    main()
