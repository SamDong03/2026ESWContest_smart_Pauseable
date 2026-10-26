import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


def resolve_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE / path


def required_value(name, value):
    if value is None or str(value).strip() == "":
        raise ValueError(f"{name} is required. Use the command option or environment variable.")
    return str(value).strip()


def append_csv_row(path, fieldnames, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def run_logged(label, cmd, log_path, env):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{label}] $ " + " ".join(str(part) for part in cmd))
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(part) for part in cmd],
            cwd=BASE,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            text = line.rstrip()
            if text:
                print(f"[{label}] {text}")

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"{label} failed with exit code {return_code}. See {log_path}")


def read_level_counts(result_path):
    counts = Counter()
    if not result_path.exists():
        return counts

    with result_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            counts[row.get("level", "unknown")] += 1
    return counts


def read_episode_summary(episode_path):
    rows = []
    if not episode_path.exists():
        return rows

    with episode_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def max_episode_score(rows):
    scores = []
    for row in rows:
        value = row.get("max_score") or ""
        try:
            scores.append(float(value))
        except ValueError:
            pass
    return max(scores) if scores else ""


def top_episode_pattern(rows):
    if not rows:
        return ""

    scored_rows = []
    for row in rows:
        try:
            score = float(row.get("max_score") or 0)
        except ValueError:
            score = 0.0
        scored_rows.append((score, row))
    scored_rows.sort(key=lambda item: item[0], reverse=True)
    return scored_rows[0][1].get("primary_pattern", "")


def build_env(args):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["HA_URL"] = args.ha_url
    env["HA_TOKEN"] = args.ha_token
    return env


def build_collector_cmd(args, raw_path):
    cmd = [
        sys.executable,
        "-u",
        BASE / "src/collect_ha_events_ws.py",
        "--output",
        raw_path,
        "--duration-seconds",
        str(args.collection_seconds),
        "--status-every-seconds",
        str(args.status_every_seconds),
    ]

    if args.write_initial_snapshot:
        cmd.append("--write-initial-snapshot")
    if args.truncate:
        cmd.append("--truncate")
    if args.include_all or not args.entity_keyword:
        cmd.append("--include-all")
    for keyword in args.entity_keyword:
        cmd.extend(["--entity-keyword", keyword])

    return cmd


def build_pipeline_cmd(args, raw_path, prefix):
    cmd = [
        sys.executable,
        BASE / "src/run_ha_pipeline.py",
        "--input",
        raw_path,
        "--baseline",
        resolve_path(args.baseline),
        "--prefix",
        prefix,
        "--baseline-history",
        resolve_path(args.baseline_history),
        "--quarantine",
        resolve_path(args.quarantine),
        "--abnormal-log",
        resolve_path(args.abnormal_log),
        "--max-history-days",
        str(args.max_history_days),
        "--max-review-days",
        str(args.max_review_days),
    ]
    if args.update_baseline:
        cmd.append("--update-baseline")
    if args.init_history_from_current_normal:
        cmd.append("--init-history-from-current-normal")
    cmd.extend(["--model-dir", resolve_path(args.model_dir), "--data-source", args.data_source,
                "--event-history", resolve_path(args.event_history)])
    return cmd


def print_cycle_summary(cycle_id, counts, episodes, result_path, episode_path):
    print()
    print(f"=== HA automation cycle {cycle_id} ===")
    print(f"result_csv: {result_path}")
    print(f"episode_csv: {episode_path}")
    print(
        "level_counts: "
        f"normal={counts.get('normal', 0)} "
        f"attention={counts.get('attention', 0)} "
        f"risk={counts.get('risk', 0)}"
    )
    print(f"episodes: {len(episodes)}")
    for row in episodes[:5]:
        print(
            "  "
            f"{row.get('start_time', '')}~{row.get('end_time', '')} "
            f"level={row.get('level', '')} "
            f"score={row.get('max_score', '')} "
            f"pattern={row.get('primary_pattern', '')}"
        )
    print()


SUMMARY_FIELDS = [
    "cycle_id",
    "started_at",
    "finished_at",
    "status",
    "raw_csv",
    "result_csv",
    "episode_csv",
    "normal_count",
    "attention_count",
    "risk_count",
    "episode_count",
    "max_score",
    "primary_pattern",
    "error",
]


def run_cycle(args, env, cycle_number):
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    cycle_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.max_cycles != 1:
        cycle_id = f"{cycle_id}_{cycle_number:04d}"

    raw_dir = resolve_path(args.raw_dir)
    raw_path = raw_dir / f"{args.prefix}_{cycle_id}_events.csv"
    cycle_prefix = f"{args.prefix}_{cycle_id}"
    result_path = BASE / "outputs" / f"{cycle_prefix}_result.csv"
    episode_path = BASE / "outputs" / f"{cycle_prefix}_episode_summary.csv"
    log_dir = resolve_path(args.log_dir)
    collector_log = log_dir / f"{cycle_prefix}_collector.log"
    pipeline_log = log_dir / f"{cycle_prefix}_pipeline.log"

    row = {
        "cycle_id": cycle_id,
        "started_at": started_at,
        "finished_at": "",
        "status": "started",
        "raw_csv": str(raw_path),
        "result_csv": str(result_path),
        "episode_csv": str(episode_path),
        "normal_count": 0,
        "attention_count": 0,
        "risk_count": 0,
        "episode_count": 0,
        "max_score": "",
        "primary_pattern": "",
        "error": "",
    }

    collector_cmd = build_collector_cmd(args, raw_path)
    pipeline_cmd = build_pipeline_cmd(args, raw_path, cycle_prefix)

    if args.dry_run:
        print(f"[cycle] {cycle_id}")
        print("[collector] $ " + " ".join(str(part) for part in collector_cmd))
        print("[pipeline] $ " + " ".join(str(part) for part in pipeline_cmd))
        row["status"] = "dry_run"
        row["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        return row

    try:
        run_logged("collector", collector_cmd, collector_log, env)
        collected_until = datetime.now().astimezone().isoformat(timespec="seconds")
        pipeline_cmd.extend(["--window-start", started_at, "--window-end", collected_until])
        run_logged("pipeline", pipeline_cmd, pipeline_log, env)

        counts = read_level_counts(result_path)
        episodes = read_episode_summary(episode_path)
        print_cycle_summary(cycle_id, counts, episodes, result_path, episode_path)

        quality_path = BASE / "outputs" / f"{cycle_prefix}_data_quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
        row.update(
            {
                "status": "no_usable_data" if quality.get("status") == "no_usable_data" else "ok",
                "normal_count": counts.get("normal", 0),
                "attention_count": counts.get("attention", 0),
                "risk_count": counts.get("risk", 0),
                "episode_count": len(episodes),
                "max_score": max_episode_score(episodes),
                "primary_pattern": top_episode_pattern(episodes),
            }
        )
    except Exception as exc:
        row["status"] = "failed"
        row["error"] = str(exc)
        print(f"[cycle] failed: {exc}")
        if args.stop_on_error:
            raise
    finally:
        row["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    return row


def automation_loop(args):
    args.ha_url = required_value("HA_URL", args.ha_url)
    args.ha_token = required_value("HA_TOKEN", args.ha_token)

    env = build_env(args)
    summary_path = resolve_path(args.summary_csv)
    cycle_number = 1

    print("starting HA automation loop")
    print(f"HA_URL: {args.ha_url}")
    print(f"collection_seconds: {args.collection_seconds:g}")
    print(f"max_cycles: {'infinite' if args.max_cycles == 0 else args.max_cycles}")
    print(f"summary_csv: {summary_path}")

    while args.max_cycles == 0 or cycle_number <= args.max_cycles:
        row = run_cycle(args, env, cycle_number)
        if not args.dry_run:
            append_csv_row(summary_path, SUMMARY_FIELDS, row)

        if args.max_cycles != 0 and cycle_number >= args.max_cycles:
            break

        cycle_number += 1
        if args.sleep_seconds > 0:
            print(f"sleeping {args.sleep_seconds:g}s before next cycle")
            time.sleep(args.sleep_seconds)

    print("HA automation loop finished")


def main():
    parser = argparse.ArgumentParser(
        description="Continuously collect Home Assistant events and run the HA baseline pipeline.",
    )
    parser.add_argument("--ha-url", default=os.getenv("HA_URL"))
    parser.add_argument("--ha-token", default=os.getenv("HA_TOKEN"))
    parser.add_argument("--collection-seconds", type=float, default=600.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--max-cycles", type=int, default=0, help="0 means run forever")
    parser.add_argument("--status-every-seconds", type=float, default=60.0)
    parser.add_argument("--raw-dir", default="data/raw/ha_automation_cycles")
    parser.add_argument("--baseline", default="models/user_001_real_baseline_v2.json")
    parser.add_argument("--baseline-history", default="data/features/user_001_baseline_history_v2.csv")
    parser.add_argument("--quarantine", default="data/features/user_001_quarantine_v2.csv")
    parser.add_argument("--abnormal-log", default="outputs/user_001_abnormal_log_v2.csv")
    parser.add_argument("--max-history-days", type=int, default=30)
    parser.add_argument("--max-review-days", type=int, default=90)
    parser.add_argument("--prefix", default="ha_automation")
    parser.add_argument("--model-dir", default="models/anomaly_current")
    parser.add_argument("--data-source", choices=["local", "synthetic", "public", "unknown"], default="local")
    parser.add_argument("--event-history", default="data/raw/ha_continuous_context.csv")
    parser.add_argument("--summary-csv", default="outputs/ha_automation_cycle_summary.csv")
    parser.add_argument("--log-dir", default="outputs/logs/ha_automation")
    parser.add_argument("--entity-keyword", action="append", default=[])
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--write-initial-snapshot", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--truncate", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--init-history-from-current-normal", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        automation_loop(args)
    except KeyboardInterrupt:
        print("stopped by user")


if __name__ == "__main__":
    main()
