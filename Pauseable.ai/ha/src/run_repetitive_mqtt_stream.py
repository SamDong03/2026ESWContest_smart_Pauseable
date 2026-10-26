#!/usr/bin/env python3


from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_repetitive_mqtt_payload import default_schema_path

BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src"


def rel(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else BASE / p


def run_step(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=BASE, text=True, check=check)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payloads: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payloads.append(json.loads(line))
    return payloads


def write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def episode_key(payload: dict[str, Any]) -> str:
    evidence = payload.get("evidence") or {}
    parts = [
        str(payload.get("behavior", "")),
        str(payload.get("occurred_at", "")),
        str(evidence.get("pattern_code", "")),
    ]
    return "|".join(parts)


def decision_signature(payload: dict[str, Any]) -> str:
    return "|".join(
        [
            str(payload.get("risk_level", "")),
            str(payload.get("inference_status", "")),
            str(payload.get("risk_score", "")),
        ]
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp_live_tts_payloads(
    payloads: list[dict[str, Any]],
    *,
    title: str,
    message: str,
) -> list[dict[str, Any]]:
    now_iso = utc_now_iso()
    now_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamped: list[dict[str, Any]] = []

    for index, payload in enumerate(payloads, start=1):
        updated = dict(payload)
        base_event_id = str(updated.get("event_id", "repetitive"))
        updated["event_id"] = f"{base_event_id}-live-{now_id}-{index}"
        updated["occurred_at"] = now_iso
        stamped.append(updated)

    return stamped

def select_new_payloads(
    payloads: list[dict[str, Any]], state_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = load_json(state_path, {"episode_signatures": {}})
    episode_signatures = state.setdefault("episode_signatures", {})
    selected: list[dict[str, Any]] = []

    for payload in payloads:
        key = episode_key(payload)
        signature = decision_signature(payload)
        previous = episode_signatures.get(key)
        if previous == signature:
            continue


        if previous is not None:
            payload = dict(payload)
            digest = hashlib.sha256(f"{key}|{signature}".encode("utf-8")).hexdigest()[:12]
            payload["event_id"] = f"{payload.get('event_id', 'repetitive')}-{digest}"

        selected.append(payload)
        episode_signatures[key] = signature

    return selected, state


def publish_and_commit(
    args: argparse.Namespace,
    payloads: list[dict[str, Any]],
    next_state: dict[str, Any],
    payload_path: Path,
    state_path: Path,
) -> None:
    write_jsonl(payload_path, payloads)
    run_step(
        [
            sys.executable,
            str(SRC / "publish_repetitive_mqtt.py"),
            "--input",
            str(payload_path),
            "--host",
            args.mqtt_host,
            "--port",
            str(args.mqtt_port),
        ]
    )
    save_json(state_path, next_state)


def build_collector_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "-u",
        str(SRC / "collect_ha_events_ws.py"),
        "--output",
        str(rel(args.raw_output)),
        "--duration-seconds",
        "0",
        "--status-every-seconds",
        str(args.collector_status_seconds),
    ]
    if args.ha_url:
        cmd += ["--ha-url", args.ha_url]
    if args.token:
        cmd += ["--token", args.token]
    if args.write_initial_snapshot:
        cmd.append("--write-initial-snapshot")
    if args.truncate:
        cmd.append("--truncate")
    for keyword in args.entity_keyword:
        cmd += ["--entity-keyword", keyword]
    return cmd


def run_inference_publish_cycle(args: argparse.Namespace) -> None:
    raw_path = rel(args.raw_output)
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        print(f"waiting for HA events: {raw_path}", flush=True)
        return

    output_dir = rel("outputs")
    payload_path = output_dir / f"{args.prefix}_repetitive_mqtt_payloads.jsonl"
    new_payload_path = output_dir / f"{args.prefix}_repetitive_mqtt_payloads_new.jsonl"
    summary_path = output_dir / f"{args.prefix}_episode_summary.csv"

    pipeline_cmd = [
        sys.executable,
        str(SRC / "run_ha_pipeline.py"),
        "--input",
        str(raw_path),
        "--baseline",
        str(rel(args.baseline)),
        "--prefix",
        args.prefix,
        "--data-source",
        args.data_source,
    ]
    try:
        run_step(pipeline_cmd)
    except subprocess.CalledProcessError as exc:
        print(f"pipeline failed, will retry next cycle: exit={exc.returncode}", flush=True)
        return

    if not summary_path.exists():
        print(f"no episode summary yet: {summary_path}", flush=True)
        return

    try:
        run_step(
            [
                sys.executable,
                str(SRC / "export_repetitive_mqtt_payload.py"),
                "--episode-summary",
                str(summary_path),
                "--output",
                str(payload_path),
                "--patient-id",
                args.patient_id,
                "--device-id",
                args.device_id,
                "--model-version",
                args.model_version,
                "--decision-policy",
                args.decision_policy,
                "--model-status",
                args.model_status,
            ]
        )
        run_step(
            [
                sys.executable,
                str(SRC / "validate_repetitive_mqtt_payload.py"),
                "--schema",
                str(rel(args.schema)),
                "--input",
                str(payload_path),
            ]
        )
    except subprocess.CalledProcessError as exc:
        print(f"payload export/validation failed, will retry next cycle: exit={exc.returncode}", flush=True)
        return

    payloads = read_jsonl(payload_path)
    state_path = rel(args.state_file)
    new_payloads, next_state = select_new_payloads(payloads, state_path)
    if not new_payloads:
        print("no new repetitive decisions to publish", flush=True)
        return

    new_payloads = stamp_live_tts_payloads(
        new_payloads,
        title=args.tts_title,
        message=args.tts_message,
    )

    try:
        publish_and_commit(
            args,
            new_payloads,
            next_state,
            new_payload_path,
            state_path,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"MQTT publish failed, state was not committed; will retry next cycle: "
            f"exit={exc.returncode}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-output", default="data/raw/repetitive_live_events.csv")
    parser.add_argument("--baseline", default="outputs/normal_demo_baseline_v2.json")
    parser.add_argument("--prefix", default="repetitive_live")
    parser.add_argument("--schema", default=str(default_schema_path()))
    parser.add_argument("--state-file", default="outputs/repetitive_mqtt_stream_state.json")
    parser.add_argument(
        "--data-source",
        choices=("local", "public", "synthetic", "unknown"),
        default="local",
    )
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--collector-status-seconds", type=float, default=30.0)
    parser.add_argument("--ha-url")
    parser.add_argument("--token")
    parser.add_argument("--entity-keyword", action="append", default=[])
    parser.add_argument("--write-initial-snapshot", action="store_true")
    parser.add_argument("--truncate", dest="truncate", action="store_true", default=True)
    parser.add_argument("--no-truncate", dest="truncate", action="store_false")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--patient-id", default="byunwoojin")
    parser.add_argument("--device-id", default="pi5-home-01")
    parser.add_argument("--model-version", default="ha-ai-baseline-v1")
    parser.add_argument("--decision-policy", default="rules_with_shadow_models")
    parser.add_argument("--model-status", default="not_trained")
    parser.add_argument("--tts-title", default="반복 행동 감지")
    parser.add_argument("--tts-message", default="할머니 냉장고 문 닫아줘")
    args = parser.parse_args()

    collector_cmd = build_collector_cmd(args)
    print("starting HA event collector", flush=True)
    print("$ " + " ".join(collector_cmd), flush=True)
    collector = subprocess.Popen(collector_cmd, cwd=BASE)

    stopping = False

    def stop_handler(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True
        print(f"received signal {signum}, stopping", flush=True)
        collector.terminate()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        while not stopping:
            time.sleep(args.interval_seconds)
            if collector.poll() is not None:
                print(f"collector exited: code={collector.returncode}", flush=True)
                break
            run_inference_publish_cycle(args)
    finally:
        if collector.poll() is None:
            collector.terminate()
            try:
                collector.wait(timeout=10)
            except subprocess.TimeoutExpired:
                collector.kill()


if __name__ == "__main__":
    main()
