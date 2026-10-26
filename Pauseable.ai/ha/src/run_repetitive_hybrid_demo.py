#!/usr/bin/env python3


from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd
from ha_recorder_observation import validate_history
from ha_alert_delivery import alert_score, deliver_transition, model_version
from ha_decision_delivery import SCHEMA
from validate_repetitive_mqtt_payload import payload_validator


BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src"
FIELDS = [
    "recorded_at",
    "event_time",
    "record_type",
    "entity_id",
    "domain",
    "state",
    "friendly_name",
    "last_changed",
    "last_updated",
    "attributes_json",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def fetch_history(hours: float, entity_id: str) -> tuple[list[dict[str, Any]], datetime, datetime]:
    now = utc_now()
    start = now - timedelta(hours=hours)
    base = os.environ["HA_URL"].rstrip("/")
    url = (
        f"{base}/api/history/period/{quote(start.isoformat())}"
        f"?filter_entity_id={quote(entity_id)}"
        f"&end_time={quote(now.isoformat())}&no_attributes"
    )
    request = Request(url, headers={"Authorization": f"Bearer {os.environ['HA_TOKEN']}"})
    data = json.load(urlopen(request, timeout=20))
    history = data[0] if data else []
    if not history:
        raise RuntimeError(f"No Home Assistant Recorder history for {entity_id}")
    validate_history(history, start, now, entity_id)
    return history, start, now


def recent_open_count(
    history: list[dict[str, Any]],
    now: datetime,
    minutes: int = 10,
    after: datetime | None = None,
) -> int:
    cutoff = now - timedelta(minutes=minutes)
    if after is not None:
        cutoff = max(cutoff, after)
    return sum(
        1
        for item in history
        if item.get("state") == "on"
        and item.get("last_changed")
        and parse_time(item["last_changed"]) >= cutoff
    )


def write_observation(
    history: list[dict[str, Any]],
    start: datetime,
    now: datetime,
    raw_path: Path,
    entity_id: str,
) -> Path:
    observation = validate_history(history, start, now, entity_id)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    attributes = json.dumps(
        {"device_class": "door", "friendly_name": "냉장고 문"},
        ensure_ascii=False,
    )
    rows = []
    for index, item in enumerate(history):
        changed = item.get("last_changed") or item.get("last_updated")
        updated = item.get("last_updated") or changed
        rows.append(
            {
                "recorded_at": start.isoformat() if index == 0 else updated,
                "event_time": changed,
                "record_type": "state_snapshot" if index == 0 else "state_changed_event",
                "entity_id": entity_id,
                "domain": "binary_sensor",
                "state": item.get("state", "unknown"),
                "friendly_name": "냉장고 문",
                "last_changed": changed,
                "last_updated": updated,
                "attributes_json": attributes,
            }
        )

    temporary = raw_path.with_suffix(".tmp.csv")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, raw_path)

    coverage_path = raw_path.with_suffix(".coverage.json")
    atomic_json(
        coverage_path,
        {
            "intervals": [[start.isoformat(), now.isoformat()]],
            "confirmed_at": now.isoformat(),
            "source": "home_assistant_recorder",
            "observation_validation": observation,
            "note": "Demo observation reconstructed from persistent HA Recorder history",
        },
    )
    return coverage_path


def run_pipeline(args: argparse.Namespace, raw_path: Path, coverage_path: Path, start: datetime, now: datetime) -> None:
    command = [
        sys.executable,
        str(SRC / "run_ha_pipeline.py"),
        "--input",
        str(raw_path),
        "--baseline",
        str(Path(args.baseline)),
        "--prefix",
        args.prefix,
        "--data-source",
        "synthetic",
        "--household-id",
        args.household_id,
        "--coverage-file",
        str(coverage_path),
        "--window-start",
        start.isoformat(),
        "--window-end",
        now.isoformat(),
        "--lifecycle-dir",
        str(Path(args.lifecycle_dir)),
        "--model-policy",
        "hybrid",
        "--no-lifecycle-learning",
        "--no-personalize",
    ]
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=BASE, check=True)


def latest_decision(prefix: str) -> dict[str, Any]:
    path = BASE / "outputs" / f"{prefix}_result.csv"
    frame = pd.read_csv(path)
    if frame.empty:
        raise RuntimeError("The hybrid pipeline produced no decision rows")
    return frame.iloc[-1].fillna("").to_dict()


def reason_code(value: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return value[:64] or "unknown"


def build_payload(row: dict[str, Any], opens: int, args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    level = str(row.get("level", ""))
    risk_level = "danger" if level == "risk" else "caution"
    score = alert_score(row)
    if_level = reason_code(str(row.get("if_level", "unavailable")))
    ae_level = reason_code(str(row.get("ae_level", "unavailable")))
    policy = str(row.get("decision_policy", "rules_plus_validated_if_ae"))[:64]
    model_status = str(row.get("model_status", "shadow"))[:64]
    reason = " ".join(str(row.get("reasons", "")).split())
    reason = (
        f"{reason}; fridge opens in 10m={opens}; IF={if_level}; AE={ae_level}; "
        "synthetic-pretrained hybrid demo, not a medical diagnosis"
    ).strip("; ")[:500]
    return {
        "contract_version": "1.0",
        "event_id": f"repetitive-hybrid-live-{uuid.uuid4().hex}",
        "occurred_at": iso_z(now),
        "patient_id": args.patient_id,
        "device_id": args.device_id,
        "source": "repetitive-ai",
        "behavior": "repetitive",
        "risk_level": risk_level,
        "risk_score": score,
        "model_version": model_version(row, args),
        "inference_status": "ok",
        "evidence": {
            "window_seconds": 600,
            "observation_count": opens,


            "pattern_code": "fridge_repeated_check",
            "reason_text": reason,
            "decision_policy": policy,
            "model_status": model_status,
            "reason_codes": [
                "fridge_repeated_check",
                "model_contributed" if if_level in {"attention", "risk"} or ae_level in {"attention", "risk"} else "baseline_alert",
                f"if_{if_level}",
                f"ae_{ae_level}",
            ],
        },
    }


def build_normal_payload(args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    return {
        "contract_version": "1.0",
        "event_id": f"repetitive-hybrid-normal-{uuid.uuid4().hex}",
        "occurred_at": iso_z(now),
        "patient_id": args.patient_id,
        "device_id": args.device_id,
        "source": "repetitive-ai",
        "behavior": "normal",
        "risk_level": "normal",
        "risk_score": 0,
        "model_version": model_version({}, args),
        "inference_status": "ok",
    }


def publish(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    payload_validator(SCHEMA).validate(payload)
    output = BASE / "outputs" / f"{args.prefix}_publish.jsonl"
    output.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.dry_run:
        print("DRY-RUN " + json.dumps(payload, ensure_ascii=False), flush=True)
        return
    command = [
        sys.executable,
        str(SRC / "publish_repetitive_mqtt.py"),
        "--input",
        str(output),
        "--topic",
        args.mqtt_topic,
        "--host",
        args.mqtt_host,
        "--port",
        str(args.mqtt_port),
        "--qos",
        "1",
        "--no-retain",
    ]
    subprocess.run(command, cwd=BASE, check=True)


def run_cycle(args: argparse.Namespace, state_path: Path) -> None:
    history, start, now = fetch_history(args.history_hours, args.entity_id)
    opens = recent_open_count(history, now)
    print(
        f"RECORDER_STATUS utc={iso_z(now)} opens_10m={opens}",
        flush=True,
    )

    raw_path = BASE / "data" / "raw" / f"{args.prefix}.csv"
    coverage_path = write_observation(history, start, now, raw_path, args.entity_id)
    run_pipeline(args, raw_path, coverage_path, start, now)
    decision = latest_decision(args.prefix)
    level = str(decision.get("level", ""))
    result = deliver_transition(
        state_path, level, lambda: build_payload(decision, opens, args),
        lambda: build_normal_payload(args), lambda payload: publish(args, payload),
        pattern="fridge_repeated_check", dry_run=getattr(args, "dry_run", False),
    )
    print("DEMO_DELIVERY " + json.dumps(result), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--history-hours", type=float, default=2.25)
    parser.add_argument("--prefix", default="repetitive_hybrid_live")
    parser.add_argument("--baseline", default=str(BASE / "outputs/normal_demo_baseline_v2.json"))
    parser.add_argument(
        "--lifecycle-dir",
        default=str(BASE / "outputs/fridge_ai_demo_lifecycle_20261004"),
    )
    parser.add_argument("--model-version", help="Override label only when no model_id is present")
    parser.add_argument("--household-id", default="synthetic-month-acceptance")
    parser.add_argument("--patient-id", default="byunwoojin")
    parser.add_argument("--device-id", default="pi5-home-01")
    parser.add_argument("--entity-id", default="binary_sensor.naengjanggo_door")
    parser.add_argument("--state-file", default=str(BASE / "outputs/repetitive_hybrid_live_state.json"))
    parser.add_argument("--mqtt-topic", default="pauseable/ai/repetitive/decision")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.poll_seconds < 5:
        parser.error("--poll-seconds must be at least 5")
    if args.history_hours < 2:
        parser.error("--history-hours must be at least 2")
    state_path = Path(args.state_file)
    while True:
        try:
            run_cycle(args, state_path)
        except KeyboardInterrupt:
            raise
        except Exception as error:
            print(f"DEMO_ERROR {type(error).__name__}: {error}", flush=True)
            if args.once:
                raise SystemExit(1)
        if args.once:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
