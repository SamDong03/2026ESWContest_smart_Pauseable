import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE = Path(__file__).resolve().parents[1]
FIELDNAMES = [
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

DEFAULT_ENTITY_KEYWORDS = [
    "setaggi",
    "geonjogi",
    "naengjanggo",
    "gonggiceongjeonggi",
    "pauseable_virtual",
    "virtual_ac",
    "virtual_microwave",
    "virtual_door_lock",
    "climate.",
    "dishwasher",
    "siggiseceoggi",
]

DEFAULT_BEHAVIOR_SUFFIXES = [
    "_current_status",
    "_door",
    "_lock",
    "_mode",
    "_operating_mode",
    "_operation",
    "_power",
    "_speed",
    "_status",
    "_target_temperature",
    "_temperature",
]


def resolve_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE / path


def normalize_ha_url(value):
    if not value:
        raise ValueError("Home Assistant URL is required. Use --ha-url or HA_URL.")

    value = value.rstrip("/")
    if value.endswith("/api"):
        value = value[:-4]
    return value


def states_url(ha_url):
    return f"{normalize_ha_url(ha_url)}/api/states"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fetch_states(ha_url, token, timeout):
    request = Request(
        states_url(ha_url),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def entity_is_selected(entity_id, keywords, behavior_only):
    entity_id = str(entity_id or "").lower()
    if not entity_id:
        return False

    if keywords and not any(keyword.lower() in entity_id for keyword in keywords):
        return False

    if behavior_only:
        if entity_id.startswith('climate.'):
            return True
        return any(suffix in entity_id for suffix in DEFAULT_BEHAVIOR_SUFFIXES)

    return True


def state_signature(item):
    return (
        str(item.get("entity_id", "")),
        str(item.get("state", "")),
        str(item.get("last_changed", "")),
        str(item.get("last_updated", "")),
    )


def state_to_row(item, record_type, recorded_at):
    entity_id = str(item.get("entity_id", ""))
    attrs = item.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}

    return {
        "recorded_at": recorded_at,
        "event_time": item.get("last_updated") or item.get("last_changed") or recorded_at,
        "record_type": record_type,
        "entity_id": entity_id,
        "domain": entity_id.split(".", 1)[0] if "." in entity_id else "",
        "state": item.get("state", ""),
        "friendly_name": attrs.get("friendly_name", ""),
        "last_changed": item.get("last_changed", ""),
        "last_updated": item.get("last_updated", ""),
        "attributes_json": json.dumps(attrs, ensure_ascii=False, sort_keys=True),
    }


def append_rows(path, rows):
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def selected_states(states, keywords, behavior_only):
    return [
        item
        for item in states
        if entity_is_selected(item.get("entity_id"), keywords, behavior_only)
    ]


def collect_once(ha_url, token, timeout, keywords, behavior_only, write_snapshot):
    states = selected_states(fetch_states(ha_url, token, timeout), keywords, behavior_only)
    signatures = {item["entity_id"]: state_signature(item) for item in states}
    rows = []
    if write_snapshot:
        recorded_at = utc_now()
        rows = [state_to_row(item, "state_snapshot", recorded_at) for item in states]
    return rows, signatures


def collect_loop(args):
    output_path = resolve_path(args.output)
    token = args.token or os.getenv("HA_TOKEN")
    ha_url = args.ha_url or os.getenv("HA_URL")

    if not token:
        raise ValueError("Home Assistant token is required. Use --token or HA_TOKEN.")

    keywords = args.entity_keyword
    if args.include_all:
        keywords = []
    elif not keywords:
        keywords = DEFAULT_ENTITY_KEYWORDS

    rows, previous = collect_once(
        ha_url=ha_url,
        token=token,
        timeout=args.timeout,
        keywords=keywords,
        behavior_only=args.behavior_only,
        write_snapshot=args.write_initial_snapshot or args.once,
    )
    append_rows(output_path, rows)
    print(f"initial selected entities: {len(previous)}")
    if rows:
        print(f"initial rows written: {len(rows)}")

    if args.once:
        print(f"saved: {output_path}")
        return

    start_time = time.monotonic()
    total_written = len(rows)

    while True:
        if args.duration_seconds > 0:
            elapsed = time.monotonic() - start_time
            if elapsed >= args.duration_seconds:
                break

        time.sleep(args.poll_seconds)
        try:
            states = selected_states(
                fetch_states(ha_url, token, args.timeout),
                keywords,
                args.behavior_only,
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"poll failed: {exc}")
            continue

        recorded_at = utc_now()
        changed_rows = []
        for item in states:
            entity_id = item.get("entity_id")
            signature = state_signature(item)
            if previous.get(entity_id) != signature:
                changed_rows.append(state_to_row(item, "state_changed", recorded_at))
                previous[entity_id] = signature

        append_rows(output_path, changed_rows)
        total_written += len(changed_rows)
        if changed_rows:
            print(f"changed rows written: {len(changed_rows)} total: {total_written}")

    print(f"saved: {output_path}")
    print(f"total rows written: {total_written}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ha-url", help="Home Assistant base URL, or HA_URL env var")
    parser.add_argument("--token", help="Long-lived access token, or HA_TOKEN env var")
    parser.add_argument("--output", default="data/raw/ha_state_events_live.csv")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--entity-keyword", action="append")
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--behavior-only", action="store_true", default=True)
    parser.add_argument("--include-telemetry", dest="behavior_only", action="store_false")
    parser.add_argument("--write-initial-snapshot", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    collect_loop(args)


if __name__ == "__main__":
    main()
