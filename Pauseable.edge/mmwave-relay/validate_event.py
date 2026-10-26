

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "Pauseable.contracts" / "mmwave-target-event.schema.json"
EXAMPLES_PATH = REPO_ROOT / "Pauseable.contracts" / "examples" / "mmwave"
MAX_PACKET_BYTES = 4096
SOURCE_BY_ORIGIN = {
    "live": "esp32-ld6004",
    "simulated": "pauseable-simulator",
    "replay": "pauseable-replay",
}
_SUPPORTED_KEYWORDS = {
    "$schema", "$id", "$comment", "title", "description", "type", "const",
    "enum", "required", "properties", "additionalProperties", "items",
    "maxItems", "minimum", "maximum", "minLength", "maxLength", "pattern",
    "format",
}


class ContractError(ValueError):
    pass


def _check_schema_support(spec: dict[str, Any]) -> None:
    unsupported = set(spec) - _SUPPORTED_KEYWORDS
    if unsupported:
        raise RuntimeError(f"Unsupported contract keywords: {sorted(unsupported)}")
    if spec.get("format") not in (None, "date-time"):
        raise RuntimeError("Unsupported contract format")
    if "additionalProperties" in spec and spec["additionalProperties"] is not False:
        raise RuntimeError("This contract reader requires closed objects")
    allowed = {"object", "array", "string", "integer", "number", "boolean", "null"}
    types = spec.get("type", [])
    if isinstance(types, str):
        types = [types]
    if not types or not set(types) <= allowed:
        raise RuntimeError("Unsupported or missing contract type")
    for child in spec.get("properties", {}).values():
        _check_schema_support(child)
    if "items" in spec:
        _check_schema_support(spec["items"])


SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_check_schema_support(SCHEMA)


def _is_type(value: Any, expected: str) -> bool:
    if expected == "number":

        return type(value) in (int, float)
    return {
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(expected, False)


def _shape_errors(value: Any, spec: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    types = spec["type"]
    if isinstance(types, str):
        types = [types]
    if not any(_is_type(value, item) for item in types):
        return [f"{path}: expected {'/'.join(types)}"]
    if "const" in spec and value != spec["const"]:
        errors.append(f"{path}: expected {spec['const']!r}")
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: expected one of {spec['enum']}")
    if value is None:
        return errors
    if type(value) is dict:
        for field in spec.get("required", []):
            if field not in value:
                errors.append(f"{path}.{field}: missing field")
        properties = spec.get("properties", {})
        for field, content in value.items():
            if field not in properties:
                errors.append(f"{path}.{field}: unexpected field")
            else:
                errors.extend(_shape_errors(content, properties[field], f"{path}.{field}"))
    elif type(value) is list:
        limit = spec.get("maxItems")
        if limit is not None and len(value) > limit:
            return [f"{path}: at most {limit} entries are allowed"]
        for index, item in enumerate(value):
            errors.extend(_shape_errors(item, spec["items"], f"{path}[{index}]"))
    elif type(value) is str:
        if len(value) < spec.get("minLength", 0):
            errors.append(f"{path}: string too short")
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            errors.append(f"{path}: string too long")
        if "pattern" in spec and re.fullmatch(spec["pattern"], value) is None:
            errors.append(f"{path}: invalid string format")
        if spec.get("format") == "date-time":
            try:

                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: invalid calendar date/time")
    elif type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            errors.append(f"{path}: number must be finite")
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(f"{path}: below minimum {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            errors.append(f"{path}: above maximum {spec['maximum']}")
    return errors


def validate_event(event: Any) -> list[str]:
    pass


    errors = _shape_errors(event, SCHEMA, "$")
    if errors:
        return errors
    if event["source"] != SOURCE_BY_ORIGIN[event["data_origin"]]:
        errors.append("$.source: does not match data_origin")
    expected_id = f"{event['sensor_id']}:{event['session_id']}:{event['seq']}"
    if event["event_id"] != expected_id:
        errors.append("$.event_id: must equal sensor_id:session_id:seq")
    synced = event["time_status"] == "synced"
    if synced != (event["occurred_at"] is not None):
        errors.append("$.occurred_at: synced needs UTC time; unsynced needs null")
    if event["target_count"] != len(event["targets"]):
        errors.append("$.target_count: does not equal len(targets)")
    ids = [target["id"] for target in event["targets"]]
    if len(set(ids)) != len(ids):
        errors.append("$.targets: duplicate target id within one frame")
    if event["targets_truncated"] and event["target_count"] != 4:
        errors.append("$.targets_truncated: truncation requires four transmitted targets")
    if event["sensor_status"] != "ok":
        if event["target_count"] or event["targets"] or event["targets_truncated"]:
            errors.append("$.sensor_status: unhealthy sensor must carry no targets")
        if event["frame_age_ms"] is not None:
            errors.append("$.frame_age_ms: unhealthy sensor needs null")
    else:
        if event["frame_age_ms"] is None:
            errors.append("$.frame_age_ms: ok sensor needs a frame age")
        elif event["frame_age_ms"] > event["uptime_ms"]:
            errors.append("$.frame_age_ms: cannot exceed sender session uptime")
    if event["data_origin"] == "replay":
        if event["replay"] is None:
            errors.append("$.replay: provenance is required for replay")
        elif event["replay"]["original_event_id"] == event["event_id"]:
            errors.append("$.replay.original_event_id: replay needs a new event identity")
    elif event["replay"] is not None:
        errors.append("$.replay: must be null outside replay mode")
    return errors


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError(f"Non-JSON numeric constant: {value}")


def parse_event(payload: bytes) -> dict[str, Any]:
    pass
    if not isinstance(payload, bytes):
        raise ContractError("Payload must be UTF-8 bytes")
    if len(payload) > MAX_PACKET_BYTES:
        raise ContractError(f"Packet exceeds {MAX_PACKET_BYTES} bytes")
    try:
        event = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ContractError(f"Invalid JSON: {exc}") from exc
    errors = validate_event(event)
    if errors:
        raise ContractError("; ".join(errors))
    return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, help="One JSON event per file")
    parser.add_argument("--examples", action="store_true", help="Check bundled synthetic fixtures")
    args = parser.parse_args(argv)
    paths = list(args.files)
    if args.examples:
        paths.extend(sorted(EXAMPLES_PATH.glob("*.json")))
    if not paths:
        parser.error("Provide event file(s) or --examples")
    failures = 0
    for path in paths:
        try:
            with path.open("rb") as handle:
                event = parse_event(handle.read(MAX_PACKET_BYTES + 1))
            print(f"PASS {path.name} origin={event['data_origin']} targets={event['target_count']}")
        except (OSError, ContractError) as exc:
            failures += 1
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
    print(f"Checked {len(paths)} event(s); {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
