

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import random
import re
import socket
import sys
import time
import uuid

from validate_event import ContractError, MAX_PACKET_BYTES, parse_event


SCENARIOS = (
    "walking", "empty", "multiple", "sensor-error", "stale",
    "silence", "duplicate", "out-of-order", "demo",
)
MAX_EVENTS = 10000
MAX_LOG_RECORDS = MAX_EVENTS * 2
MAX_LOG_BYTES = 16 * 1024 * 1024


def bounded_int(low, high):
    def convert(text):
        try:
            value = int(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Enter an integer.") from exc
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"Allowed range: {low}..{high}")
        return value
    return convert


def identifier(text):
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", text) is None:
        raise argparse.ArgumentTypeError("Use 1..48 lowercase letters, digits, _ or -.")
    return text


def ipv4(text):
    try:
        return str(ipaddress.IPv4Address(text))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Enter an IPv4 address, e.g. 127.0.0.1.") from exc


def encode_event(event):
    payload = json.dumps(
        event, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    parse_event(payload)
    return payload


def envelope(sensor_id, session_id, seq, uptime_ms):
    return {
        "schema_version": "1.0",
        "event_id": f"{sensor_id}:{session_id}:{seq}",
        "source": "pauseable-simulator",
        "data_origin": "simulated",
        "sensor_id": sensor_id,
        "session_id": session_id,
        "seq": seq,
        "occurred_at": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "time_status": "synced",
        "uptime_ms": uptime_ms,
        "measurement_profile": "ld6004-target-raw-v1",
        "sensor_status": "ok",
        "frame_age_ms": 0,
        "target_count": 0,
        "targets_truncated": False,
        "targets": [],
        "replay": None,
    }


class Simulator:
    def __init__(self, scenario, count, seed, sensor_id):
        self.scenario = scenario
        self.count = count
        self.sensor_id = sensor_id
        self.session_id = uuid.uuid4().hex
        self.rng = random.Random(seed)
        self.frozen_targets = None

    def make_event(self, seq, uptime_ms):
        mode = self.scenario
        if mode == "demo":
            mode = ("walking", "empty", "sensor-error")[min(2, seq * 3 // self.count)]
        event = envelope(self.sensor_id, self.session_id, seq, uptime_ms)
        if mode == "sensor-error":
            event.update(sensor_status="error", frame_age_ms=None)
        elif mode != "empty":
            if mode == "stale" and self.frozen_targets is not None:
                targets = deepcopy(self.frozen_targets)
            else:

                phase = seq % 48
                step = phase if phase <= 24 else 48 - phase
                x = round(-1.2 + step * 0.1 + self.rng.uniform(-0.01, 0.01), 3)
                targets = [{"id": 1, "x": x, "y": 0.5, "z": 1.3, "doppler": -1}]
                if mode == "multiple":
                    targets.append({"id": 2, "x": -x, "y": 1.0, "z": 1.2, "doppler": 1})
            event.update(targets=targets, target_count=len(targets))
            if mode == "stale":
                self.frozen_targets = deepcopy(targets)

                event["frame_age_ms"] = uptime_ms
        return event


def load_replay(path, count, interval_ms, max_extra_wait_ms):
    pass
    if not path.is_file():
        raise ValueError(f"Replay input is not a regular file: {path}")
    records, digest, total = [], hashlib.sha256(), 0
    with path.open("rb") as handle:
        line_no = 0
        while True:

            line = handle.readline(MAX_PACKET_BYTES + 3)
            if not line:
                break
            line_no += 1
            total += len(line)
            if total > MAX_LOG_BYTES:
                raise ValueError("Replay log exceeds 16 MiB.")
            digest.update(line)
            payload = line.removesuffix(b"\n").removesuffix(b"\r")
            if len(payload) > MAX_PACKET_BYTES:
                raise ValueError(f"{path.name}:{line_no}: record exceeds 4096 bytes.")
            if not payload.strip():
                continue
            try:
                event = parse_event(payload)
            except ContractError as exc:
                raise ValueError(f"{path.name}:{line_no}: {exc}") from exc
            records.append((event, line_no - 1))
            if len(records) > MAX_LOG_RECORDS:
                raise ValueError(f"Replay log exceeds {MAX_LOG_RECORDS} records.")
    if not records:
        raise ValueError("Replay log contains no events.")
    if count is not None:
        if count > len(records):
            raise ValueError(f"Requested {count} events, but log contains {len(records)}.")
        records = records[:count]
    schedule, due_ms = [], 0
    for index, (event, _) in enumerate(records):
        age = event["frame_age_ms"] or 0
        due_ms = max(0 if index == 0 else due_ms + interval_ms, age)
        if due_ms - index * interval_ms > max_extra_wait_ms:
            raise ValueError(
                f"Replay event {index}: preserving frame_age_ms needs more than "
                f"{max_extra_wait_ms}ms extra wait. Increase --max-replay-wait-ms."
            )
        schedule.append(due_ms)
    return records, schedule, "log-" + digest.hexdigest()[:24]


def replay_event(record, index, uptime_ms, session_id, log_id):
    original, frame_index = record
    event = envelope(original["sensor_id"], session_id, index, uptime_ms)
    for field in ("sensor_status", "frame_age_ms", "target_count", "targets_truncated", "targets"):
        event[field] = deepcopy(original[field])
    event.update(source="pauseable-replay", data_origin="replay")
    if original["data_origin"] == "replay":

        event["replay"] = deepcopy(original["replay"])
    else:
        event["replay"] = {
            "log_id": log_id,
            "frame_index": frame_index,
            "original_origin": original["data_origin"],
            "original_event_id": original["event_id"],
            "original_occurred_at": original["occurred_at"],
        }
    return event


def wait_until(started_ns, due_ms):
    deadline = started_ns + due_ms * 1_000_000
    while True:
        remaining = deadline - time.monotonic_ns()
        if remaining <= 0:
            return
        time.sleep(remaining / 1_000_000_000)


def self_test():
    checked = 0
    for scenario in SCENARIOS:
        simulator = Simulator(scenario, 9, 42, "test-radar")
        for seq in range(9):
            encode_event(simulator.make_event(seq, seq * 100))
            checked += 1
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2.0)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for scenario in ("walking", "empty", "sensor-error"):
                payload = encode_event(Simulator(scenario, 1, 42, "test-radar").make_event(0, 0))
                sender.sendto(payload, receiver.getsockname())
                received, _ = receiver.recvfrom(MAX_PACKET_BYTES + 1)
                if received != payload:
                    raise ValueError("Loopback UDP payload mismatch.")
                parse_event(received)
    print(f"SELF-TEST OK: {checked} valid events; 3 loopback UDP packets received.")
    print("This checks software and local UDP, not ESP32/Pi5 or model accuracy.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default=None)
    parser.add_argument("--count", type=bounded_int(1, MAX_EVENTS), default=None,
                        help="Generated frames (default 10); replay defaults to all records.")
    parser.add_argument("--interval-ms", type=bounded_int(1, 60000), default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sensor-id", type=identifier, default="test-radar")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="Enable UDP transmission.")
    mode.add_argument("--dry-run", action="store_true", help="Print/record only (default).")
    parser.add_argument("--host", type=ipv4, default="127.0.0.1")
    parser.add_argument("--port", type=bounded_int(1, 65535), default=5005)
    parser.add_argument("--output", type=Path, help="New UTF-8 JSONL file; never overwrite.")
    parser.add_argument("--quiet", action="store_true", help="Suppress JSON stdout; keep summary.")
    parser.add_argument("--replay", type=Path, help="Replay validated JSONL (not raw UART HEX).")
    parser.add_argument("--max-replay-wait-ms", type=bounded_int(0, 60000), default=10000,
                        help="Maximum EXTRA replay delay to retain frame age (default 10000).")
    parser.add_argument("--self-test", action="store_true", help="Validate scenarios and local UDP.")
    return parser


def run(args):
    scenario = args.scenario or "walking"
    if args.replay:
        records, schedule, log_id = load_replay(
            args.replay, args.count, args.interval_ms, args.max_replay_wait_ms
        )
        count, session_id = len(records), uuid.uuid4().hex

        for index, record in enumerate(records):
            encode_event(replay_event(record, index, schedule[index], session_id, log_id))
    else:
        count = args.count or 10
        records = None
        schedule = [index * args.interval_ms for index in range(count)]
        simulator = Simulator(scenario, count, args.seed, args.sensor_id)

    stats = {"generated": 0, "emitted": 0, "udp_sent": 0, "dropped": 0}
    exit_code = 0
    with ExitStack() as resources:
        udp = None
        if args.send:
            udp = resources.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            udp.settimeout(2.0)
        log = None
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            log = resources.enter_context(args.output.open("x", encoding="utf-8", newline="\n"))
        print("MODE: " + (f"UDP -> {args.host}:{args.port}" if udp else "DRY-RUN (no UDP)"), file=sys.stderr)

        def emit(payload):
            parse_event(payload)
            if udp is not None:
                if udp.sendto(payload, (args.host, args.port)) != len(payload):
                    raise OSError("Incomplete UDP send.")
                stats["udp_sent"] += 1
            text = payload.decode("utf-8")
            if log is not None:
                log.write(text + "\n")
                log.flush()
            if not args.quiet:
                print(text, flush=True)
            stats["emitted"] += 1

        held = None
        started_ns = time.monotonic_ns()
        try:
            for seq in range(count):
                wait_until(started_ns, schedule[seq])
                uptime_ms = (time.monotonic_ns() - started_ns) // 1_000_000
                event = (replay_event(records[seq], seq, uptime_ms, session_id, log_id)
                         if records is not None else simulator.make_event(seq, uptime_ms))
                payload = encode_event(event)
                stats["generated"] += 1
                if records is None and scenario == "silence" and count // 3 <= seq < 2 * count // 3:
                    stats["dropped"] += 1
                    continue
                if records is None and scenario == "out-of-order":
                    if held is None:
                        held = payload
                        continue
                    emit(payload)
                    emit(held)
                    held = None
                else:
                    emit(payload)
                    if records is None and scenario == "duplicate":
                        emit(payload)
            if held is not None:
                emit(held)
        except KeyboardInterrupt:
            exit_code = 130
            print("Interrupted by user.", file=sys.stderr)
        finally:
            print("SUMMARY " + json.dumps(stats, separators=(",", ":")), file=sys.stderr)
            if udp:
                print("udp_sent counts successful send calls, not receiver acknowledgements.", file=sys.stderr)
    return exit_code


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.replay and args.scenario:
        parser.error("--replay and --scenario cannot be used together.")
    if not args.replay and (args.scenario or "walking") in ("silence", "demo") and (args.count or 10) < 3:
        parser.error("silence/demo requires --count >= 3.")
    try:
        return self_test() if args.self_test else run(args)
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
