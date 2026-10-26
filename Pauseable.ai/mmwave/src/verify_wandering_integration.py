from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from wandering_contract import validate_behavior_payload


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SIMULATOR = REPO_ROOT / "Pauseable.edge" / "mmwave-relay" / "simulate.py"
PUBLISHER = HERE / "publish_wandering.py"
TOPIC = "pauseable/ai/wandering/decision"
FILE_TRANSITIONS = [
    (
        "sensor_error",
        "mmwave_sensor_error",
    ),
    (
        "insufficient_data",
        "mmwave_data_missing",
    ),
]

LIVE_TRANSITIONS = [
    (
        "insufficient_data",
        "insufficient_evidence",
    ),
    (
        "insufficient_data",
        "mmwave_data_missing",
    ),
    (
        "insufficient_data",
        "insufficient_evidence",
    ),
    (
        "insufficient_data",
        "mmwave_data_missing",
    ),
]

TEST_MODULES = [
    "test_wandering_policy.py",
    "test_wandering_contract.py",
    "test_wandering_publisher.py",
    "test_wandering_decision.py",
    "test_wandering_runtime.py",
    "test_publish_wandering.py",
    "test_wandering_live.py",
]


def require_command(name: str) -> str:
    path = shutil.which(name)

    if path is None:
        raise RuntimeError(
            f"Required command is not installed: {name}"
        )

    return path


def available_port() -> int:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def stop_process(
    process: subprocess.Popen | None,
) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()

    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=3)


def wait_for_broker(
    process: subprocess.Popen,
    port: int,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.communicate(
                timeout=1
            )[0]
            raise RuntimeError(
                "Temporary MQTT broker exited early:\n"
                + output
            )

        try:
            with socket.create_connection(
                ("127.0.0.1", port),
                timeout=0.2,
            ):
                return
        except OSError:
            time.sleep(0.05)

    raise RuntimeError(
        "Temporary MQTT broker did not start"
    )


def run_unit_tests() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "-v",
            *TEST_MODULES,
        ],
        cwd=HERE,
        check=True,
    )


def validate_messages(
    raw_output: str,
    expected_transitions: list[
        tuple[str, str]
    ],
) -> list[dict]:
    lines = [
        line
        for line in raw_output.splitlines()
        if line.strip()
    ]

    if len(lines) != len(expected_transitions):
        raise RuntimeError(
            "Expected "
            f"{len(expected_transitions)} MQTT messages, "
            f"received {len(lines)}"
        )

    try:
        rows = [
            json.loads(line)
            for line in lines
        ]
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Subscriber returned invalid JSON: {error}"
        ) from error

    for row in rows:
        validate_behavior_payload(row)

        if row["source"] != "wandering-ai":
            raise RuntimeError(
                "Unexpected inference source"
            )

        if (
            row["behavior"] != "unknown"
            or row["risk_level"] != "unknown"
            or row["risk_score"] is not None
        ):
            raise RuntimeError(
                "Missing-data test produced a risk result"
            )

    transitions = [
        (
            row["inference_status"],
            row["evidence"]["pattern_code"],
        )
        for row in rows
    ]

    if transitions != expected_transitions:
        raise RuntimeError(
            "Unexpected MQTT transitions: "
            + repr(transitions)
        )

    event_ids = [
        row["event_id"]
        for row in rows
    ]

    if len(set(event_ids)) != len(event_ids):
        raise RuntimeError(
            "Different transitions reused an event_id"
        )

    return rows

def validate_live_process(
    raw_output: str,
) -> dict:
    ready = False
    summary = None

    for line in raw_output.splitlines():
        if not line.strip():
            continue

        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue

        if value == {
            "status": "LIVE_INPUT_READY"
        }:
            ready = True

        if (
            isinstance(value, dict)
            and "published_messages" in value
        ):
            summary = value

    if not ready:
        raise RuntimeError(
            "Live publisher did not report LIVE_INPUT_READY"
        )

    if summary is None:
        raise RuntimeError(
            "Live publisher did not report a summary"
        )

    if (
        summary.get("published_messages")
        != len(LIVE_TRANSITIONS)
    ):
        raise RuntimeError(
            "Live publisher reported an unexpected "
            "message count"
        )

    if summary.get("input") != "stdin":
        raise RuntimeError(
            "Live publisher did not use stdin"
        )

    return summary


def run_integration() -> None:
    mosquitto = require_command("mosquitto")
    mosquitto_sub = require_command("mosquitto_sub")

    print("[1/7] Running wandering tests", flush=True)
    run_unit_tests()

    with tempfile.TemporaryDirectory(
        prefix="pauseable-wandering-"
    ) as directory:
        temporary = Path(directory)
        port = available_port()
        broker_config = temporary / "mosquitto.conf"
        input_path = temporary / "sensor-error.jsonl"
        database_path = temporary / "wandering.sqlite3"
        live_database_path = (
            temporary / "live-wandering.sqlite3"
        )

        broker_config.write_text(
            "\n".join(
                [
                    f"listener {port} 127.0.0.1",
                    "allow_anonymous true",
                    "persistence false",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        broker = None
        subscriber = None

        try:
            print(
                f"[2/7] Starting temporary MQTT broker on {port}",
                flush=True,
            )

            broker = subprocess.Popen(
                [
                    mosquitto,
                    "-c",
                    str(broker_config),
                    "-v",
                ],
                cwd=temporary,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            wait_for_broker(
                broker,
                port,
            )

            subscriber = subprocess.Popen(
                [
                    mosquitto_sub,
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-t",
                    TOPIC,
                    "-q",
                    "1",
                    "-C",
                    "2",
                ],
                cwd=HERE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            time.sleep(0.5)

            if subscriber.poll() is not None:
                stdout, stderr = subscriber.communicate(
                    timeout=1
                )
                raise RuntimeError(
                    "MQTT subscriber exited early:\n"
                    + stdout
                    + stderr
                )

            print(
                "[3/7] Generating file input and publishing",
                flush=True,
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SIMULATOR),
                    "--scenario",
                    "sensor-error",
                    "--count",
                    "3",
                    "--interval-ms",
                    "1",
                    "--output",
                    str(input_path),
                    "--quiet",
                ],
                cwd=HERE,
                check=True,
            )

            environment = os.environ.copy()
            environment.pop("MQTT_USER", None)
            environment.pop("MQTT_PASSWORD", None)
            environment.update(
                {
                    "MQTT_HOST": "127.0.0.1",
                    "MQTT_PORT": str(port),
                    "MQTT_CLIENT_ID": (
                        "pauseable-wandering-verify-"
                        + uuid.uuid4().hex[:12]
                    ),
                }
            )

            published = subprocess.run(
                [
                    sys.executable,
                    str(PUBLISHER),
                    "--input",
                    str(input_path),
                    "--db",
                    str(database_path),
                    "--sample-ms",
                    "100",
                    "--window-ms",
                    "30000",
                ],
                cwd=HERE,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if published.stdout:
                print(
                    published.stdout,
                    end="",
                )

            if published.stderr:
                print(
                    published.stderr,
                    end="",
                    file=sys.stderr,
                )

            if published.returncode != 0:
                raise RuntimeError(
                    "Publisher exited with code "
                    f"{published.returncode}"
                )

            try:
                subscriber_output, subscriber_error = (
                    subscriber.communicate(timeout=10)
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    "Subscriber did not receive 2 messages"
                ) from error

            if subscriber.returncode != 0:
                raise RuntimeError(
                    "Subscriber failed:\n"
                    + subscriber_error
                )

            print(
                "[4/7] Validating file MQTT messages",
                flush=True,
            )

            file_rows = validate_messages(
                subscriber_output,
                FILE_TRANSITIONS,
            )
            subscriber = None

            print(
                "[5/7] Generating buffered live input",
                flush=True,
            )

            simulated = subprocess.run(
                [
                    sys.executable,
                    str(SIMULATOR),
                    "--scenario",
                    "silence",
                    "--count",
                    "9",
                    "--interval-ms",
                    "200",
                    "--dry-run",
                ],
                cwd=HERE,
                capture_output=True,
                text=True,
                timeout=15,
            )

            if simulated.stderr:
                print(
                    simulated.stderr,
                    end="",
                    file=sys.stderr,
                )

            if simulated.returncode != 0:
                raise RuntimeError(
                    "Live simulator exited with code "
                    f"{simulated.returncode}"
                )

            live_input_lines = [
                line
                for line in simulated.stdout.splitlines()
                if line.strip()
            ]

            if len(live_input_lines) != 6:
                raise RuntimeError(
                    "Expected 6 buffered input events, "
                    f"received {len(live_input_lines)}"
                )

            live_input = (
                "\n".join(live_input_lines)
                + "\n"
            )

            subscriber = subprocess.Popen(
                [
                    mosquitto_sub,
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-t",
                    TOPIC,
                    "-q",
                    "1",
                    "-C",
                    str(len(LIVE_TRANSITIONS)),
                ],
                cwd=HERE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            time.sleep(0.5)

            if subscriber.poll() is not None:
                stdout, stderr = subscriber.communicate(
                    timeout=1
                )
                raise RuntimeError(
                    "Live MQTT subscriber exited early:\n"
                    + stdout
                    + stderr
                )

            environment["MQTT_CLIENT_ID"] = (
                "pauseable-wandering-live-verify-"
                + uuid.uuid4().hex[:12]
            )

            print(
                "[6/7] Publishing buffered live input",
                flush=True,
            )

            live_published = subprocess.run(
                [
                    sys.executable,
                    str(PUBLISHER),
                    "--stdin",
                    "--silence-timeout-seconds",
                    "0.4",
                    "--db",
                    str(live_database_path),
                    "--sample-ms",
                    "100",
                    "--window-ms",
                    "30000",
                ],
                cwd=HERE,
                env=environment,
                input=live_input,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if live_published.stdout:
                print(
                    live_published.stdout,
                    end="",
                )

            if live_published.stderr:
                print(
                    live_published.stderr,
                    end="",
                    file=sys.stderr,
                )

            if live_published.returncode != 0:
                raise RuntimeError(
                    "Live publisher exited with code "
                    f"{live_published.returncode}"
                )

            validate_live_process(
                live_published.stderr
            )

            try:
                live_subscriber_output, live_subscriber_error = (
                    subscriber.communicate(timeout=15)
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    "Live subscriber did not receive "
                    f"{len(LIVE_TRANSITIONS)} messages"
                ) from error

            if subscriber.returncode != 0:
                raise RuntimeError(
                    "Live subscriber failed:\n"
                    + live_subscriber_error
                )

            print(
                "[7/7] Validating live MQTT messages",
                flush=True,
            )

            live_rows = validate_messages(
                live_subscriber_output,
                LIVE_TRANSITIONS,
            )

            print(
                json.dumps(
                    {
                        "status": "AUTOMATION_OK",
                        "tests": len(TEST_MODULES),
                        "file_mqtt_messages": len(
                            file_rows
                        ),
                        "live_mqtt_messages": len(
                            live_rows
                        ),
                        "mqtt_messages": (
                            len(file_rows)
                            + len(live_rows)
                        ),
                        "topic": TOPIC,
                        "port": port,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        finally:
            stop_process(subscriber)
            stop_process(broker)


def main() -> int:
    try:
        run_integration()
        return 0
    except KeyboardInterrupt:
        print(
            "AUTOMATION INTERRUPTED",
            file=sys.stderr,
        )
        return 130
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"AUTOMATION FAILED: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
