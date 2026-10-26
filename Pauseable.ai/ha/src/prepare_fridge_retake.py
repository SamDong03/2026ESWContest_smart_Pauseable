#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from run_repetitive_hybrid_demo import BASE, atomic_json, iso_z, utc_now


def publish_normal(args: argparse.Namespace) -> str:
    now = utc_now()
    event_id = f"repetitive-retake-normal-{now.strftime('%Y%m%dT%H%M%SZ')}"
    payload = {
        "contract_version": "1.0",
        "event_id": event_id,
        "occurred_at": iso_z(now),
        "patient_id": args.patient_id,
        "device_id": args.device_id,
        "source": "repetitive-ai",
        "behavior": "normal",
        "risk_level": "normal",
        "risk_score": 0,
        "model_version": args.model_version,
        "inference_status": "ok",
    }
    output = BASE / "outputs" / "repetitive_retake_normal.jsonl"
    output.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(BASE / "src" / "publish_repetitive_mqtt.py"),
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
        ],
        cwd=BASE,
        check=True,
    )
    return event_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-file",
        default=str(BASE / "outputs" / "repetitive_hybrid_live_state.json"),
    )
    parser.add_argument("--patient-id", default="byunwoojin")
    parser.add_argument("--device-id", default="pi5-home-01")
    parser.add_argument("--model-version", default="20260911T122626748657Z")
    parser.add_argument("--mqtt-topic", default="pauseable/ai/repetitive/decision")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    args = parser.parse_args()

    event_id = publish_normal(args)
    now = utc_now()
    atomic_json(
        Path(args.state_file),
        {
            "active": False,
            "opens_10m": 0,
            "rearm_after": iso_z(now),
            "updated_at": iso_z(now),
            "reset_event_id": event_id,
        },
    )
    subprocess.run(
        [
            sys.executable,
            str(BASE / "src" / "turn_on_air_purifier.py"),
            "--desired-state",
            "off",
        ],
        cwd=BASE,
        check=True,
    )
    print(
        f"RETAKE_READY reset_at={iso_z(now)} purifier=off",
        flush=True,
    )


if __name__ == "__main__":
    main()
