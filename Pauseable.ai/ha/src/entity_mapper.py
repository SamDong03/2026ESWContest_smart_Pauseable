import argparse
import ast
import csv
import json
from pathlib import Path


DEVICE_KEYWORDS = {
    "dishwasher": ["dishwasher", "siggiseceoggi", "sikgisecheokgi", "식기세척기"],
    "fridge": ["fridge", "refrigerator", "naengjanggo", "냉장고", "김치냉장고"],
    "washer": ["washer", "washing", "washing_machine", "setaggi", "세탁기"],
    "dryer": ["dryer", "drying", "drying_machine", "geonjogi", "건조기"],
    "air_purifier": [
        "air_purifier",
        "purifier",
        "puri",
        "gonggiceongjeonggi",
        "공기청정기",
        "공청기",
        "퓨리케어",
    ],
    "air_conditioner": [
        "air_conditioner",
        "airconditioner",
        "aircon",
        "climate.",
        "climate_",
        "eokeon",
        "ac_power",
        "ac_mode",
        "virtual_ac",
        "pauseable_virtual_air_conditioner",
        "에어컨",
    ],
    "microwave": [
        "microwave",
        "microwave_oven",
        "jeonjareinji",
        "jeonjaleinji",
        "virtual_microwave",
        "pauseable_virtual_microwave",
        "전자레인지",
    ],
    "door_lock": [
        "door_lock",
        "front_door_lock",
        "smart_lock",
        "virtual_door_lock",
        "pauseable_virtual_door_lock",
        "hyeongwan_lock",
        "도어락",
        "현관잠금",
        "현관 도어락",
    ],
}

SIGNAL_KEYWORDS = {
    "door": ["door", "contact", "문", "도어"],
    "lock": ["lock", "locked", "door_lock", "잠금", "도어락"],
    "mode": ["mode", "preset", "모드"],
    "speed": ["speed", "fan", "wind", "풍량", "바람"],
    "temperature": ["temperature", "target_temp", "temp", "온도"],
    "power": ["power", "switch", "전원", "파워"],
    "operation": ["operation", "run", "running", "status", "state", "job", "작동", "운전", "상태"],
}

SKIP_ENTITY_PREFIXES = (
    "event.",
    "number.",
    "sun.",
    "weather.",
)

SKIP_ENTITY_KEYWORDS = (
    "air_quality",
    "clean_indicator",
    "cycles",
    "current_cycle",
    "delayed_end",
    "delayed_start",
    "energy_",
    "error",
    "express_mode",
    "filter_remaining",
    "forecast",
    "machine_clean",
    "next_noon",
    "notification",
    "odor",
    "overall_air_quality",
    "pm1",
    "pm2_5",
    "pm2.5",
    "pm10",
    "remaining_time",
    "remote_start",
    "rinse_aid",
    "rinse_refill",
    "schedule_turn",
    "softening_level",
    "sun_next",
    "temperature",
    "total_time",
)

SKIP_TEXT_KEYWORDS = (
    "air quality",
    "delayed end",
    "delayed start",
    "energy",
    "filter remaining",
    "forecast",
    "remaining time",
    "temperature",
    "total time",
    "공기질",
    "남은 시간",
    "냄새",
    "사용 횟수",
    "스케줄",
    "알림",
    "에너지",
    "예약",
    "오류",
    "온도",
    "잔여",
    "지연",
    "총 시간",
    "필터",
)

KEEP_ENTITY_KEYWORDS = (
    "air_conditioner_temperature",
    "pauseable_virtual_air_conditioner_temperature",
    "virtual_ac_temperature",
)

TIME_COLUMNS = ["event_time", "timestamp", "last_changed", "last_updated", "time", "datetime", "시간"]
ENTITY_COLUMNS = ["entity_id", "entity", "id", "엔티티", "엔티티ID"]
NAME_COLUMNS = ["friendly_name", "name", "display_name", "이름", "기기명"]
STATE_COLUMNS = ["state", "new_state", "action", "value", "상태", "값"]


def norm(value):
    return str(value or "").strip()


def lower(value):
    return norm(value).lower()


def normalize_row(row):
    return {lower(k): v for k, v in row.items()}


def pick(row, names):
    for name in names:
        key = lower(name)
        if key in row and norm(row[key]) != "":
            return row[key]
    return ""


def parse_attributes(value):
    text = norm(value)
    if not text:
        return {}

    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def should_skip_entity(entity_id, friendly_name, attr_device_class):
    e = lower(entity_id)
    text = lower(f"{entity_id} {friendly_name} {attr_device_class}")
    if e.startswith('climate.'):
        return False

    if any(keyword in e for keyword in KEEP_ENTITY_KEYWORDS):
        return False

    if any(e.startswith(prefix) for prefix in SKIP_ENTITY_PREFIXES):
        return True
    if any(keyword in e for keyword in SKIP_ENTITY_KEYWORDS):
        return True
    if any(keyword in text for keyword in SKIP_TEXT_KEYWORDS):
        return True

    return False


def detect_device(text):
    t = lower(text)
    for device_type, keywords in DEVICE_KEYWORDS.items():
        if any(k.lower() in t for k in keywords):
            return device_type
    return "unknown"


def detect_signal(text, entity_id, state, device_type):
    t = lower(text)
    e = lower(entity_id)
    s = lower(state)

    if device_type == "door_lock":
        return "lock"

    if device_type == "microwave":
        if e.startswith(("switch.", "input_boolean.")) or "power" in e or "전원" in t:
            return "power"
        if "status" in e or "operation" in e or "state" in e or "상태" in t or "작동" in t:
            return "operation"

    if device_type == "air_conditioner":
        if e.startswith(("switch.", "input_boolean.")) or "power" in e or "전원" in t:
            return "power"
        if "temperature" in e or "target_temp" in e or "temp" in e or "온도" in t:
            return "temperature"
        if "mode" in e or "hvac" in e or "preset" in e or "모드" in t:
            return "mode"
        if "speed" in e or "fan" in e or "wind" in e or "풍량" in t:
            return "speed"

    if device_type == "air_purifier":
        if e.startswith("switch.") or "power" in e or "파워" in t or "전원" in t:
            return "power"
        if "operating_mode" in e or "operation_mode" in e or "mode" in e or "모드" in t:
            return "mode"
        if "speed" in e or "fan" in e or "wind" in e or "속도" in t or "풍량" in t:
            return "speed"

    if e.startswith(("switch.", "input_boolean.")):
        return "power"

    if device_type == "fridge" and ("door" in e or "문" in t or "도어" in t):
        return "door"

    if device_type in {"washer", "dryer", "dishwasher"}:
        is_operation_entity = (
            "current_status" in e
            or e.endswith("_operation")
            or "operation" in e
            or "status" in e
            or "현재 상태" in t
            or "운전" in t
        )
        if is_operation_entity:
            return "operation"

    for signal_type, keywords in SIGNAL_KEYWORDS.items():
        if any(k.lower() in t for k in keywords):
            return signal_type

    if device_type == "fridge" and s in {"on", "off", "open", "closed", "열림", "닫힘"}:
        return "door"

    return "unknown"


def normalize_action(signal_type, state, device_type=""):
    s = lower(state)

    if s in {"", "initial", "unknown", "unavailable", "none", "null", "nan"}:
        return "skip"

    if signal_type == "lock":
        if s in {"on", "true", "open", "opened", "unlock", "unlocked", "열림", "해제", "잠금해제"}:
            return "unlock"
        if s in {"off", "false", "close", "closed", "lock", "locked", "닫힘", "잠김"}:
            return "lock"

    if signal_type == "door":
        if s in {"on", "open", "opened", "true", "열림"}:
            return "open"
        if s in {"off", "close", "closed", "false", "닫힘"}:
            return "close"

    if signal_type == "operation":
        if s in {
            "add_drain",
            "cook",
            "cooking",
            "cooling",
            "detecting",
            "dispensing",
            "drying",
            "frozen_prevent_running",
            "prewash",
            "refreshing",
            "rinse_hold",
            "rinsing",
            "run",
            "running",
            "soaking",
            "spinning",
            "start",
            "started",
            "heating",
            "steam_softening",
            "washing",
            "wrinkle_care",
            "작동",
            "운전",
            "세탁중",
            "건조중",
        }:
            return "running"
        if s in {"off", "idle", "power_off", "standby", "stop", "stopped", "대기", "정지"}:
            return "idle"
        if s in {"done", "complete", "completed", "finished", "end", "완료", "종료"}:
            return "done"
        if s in {"frozen_prevent_pause", "pause", "paused", "일시정지"}:
            return "paused"

    if signal_type == "power":
        if s in {"on", "true", "켜짐"}:
            return "on"
        if s in {"off", "false", "꺼짐"}:
            return "off"

    if signal_type in {"mode", "speed", "temperature"}:
        return s

    return s


def convert_row(raw_row):
    row = normalize_row(raw_row)

    attrs = parse_attributes(pick(row, ["attributes_json", "attributes", "attribute", "속성"]))
    attr_name = attrs.get("friendly_name", "")
    attr_device_class = attrs.get("device_class", "")

    event_time = pick(row, TIME_COLUMNS)
    entity_id = pick(row, ENTITY_COLUMNS)
    friendly_name = pick(row, NAME_COLUMNS) or attr_name
    state = pick(row, STATE_COLUMNS)

    if not event_time or should_skip_entity(entity_id, friendly_name, attr_device_class):
        return {
            "event_time": event_time,
            "device_type": "unknown",
            "signal_type": "unknown",
            "action": "skip",
        }

    text = f"{entity_id} {friendly_name} {attr_device_class}"
    device_type = detect_device(text)
    signal_type = detect_signal(text, entity_id, state, device_type)
    action = normalize_action(signal_type, state, device_type)

    return {
        "event_time": event_time,
        "device_type": device_type,
        "signal_type": signal_type,
        "action": action,
        "entity_id": entity_id,
        "record_type": pick(row, ["record_type"]) or "state_changed_event",
        "recorded_at": pick(row, ["recorded_at"]) or event_time,
    }


def convert_rows(raw_row):
    row = normalize_row(raw_row)
    entity_id = pick(row, ENTITY_COLUMNS)
    if not lower(entity_id).startswith('climate.'):
        return [convert_row(raw_row)]
    attrs = parse_attributes(pick(row, ['attributes_json', 'attributes']))
    state = lower(pick(row, STATE_COLUMNS))
    event_time = pick(row, TIME_COLUMNS)
    if not event_time or state in {'unknown', 'unavailable', '', 'none'}:
        return [convert_row(raw_row)]
    base = {'event_time': event_time, 'device_type': 'air_conditioner', 'entity_id': entity_id,
            'record_type': pick(row, ['record_type']) or 'state_changed_event',
            'recorded_at': pick(row, ['recorded_at']) or event_time}
    signals = {'mode': state, 'power': 'off' if state == 'off' else 'on'}
    if isinstance(attrs.get('temperature'), (int, float)):
        signals['temperature'] = str(attrs['temperature'])
    if attrs.get('fan_mode') is not None:
        signals['speed'] = str(attrs['fan_mode'])
    return [{**base, 'signal_type': key, 'action': value} for key, value in signals.items()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--keep-unknown", action="store_true")
    args = parser.parse_args()

    rows = []
    skipped = 0
    unknown = 0

    with open(args.input, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            for converted in convert_rows(raw):
                if converted["action"] == "skip":
                    skipped += 1
                    continue
                is_unknown = converted["device_type"] == "unknown" or converted["signal_type"] == "unknown"
                if is_unknown:
                    unknown += 1
                    if not args.keep_unknown:
                        continue
                rows.append(converted)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["event_time", "device_type", "signal_type", "action", "entity_id", "record_type", "recorded_at"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"saved: {output_path}")
    print(f"converted rows: {len(rows)}")
    print(f"skipped telemetry/unavailable rows: {skipped}")
    print(f"unknown entity rows: {unknown}")


if __name__ == "__main__":
    main()
