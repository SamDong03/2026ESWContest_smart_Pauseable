import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


LEVEL_MAP = {
    "normal": "normal",
    "attention": "caution",
    "risk": "danger",
}


def to_utc_iso(value):
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def make_event_id(row):
    start = row["start_time"].replace("-", "").replace(":", "").replace(" ", "T")
    episode_id = row.get("episode_id", "0")
    return f"repetitive-{start}-{episode_id}"


def trim_text(value, limit=500):
    value = " ".join(str(value or "").split())
    return value[:limit]


def convert_row(
    row,
    patient_id,
    device_id,
    model_version,
    decision_policy=None,
    model_status=None,
):
    level = str(row["level"]).strip().lower()
    risk_level = LEVEL_MAP.get(level, "unknown")

    if risk_level == "unknown":
        return {
            "contract_version": "1.0",
            "event_id": make_event_id(row),
            "occurred_at": to_utc_iso(row["start_time"]),
            "patient_id": patient_id,
            "device_id": device_id,
            "source": "repetitive-ai",
            "behavior": "unknown",
            "risk_level": "unknown",
            "risk_score": None,
            "model_version": model_version,
            "inference_status": "model_error",
        }

    duration_minutes = int(float(row.get("duration_minutes", 0) or 0))
    window_count = int(float(row.get("window_count", 0) or 0))
    max_score = int(float(row.get("max_score", 0) or 0))
    pattern = str(row.get("primary_pattern", "") or "unknown_pattern").strip()

    behavior = "normal" if risk_level == "normal" else "repetitive"
    evidence = {
        "window_seconds": duration_minutes * 60,
        "observation_count": window_count,
        "pattern_code": pattern,
        "reason_text": trim_text(row.get("reasons", "")),
    }
    if decision_policy:
        evidence["decision_policy"] = decision_policy
    if model_status:
        evidence["model_status"] = model_status

    return {
        "contract_version": "1.0",
        "event_id": make_event_id(row),
        "occurred_at": to_utc_iso(row["start_time"]),
        "patient_id": patient_id,
        "device_id": device_id,
        "source": "repetitive-ai",
        "behavior": behavior,
        "risk_level": risk_level,
        "risk_score": max_score,
        "model_version": model_version,
        "inference_status": "ok",
        "evidence": evidence,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-summary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--patient-id", default="byunwoojin")
    parser.add_argument("--device-id", default="pi5-home-01")
    parser.add_argument("--model-version", default="ha-ai-baseline-v1")
    parser.add_argument("--decision-policy")
    parser.add_argument("--model-status")
    args = parser.parse_args()

    input_path = Path(args.episode_summary)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with input_path.open("r", encoding="utf-8", newline="") as f_in, output_path.open(
        "w", encoding="utf-8"
    ) as f_out:
        reader = csv.DictReader(f_in)
        for row in reader:
            payload = convert_row(
                row,
                patient_id=args.patient_id,
                device_id=args.device_id,
                model_version=args.model_version,
                decision_policy=args.decision_policy,
                model_status=args.model_status,
            )
            f_out.write(json.dumps(payload, ensure_ascii=False) + "\n")
            count += 1

    print(f"saved: {output_path}")
    print(f"payloads: {count}")


if __name__ == "__main__":
    main()
