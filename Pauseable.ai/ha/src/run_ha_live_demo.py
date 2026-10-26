import argparse
import csv
import os
import subprocess
import sys
import threading
import time
from collections import Counter
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


def print_command(label, cmd):
    print(f"[{label}] $ " + " ".join(str(part) for part in cmd))


def stream_process(process, label, log_path, ready_event=None, ready_patterns=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ready_patterns = ready_patterns or []

    with log_path.open("w", encoding="utf-8") as log:
        for line in process.stdout:
            log.write(line)
            log.flush()
            text = line.rstrip()
            if text:
                print(f"[{label}] {text}")
            if ready_event and any(pattern in text for pattern in ready_patterns):
                ready_event.set()


def start_streamed_process(label, cmd, log_path, env=None, ready_patterns=None):
    ready_event = threading.Event() if ready_patterns else None
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
    thread = threading.Thread(
        target=stream_process,
        args=(process, label, log_path, ready_event, ready_patterns),
        daemon=True,
    )
    thread.start()
    return process, thread, ready_event


def run_streamed_command(label, cmd, log_path, env=None):
    print_command(label, cmd)
    process, thread, _ = start_streamed_process(label, cmd, log_path, env=env)
    return_code = process.wait()
    thread.join(timeout=2.0)
    if return_code != 0:
        raise RuntimeError(f"{label} failed with exit code {return_code}. See {log_path}")


def stop_process(process, thread, label):
    if process.poll() is None:
        print(f"[{label}] stopping collector")
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            print(f"[{label}] collector did not stop in time; killing it")
            process.kill()
            process.wait(timeout=5.0)
    thread.join(timeout=2.0)


def read_level_counts(result_path):
    if not result_path.exists():
        return Counter()

    counts = Counter()
    with result_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            counts[row.get("level", "unknown")] += 1
    return counts


def read_episode_rows(episode_path):
    if not episode_path.exists():
        return []

    with episode_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def print_summary(result_path, episode_path):
    print()
    print("=== HA live demo summary ===")
    print(f"result_csv: {result_path}")
    print(f"episode_csv: {episode_path}")

    counts = read_level_counts(result_path)
    if counts:
        print("level_counts:")
        for level in ["normal", "attention", "risk"]:
            if level in counts:
                print(f"  {level}: {counts[level]}")

    episodes = read_episode_rows(episode_path)
    print(f"episodes: {len(episodes)}")
    for row in episodes[:5]:
        print(
            "  "
            f"{row.get('start_time', '')}~{row.get('end_time', '')} "
            f"level={row.get('level', '')} "
            f"score={row.get('max_score', '')} "
            f"pattern={row.get('primary_pattern', '')}"
        )


def build_collector_cmd(args, raw_output):
    cmd = [
        sys.executable,
        "-u",
        BASE / "src/collect_ha_events_ws.py",
        "--output",
        raw_output,
        "--duration-seconds",
        args.collection_seconds,
        "--status-every-seconds",
        args.status_every_seconds,
    ]

    if args.write_initial_snapshot:
        cmd.append("--write-initial-snapshot")
    if args.truncate:
        cmd.append("--truncate")
    if args.include_all:
        cmd.append("--include-all")
    else:
        for keyword in args.entity_keyword:
            cmd.extend(["--entity-keyword", keyword])

    return cmd


def build_publisher_cmd(args):
    return [
        sys.executable,
        "-u",
        BASE / "src/publish_virtual_mqtt_devices.py",
        "--host",
        args.mqtt_host,
        "--port",
        args.mqtt_port,
        "--username",
        args.mqtt_user,
        "--scenario",
        args.scenario,
        "--delay-seconds",
        args.delay_seconds,
    ]


def build_pipeline_cmd(args, raw_output):
    cmd = [
        sys.executable,
        BASE / "src/run_ha_pipeline.py",
        "--input",
        raw_output,
        "--baseline",
        args.baseline,
        "--prefix",
        args.prefix,
    ]
    if args.update_baseline:
        cmd.append("--update-baseline")
    if args.init_history_from_current_normal:
        cmd.append("--init-history-from-current-normal")
    return cmd


def build_env(args):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["HA_URL"] = args.ha_url
    env["HA_TOKEN"] = args.ha_token
    env["MQTT_HOST"] = args.mqtt_host
    env["MQTT_PORT"] = str(args.mqtt_port)
    env["MQTT_USER"] = args.mqtt_user
    env["MQTT_PASSWORD"] = args.mqtt_password
    return env


def estimate_publish_seconds(args):
    try:
        from publish_virtual_mqtt_devices import SCENARIOS

        return len(SCENARIOS.get(args.scenario, [])) * float(args.delay_seconds)
    except Exception:
        return 30.0


def run_demo(args):
    raw_output = resolve_path(args.raw_output)
    baseline = resolve_path(args.baseline)
    args.baseline = str(baseline)

    env = build_env(args)
    log_dir = resolve_path(args.log_dir)
    collector_log = log_dir / f"{args.prefix}_collector.log"
    publisher_log = log_dir / f"{args.prefix}_publisher.log"
    pipeline_log = log_dir / f"{args.prefix}_pipeline.log"

    collector_cmd = build_collector_cmd(args, raw_output)
    publisher_cmd = build_publisher_cmd(args)
    pipeline_cmd = build_pipeline_cmd(args, raw_output)

    if args.dry_run:
        print_command("collector", collector_cmd)
        print_command("publisher", publisher_cmd)
        print_command("pipeline", pipeline_cmd)
        print("dry-run only; no HA/MQTT connection was opened")
        return

    print("starting HA WebSocket collector")
    print_command("collector", collector_cmd)
    ready_patterns = ["initial snapshot rows written"] if args.write_initial_snapshot else ["subscribed: state_changed"]
    collector, collector_thread, collector_ready = start_streamed_process(
        "collector",
        collector_cmd,
        collector_log,
        env=env,
        ready_patterns=ready_patterns,
    )

    try:
        if not collector_ready.wait(timeout=args.collector_ready_timeout):
            raise RuntimeError(
                "collector did not become ready in time. "
                f"See {collector_log} and check HA_URL/HA_TOKEN."
            )

        print("collector is ready; publishing MQTT scenario")
        run_streamed_command("publisher", publisher_cmd, publisher_log, env=env)

        if args.settle_seconds > 0:
            print(f"waiting {args.settle_seconds:g}s for HA state_changed events")
            time.sleep(args.settle_seconds)

        if args.wait_full_duration:
            remaining_timeout = max(
                args.collection_seconds,
                estimate_publish_seconds(args) + args.settle_seconds + 10,
            )
            collector.wait(timeout=remaining_timeout)
            collector_thread.join(timeout=2.0)
        else:
            stop_process(collector, collector_thread, "collector")

        print("running HA baseline pipeline")
        run_streamed_command("pipeline", pipeline_cmd, pipeline_log, env=env)
    except Exception:
        stop_process(collector, collector_thread, "collector")
        raise

    result_path = BASE / "outputs" / f"{args.prefix}_result.csv"
    episode_path = BASE / "outputs" / f"{args.prefix}_episode_summary.csv"
    print_summary(result_path, episode_path)


def main():
    parser = argparse.ArgumentParser(
        description="Run the HA MQTT live demo end-to-end: collect events, publish a scenario, run baseline inference.",
    )
    parser.add_argument("--ha-url", default=os.getenv("HA_URL"))
    parser.add_argument("--ha-token", default=os.getenv("HA_TOKEN"))
    parser.add_argument("--mqtt-host", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--mqtt-user", default=os.getenv("MQTT_USER", "mqtt_user"))
    parser.add_argument("--mqtt-password", default=os.getenv("MQTT_PASSWORD"))
    parser.add_argument("--scenario", default="demo_risk_combo")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--collection-seconds", type=float, default=90.0)
    parser.add_argument("--collector-ready-timeout", type=float, default=30.0)
    parser.add_argument("--settle-seconds", type=float, default=5.0)
    parser.add_argument("--status-every-seconds", type=float, default=15.0)
    parser.add_argument("--raw-output", default="data/raw/ha_live_demo_events.csv")
    parser.add_argument("--baseline", default="models/user_001_real_baseline_v2.json")
    parser.add_argument("--prefix", default="ha_live_demo")
    parser.add_argument("--log-dir", default="outputs/logs")
    parser.add_argument("--entity-keyword", action="append", default=["pauseable_virtual"])
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--write-initial-snapshot", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--truncate", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--wait-full-duration", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--init-history-from-current-normal", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    args.ha_url = required_value("HA_URL", args.ha_url)
    args.ha_token = required_value("HA_TOKEN", args.ha_token)
    args.mqtt_host = required_value("MQTT_HOST", args.mqtt_host)
    args.mqtt_user = required_value("MQTT_USER", args.mqtt_user)
    args.mqtt_password = required_value("MQTT_PASSWORD", args.mqtt_password)

    run_demo(args)


if __name__ == "__main__":
    main()
