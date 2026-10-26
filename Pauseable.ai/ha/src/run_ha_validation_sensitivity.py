import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else BASE / path


def parse_int_list(value):
    return [int(part.strip()) for part in str(value).split(",") if part.strip()]


def run(cmd):
    print("$ " + " ".join(str(part) for part in cmd))
    subprocess.run([str(part) for part in cmd], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=12)
    parser.add_argument("--train-days", default="7,14,30")
    parser.add_argument("--seeds", default="42,99,2026")
    parser.add_argument("--start-date", default="2026-08-01")
    parser.add_argument("--generated-root", default="data/generated/ha_population_sensitivity")
    parser.add_argument("--output-root", default="outputs/ha_validation_sensitivity")
    args = parser.parse_args()

    train_days_values = parse_int_list(args.train_days)
    seeds = parse_int_list(args.seeds)
    generated_root = resolve_path(args.generated_root)
    output_root = resolve_path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    rows = []
    for train_days in train_days_values:
        for seed in seeds:
            run_id = f"days_{train_days}_seed_{seed}"
            generated_dir = generated_root / run_id
            output_dir = output_root / run_id

            run([
                sys.executable,
                BASE / "src/run_ha_population_validation.py",
                "--generated-dir",
                generated_dir,
                "--output-dir",
                output_dir,
                "--users",
                args.users,
                "--train-days",
                train_days,
                "--start-date",
                args.start_date,
                "--seed",
                seed,
            ])

            summary_path = output_dir / "validation_overall_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            rows.append({
                "run_id": run_id,
                "users": summary["users"],
                "train_days": summary["train_days"],
                "seed": summary["seed"],
                "case_count": summary["case_count"],
                "pass_rate": summary["pass_rate"],
                "normal_false_alarm_rate": summary["normal_false_alarm_rate"],
                "attention_or_risk_detection_rate": summary["attention_or_risk_detection_rate"],
                "risk_recall": summary["risk_recall"],
                "review_count": summary["review_count"],
                "output_dir": str(output_dir),
            })

    summary_csv = output_root / "sensitivity_summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    aggregate = {
        "run_count": len(rows),
        "min_pass_rate": min(row["pass_rate"] for row in rows),
        "max_false_alarm_rate": max(row["normal_false_alarm_rate"] for row in rows),
        "min_attention_or_risk_detection_rate": min(
            row["attention_or_risk_detection_rate"] for row in rows
        ),
        "min_risk_recall": min(row["risk_recall"] for row in rows),
        "runs": rows,
    }
    aggregate_json = output_root / "sensitivity_overall_summary.json"
    aggregate_json.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")

    print(f"sensitivity summary: {summary_csv}")
    print(f"sensitivity overall: {aggregate_json}")
    print(
        "min_pass_rate="
        f"{aggregate['min_pass_rate']} "
        f"max_false_alarm_rate={aggregate['max_false_alarm_rate']} "
        f"min_risk_recall={aggregate['min_risk_recall']}"
    )


if __name__ == "__main__":
    main()
