import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "Pauseable.edge" / "mmwave-relay"))

from validate_event import MAX_PACKET_BYTES, parse_event, validate_event


class TrajectoryWindows:
    pass


    def __init__(self, sample_ms, window_ms=30000, *, alignment_ms=0,
                 max_gap_ms=None):
        if type(sample_ms) is not int or type(window_ms) is not int:
            raise ValueError("sample_ms and window_ms must be positive integers.")
        if not 0 < sample_ms <= window_ms or window_ms % sample_ms:
            raise ValueError(
                "window_ms must be a positive multiple of sample_ms."
            )

        self.sample_ms = sample_ms
        self.window_ms = window_ms
        if type(alignment_ms) is not int or not 0 <= alignment_ms < window_ms:
            raise ValueError("alignment_ms must be an integer within one window.")
        self.alignment_ms = alignment_ms


        if max_gap_ms is not None and (
                type(max_gap_ms) is not int or max_gap_ms <= 0):
            raise ValueError("max_gap_ms must be a positive integer.")
        self.gap_ms = 3 * sample_ms if max_gap_ms is None else max_gap_ms

        self.scope = None
        self.session = None
        self.retired = set()
        self.last_seq = -1
        self.last_uptime = -1
        self.last_frame = -1
        self.buffers = {}

        self.counts = {
            "packets": 0,
            "duplicate_or_old": 0,
            "cached_frames": 0,
            "old_sessions": 0,
            "uptime_regressions": 0,
            "windows": 0,
        }

    def _close(self, target_id, reason):
        buffer = self.buffers.pop(target_id)
        points = buffer["points"]
        start = buffer["start"]

        expected = self.window_ms // self.sample_ms


        slots = {
            (point["frame_time_ms"] - start) // self.sample_ms
            for point in points
        }
        coverage = len(slots) / expected

        flags = []

        if len({(p["x"], p["y"]) for p in points}) < 3:
            flags.append("insufficient_distinct_xy")

        if coverage < 0.90:
            flags.append("low_coverage")

        if reason != "window_end":
            flags.append("interrupted_window")

        if any(p["occurred_at"] is None for p in points):
            flags.append("source_clock_unsynced")

        self.counts["windows"] += 1

        return {
            "window_schema_version": "0.1",
            "kind": "trajectory_window",
            "window_id": (
                f"{points[0]['event_id']}:target-{target_id}"
            ),
            "sensor_id": self.scope[0],
            "data_origin": self.scope[1],
            "session_id": self.session,
            "target_id": target_id,


            "profile_id": None,
            "identity_status": "unknown",

            "measurement_profile": "ld6004-target-raw-v1",
            "coordinate_units": "unverified",
            "time_basis": (
                "replay_schedule"
                if self.scope[1] == "replay"
                else "sender_uart_uptime_estimate"
            ),

            "window_start_ms": start,
            "window_end_ms": start + self.window_ms,
            "expected_period_ms": self.sample_ms,
            "max_gap_ms": self.gap_ms,
            "observed_samples": len(points),
            "expected_slots": expected,
            "occupied_slots": len(slots),
            "coverage": coverage,
            "close_reason": reason,
            "quality_flags": flags,


            "ready_for_shape_features": not (set(flags) - {"source_clock_unsynced"}),
            "points": points,
        }

    def _close_all(self, reason):
        return [
            self._close(target_id, reason)
            for target_id in list(self.buffers)
        ]

    def feed(self, event):
        errors = validate_event(event)
        if errors:
            raise ValueError("; ".join(errors))

        scope = (
            event["sensor_id"],
            event["data_origin"],
        )

        if self.scope is not None and scope != self.scope:
            raise ValueError(
                "Use a separate builder for each sensor/origin."
            )

        self.scope = scope
        self.counts["packets"] += 1
        output = []

        session = event["session_id"]

        if session != self.session:
            if session in self.retired:
                self.counts["old_sessions"] += 1
                return []

            if self.session is not None:
                output += self._close_all("session_changed")
                self.retired.add(self.session)

                if len(self.retired) > 128:
                    raise ValueError(
                        "Session limit: start a new input job."
                    )

            self.session = session
            self.last_seq = -1
            self.last_uptime = -1
            self.last_frame = -1


        if event["seq"] <= self.last_seq:
            self.counts["duplicate_or_old"] += 1
            return output

        uptime = event["uptime_ms"]

        if uptime < self.last_uptime:
            self.counts["uptime_regressions"] += 1
            return output + self._close_all(
                "uptime_regression"
            )

        self.last_seq = event["seq"]
        self.last_uptime = uptime

        if event["sensor_status"] != "ok":
            return output + self._close_all(
                "sensor_unhealthy"
            )

        if event["targets_truncated"]:
            return output + self._close_all(
                "targets_truncated"
            )

        if event["frame_age_ms"] > self.gap_ms:
            return output + self._close_all(
                "stale_frame"
            )


        frame_time = uptime - event["frame_age_ms"]

        if frame_time <= self.last_frame:
            self.counts["cached_frames"] += 1
            return output

        self.last_frame = frame_time

        present = {
            target["id"]
            for target in event["targets"]
        }

        for target_id, buffer in list(self.buffers.items()):
            last_time = buffer["points"][-1]["frame_time_ms"]

            if frame_time - last_time > self.gap_ms:
                output.append(
                    self._close(target_id, "observation_gap")
                )

            elif frame_time >= buffer["start"] + self.window_ms:
                output.append(
                    self._close(target_id, "window_end")
                )

            elif target_id not in present:
                output.append(
                    self._close(target_id, "target_missing")
                )

        for target in event["targets"]:
            target_id = target["id"]

            if target_id not in self.buffers:
                self.buffers[target_id] = {
                    "start": (
                        (frame_time - self.alignment_ms) // self.window_ms
                    ) * self.window_ms + self.alignment_ms,
                    "points": [],
                }

            points = self.buffers[target_id]["points"]

            if len(points) >= 5000:
                raise ValueError(
                    "Too many points in one window."
                )

            points.append({
                **target,
                "event_id": event["event_id"],
                "uptime_ms": uptime,
                "frame_age_ms": event["frame_age_ms"],
                "frame_time_ms": frame_time,
                "occurred_at": event["occurred_at"],
                "replay": deepcopy(event["replay"]),
            })

        return output

    def finish(self):

        return self._close_all("end_of_input")


def demo_event(index):
    pass
    uptime = index * 100

    utc = datetime(2026, 1, 1, tzinfo=timezone.utc)
    utc += timedelta(milliseconds=uptime)

    targets = [] if index == 30 else [{
        "id": 1,
        "x": round(index * 0.1, 3),
        "y": round((index % 7) * 0.03, 3),
        "z": 1.3,
        "doppler": 0,
    }]

    return {
        "schema_version": "1.0",
        "event_id": f"demo-radar:demo-session:{index}",
        "source": "pauseable-simulator",
        "data_origin": "simulated",
        "sensor_id": "demo-radar",
        "session_id": "demo-session",
        "seq": index,
        "occurred_at": utc.isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "time_status": "synced",
        "uptime_ms": uptime,
        "measurement_profile": "ld6004-target-raw-v1",
        "sensor_status": "ok",
        "frame_age_ms": 0,
        "target_count": len(targets),
        "targets_truncated": False,
        "targets": targets,
        "replay": None,
    }


def demo(verbose=False):


    builder = TrajectoryWindows(
        sample_ms=100,
        window_ms=1000,
    )

    windows = []

    for index in range(31):
        windows += builder.feed(demo_event(index))

    windows += builder.finish()

    assert len(windows) == 3
    assert all(
        w["observed_samples"] == 10
        for w in windows
    )
    assert all(
        w["ready_for_shape_features"]
        for w in windows
    )


    for window in windows:
        print(json.dumps({
            key: window[key]
            for key in (
                "target_id",
                "data_origin",
                "identity_status",
                "window_start_ms",
                "window_end_ms",
                "observed_samples",
                "coverage",
                "quality_flags",
                "ready_for_shape_features",
            )
        }, ensure_ascii=False))

    if verbose:
        print(json.dumps({"kind": "summary", **builder.counts}), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        help="Original v1 event JSONL",
    )
    parser.add_argument(
        "--sample-ms",
        type=int,
    )
    parser.add_argument(
        "--window-ms",
        type=int,
        default=30000,
    )

    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.input is None:
        demo(args.verbose)
        return

    if args.sample_ms is None:
        parser.error(
            "--input requires the configured --sample-ms."
        )

    builder = TrajectoryWindows(
        args.sample_ms,
        args.window_ms,
    )

    with args.input.open("rb") as handle:
        line_number = 0

        while True:
            line = handle.readline(MAX_PACKET_BYTES + 3)

            if not line:
                break

            line_number += 1
            payload = line.rstrip(b"\r\n")

            if not payload.strip():
                continue

            try:
                windows = builder.feed(
                    parse_event(payload)
                )
            except ValueError as error:
                raise ValueError(
                    f"Line {line_number}: {error}"
                ) from error

            for window in windows:
                print(json.dumps(
                    window,
                    ensure_ascii=False,
                    allow_nan=False,
                ))

    for window in builder.finish():
        print(json.dumps(
            window,
            ensure_ascii=False,
            allow_nan=False,
        ))

    if args.verbose:
        print(json.dumps({"kind": "summary", **builder.counts}), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
