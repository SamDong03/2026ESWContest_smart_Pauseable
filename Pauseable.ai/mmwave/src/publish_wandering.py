from __future__ import annotations
import math
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable, Iterable, Iterator

from mmwave_pipeline import Flow
from score_windows import DEFAULT_MODEL, WindowScorer
from trajectory_windows import MAX_PACKET_BYTES, parse_event
from wandering_contract import serialize_behavior_payload
from wandering_decision import WanderingDecisionEmitter
from wandering_publisher import (
    PublisherConfig,
    WanderingMqttPublisher,
)
from wandering_runtime import WanderingRuntime
from wandering_live import run_live_stream


class InputEventError(ValueError):
    pass


def event_stream(
    path: Path,
) -> Iterator[dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            line_number = 0

            while True:
                line = handle.readline(
                    MAX_PACKET_BYTES + 3
                )

                if not line:
                    break

                line_number += 1
                payload = line.rstrip(b"\r\n")

                if not payload.strip():
                    continue

                try:
                    yield parse_event(payload)
                except ValueError as error:
                    raise InputEventError(
                        f"Line {line_number}: {error}"
                    ) from error
    except OSError as error:
        raise InputEventError(
            f"Cannot read mmWave input: {error}"
        ) from error


def load_assignments(
    path: Path | None,
) -> dict[str, Any]:
    if path is None:
        return {}

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot load assignments: {error}"
        ) from error

    if not isinstance(value, dict):
        raise ValueError(
            "Assignments root must be an object"
        )

    return value


def write_payload(
    payload: dict[str, Any],
    output: Callable[[str], None],
) -> None:
    output(serialize_behavior_payload(payload))


def run_service(
    events: Iterable[dict[str, Any]],
    runtime: WanderingRuntime,
    *,
    output: Callable[[str], None] = print,
) -> int:
    published = 0

    try:
        for event in events:
            payload = runtime.process_event(event)

            if payload is not None:
                write_payload(payload, output)
                published += 1
    except (InputEventError, KeyboardInterrupt):
        payload = runtime.finish()

        if payload is not None:
            write_payload(payload, output)
            published += 1

        raise

    payload = runtime.finish()

    if payload is not None:
        write_payload(payload, output)
        published += 1

    return published


def positive_gap_ms(value: str) -> int:
    milliseconds = int(value)
    if milliseconds <= 0:
        raise argparse.ArgumentTypeError("--max-gap-ms must be a positive integer")
    return milliseconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    input_mode = parser.add_mutually_exclusive_group(
        required=True
    )
    input_mode.add_argument(
        "--input",
        type=Path,
    )
    input_mode.add_argument(
        "--stdin",
        action="store_true",
    )

    parser.add_argument(
        "--db",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL,
    )
    parser.add_argument(
        "--assignments",
        type=Path,
    )
    parser.add_argument(
        "--sample-ms",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--window-ms",
        type=int,
        default=32000,
    )
    parser.add_argument(
        "--stale-after-ms",
        type=int,
    )
    parser.add_argument(
        "--max-gap-ms",
        type=positive_gap_ms,
        help="Maximum observation gap and frame age; defaults to 3 * sample-ms.",
    )
    parser.add_argument("--step-ms", type=int, default=None,
                        help="Rolling evaluation stride; live 30s windows default to 10s.")
    parser.add_argument(
        "--silence-timeout-seconds",
        type=float,
    )
    parser.add_argument(
        "--trust-local-model",
        action="store_true",
    )
    parser.add_argument(
        "--trust-local-db",
        action="store_true",
    )
    return parser


def live_timeout_for(
    args: argparse.Namespace,
) -> float | None:
    value = args.silence_timeout_seconds

    if args.stdin:
        if value is None:
            raise ValueError(
                "--stdin requires "
                "--silence-timeout-seconds"
            )

        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(
                "--silence-timeout-seconds "
                "must be positive"
            )

        return float(value)

    if value is not None:
        raise ValueError(
            "--silence-timeout-seconds "
            "can only be used with --stdin"
        )

    return None


def announce_live_ready(output=None) -> None:
    stream = sys.stderr if output is None else output

    print(
        json.dumps(
            {"status": "LIVE_INPUT_READY"},
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=stream,
        flush=True,
    )


def log_window_result(window, result):
    print(json.dumps({
        "status": "MODEL_WINDOW_RESULT", "target_id": window["target_id"],
        "window_start_ms": window["window_start_ms"], "window_end_ms": window["window_end_ms"],
        **{key: window.get(key) for key in (
            "observed_samples", "occupied_slots", "expected_slots", "coverage",
            "close_reason", "expected_period_ms", "max_gap_ms",
        )},
        "model_status": result.get("status"), "quality_flags": result.get("quality_flags"),
        "rf_score": result.get("rf_shape_score_not_calibrated"),
        "decision": result.get("experimental_decision"),
        "evidence_ms": result.get("temporal_evidence", {}).get("shape", {}).get("high_ms", 0),
    }, allow_nan=False), file=sys.stderr, flush=True)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        live_timeout = live_timeout_for(args)
    except ValueError as error:
        parser.error(str(error))

    if args.sample_ms <= 0:
        parser.error("--sample-ms must be positive")

    if (
        args.window_ms <= 0
        or args.window_ms % args.sample_ms != 0
    ):
        parser.error(
            "--window-ms must be a positive multiple "
            "of --sample-ms"
        )

    stale_after_ms = (
        3 * args.sample_ms
        if args.stale_after_ms is None
        else args.stale_after_ms
    )

    step_ms = args.step_ms
    if step_ms is None:
        step_ms = 10000 if args.stdin and args.window_ms == 30000 else args.window_ms
    if (step_ms <= 0 or args.window_ms % step_ms or step_ms % args.sample_ms):
        parser.error("--step-ms must divide --window-ms and be a multiple of --sample-ms")

    if stale_after_ms <= 0:
        parser.error(
            "--stale-after-ms must be positive"
        )

    if (
        args.assignments is not None
        and args.db.is_file()
        and not args.trust_local_db
    ):
        parser.error(
            "Existing personal database with assignments "
            "requires --trust-local-db"
        )

    assignments = load_assignments(args.assignments)
    scorer = WindowScorer(
        args.model,
        args.trust_local_model,
    )

    args.db.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        with sqlite3.connect(args.db) as database:
            flow = Flow(database, scorer)

            with WanderingMqttPublisher(
                PublisherConfig.from_env()
            ) as publisher:
                emitter = WanderingDecisionEmitter(
                    publisher,
                    stale_after_ms=stale_after_ms,
                )
                runtime = WanderingRuntime(
                    flow,
                    emitter,
                    sample_ms=args.sample_ms,
                    window_ms=args.window_ms,
                    assignments=assignments,
                    step_ms=step_ms,
                    max_gap_ms=args.max_gap_ms,
                    on_result=log_window_result if args.stdin else None,
                )

                if args.stdin:
                    print(json.dumps({"status": "EVALUATION_CONFIG", "window_ms": args.window_ms,
                                      "sample_ms": args.sample_ms, "max_gap_ms": runtime.builder.gap_ms,
                                      "stale_after_ms": stale_after_ms,
                                      "step_ms": step_ms, "minimum_evidence_ms": 90000}),
                          file=sys.stderr, flush=True)
                    announce_live_ready()

                    published = run_live_stream(
                        sys.stdin.buffer,
                        runtime,
                        silence_timeout=live_timeout,
                    )
                    input_name = "stdin"
                else:
                    published = run_service(
                        event_stream(args.input),
                        runtime,
                    )
                    input_name = str(args.input)

        print(
            json.dumps(
                {
                    "published_messages": published,
                    "input": input_name,
                    "database": str(args.db),
                },
                ensure_ascii=False,
                allow_nan=False,
            ),
            file=sys.stderr,
        )

        return 0

    except KeyboardInterrupt:
        print(
            "ERROR: interrupted",
            file=sys.stderr,
        )
        return 130
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        RuntimeError,
        sqlite3.Error,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
