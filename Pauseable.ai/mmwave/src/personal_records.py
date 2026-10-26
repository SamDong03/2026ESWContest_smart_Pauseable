import hashlib
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from features import FEATURE_NAMES


BASE = Path(__file__).resolve().parent
STORE = BASE / "runs" / "personalization"


feature_source = (BASE / "features.py").read_text(encoding="utf-8")
FEATURE_SCHEMA = hashlib.sha256(
    feature_source.encode("utf-8")
).hexdigest()


MIN_COVERAGE = 0.90


def utc_time(value):
    if not isinstance(value, str):
        raise ValueError("관측 시각은 시간대가 포함된 문자열이어야 합니다.")

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if parsed.tzinfo is None:
        raise ValueError("관측 시각에 시간대가 없습니다.")

    return parsed.astimezone(timezone.utc)


def validate_record(record):
    for key in ("profile_id", "sensor_id", "session_id"):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key}가 필요합니다.")

    origin = record.get("data_origin")
    if origin not in ("live", "simulated", "replay", "unknown"):
        raise ValueError("data_origin 값이 잘못됐습니다.")

    if record.get("time_status") != "synced":
        raise ValueError("시간이 확인된 관측 기록이 필요합니다.")

    start = utc_time(record.get("start_utc"))
    end = utc_time(record.get("end_utc"))
    if end <= start:
        raise ValueError("종료 시각은 시작 시각보다 뒤여야 합니다.")

    if record.get("identity_status") not in ("assigned", "unknown"):
        raise ValueError("identity_status는 assigned 또는 unknown입니다.")

    expected = record.get("expected_samples")
    observed = record.get("observed_samples")

    if type(expected) is not int or expected < 3:
        raise ValueError("expected_samples는 3 이상의 정수여야 합니다.")
    if type(observed) is not int or not 0 <= observed <= expected:
        raise ValueError("observed_samples 값이 잘못됐습니다.")

    if record.get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError("특징 계산 버전이 현재 코드와 다릅니다.")

    features = record.get("features")
    if not isinstance(features, dict) or set(features) != set(FEATURE_NAMES):
        raise ValueError("기존 경로 특징 9개가 모두 필요합니다.")

    for name, value in features.items():
        if type(value) not in (int, float):
            raise ValueError(f"{name}은 숫자여야 합니다.")
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{name}에 유효하지 않은 숫자가 있습니다.")

    reasons = []
    if origin != "live":
        reasons.append("not_live")
    if record["identity_status"] != "assigned":
        reasons.append("person_not_assigned")
    if observed < 3 or observed / expected < MIN_COVERAGE:
        reasons.append("insufficient_observation")

    return start, end, reasons


def add_record(record):
    record = dict(record)
    start, end, reasons = validate_record(record)

    record["start_utc"] = start.isoformat(timespec="microseconds")
    record["end_utc"] = end.isoformat(timespec="microseconds")


    identity = [
        record["profile_id"],
        record["sensor_id"],
        record["session_id"],
        record["start_utc"],
        record["end_utc"],
    ]
    window_id = hashlib.sha256(
        json.dumps(identity).encode("utf-8")
    ).hexdigest()


    filename = (
        "live.sqlite3"
        if record["data_origin"] == "live"
        else "test.sqlite3"
    )

    STORE.mkdir(parents=True, exist_ok=True)
    database = STORE / filename
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)

    with sqlite3.connect(database) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS windows (
                window_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                start_utc TEXT NOT NULL,
                end_utc TEXT NOT NULL,
                usable INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
        """)

        existing = connection.execute(
            "SELECT record_json FROM windows WHERE window_id = ?",
            (window_id,),
        ).fetchone()

        if existing is not None:
            if existing[0] != payload:
                raise ValueError("같은 관측 구간에 서로 다른 내용이 있습니다.")
            return {"status": "duplicate", "window_id": window_id}

        connection.execute(
            "INSERT INTO windows VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                window_id,
                record["profile_id"],
                record["start_utc"],
                record["end_utc"],
                int(not reasons),
                json.dumps(reasons),
                payload,
            ),
        )

    return {
        "status": "stored",
        "window_id": window_id,
        "store": filename,
        "usable_for_personal_analysis": not reasons,
        "reasons": reasons,
        "baseline_updated": False,
        "alert": False,
    }


def counts(filename):
    database = STORE / filename
    if not database.exists():
        return 0, 0

    with sqlite3.connect(database) as connection:
        total, usable = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(usable), 0) FROM windows"
        ).fetchone()

    return total, usable


def show_status():
    live_total, live_usable = counts("live.sqlite3")
    test_total, _ = counts("test.sqlite3")

    print(json.dumps({
        "live_records": live_total,
        "usable_live_records": live_usable,
        "test_records": test_total,
        "collection_status": (
            "collecting"
            if live_usable > 0
            else "awaiting_real_personal_data"
        ),
        "baseline_status": "not_created",
        "automatic_training": False,
        "alert": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        show_status()
    elif len(sys.argv) == 3 and sys.argv[1] == "add":
        record = json.loads(
            Path(sys.argv[2]).read_text(encoding="utf-8")
        )
        print(json.dumps(
            add_record(record),
            ensure_ascii=False,
            indent=2,
        ))
    else:
        raise SystemExit(
            "사용법: python personal_records.py "
            "[add 관측기록.json]"
        )
