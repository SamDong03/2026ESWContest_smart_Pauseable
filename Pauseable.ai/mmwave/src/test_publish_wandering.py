from datetime import datetime, timezone
from contextlib import redirect_stderr
import json
from pathlib import Path
import tempfile
import unittest
import io

from publish_wandering import (
    InputEventError,
    announce_live_ready,
    build_parser,
    event_stream,
    live_timeout_for,
    log_window_result,
    run_service,
)
from trajectory_windows import demo_event
from wandering_contract import build_behavior_payload
from wandering_policy import unknown_result


FIXED_TIME = datetime(
    2026,
    9,
    20,
    1,
    30,
    tzinfo=timezone.utc,
)


def unknown_payload(event_id):
    return build_behavior_payload(
        unknown_result("mmwave_data_missing"),
        event_id=event_id,
        occurred_at=FIXED_TIME,
        observation_count=0,
    )


class FakeRuntime:
    def __init__(
        self,
        outputs=None,
        finish_output=None,
    ):
        self.outputs = list(outputs or [])
        self.finish_output = finish_output
        self.events = []
        self.finish_called = False

    def process_event(self, event):
        self.events.append(event)

        if not self.outputs:
            return None

        value = self.outputs.pop(0)

        if isinstance(value, Exception):
            raise value

        return value

    def finish(self):
        self.finish_called = True
        return self.finish_output


class PublishWanderingTest(unittest.TestCase):
    def test_maximum_gap_option_requires_positive_integer_and_preserves_default(self):
        parser = build_parser()
        base = ["--input", "events.jsonl", "--db", "state.sqlite3", "--sample-ms", "200"]
        self.assertIsNone(parser.parse_args(base).max_gap_ms)
        self.assertEqual(parser.parse_args(base + ["--max-gap-ms", "300"]).max_gap_ms, 300)
        for invalid in ("0", "-1", "300.0", "true"):
            with self.subTest(value=invalid), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args(base + ["--max-gap-ms", invalid])
                self.assertEqual(raised.exception.code, 2)

    def test_window_log_reports_cadence_coverage_and_original_gap_diagnostics(self):
        window = {
            "target_id": 1, "window_start_ms": 0, "window_end_ms": 30000,
            "observed_samples": 340, "occupied_slots": 149, "expected_slots": 150,
            "coverage": 149 / 150, "close_reason": "window_end",
            "expected_period_ms": 200, "max_gap_ms": 300,
        }
        output = io.StringIO()
        with redirect_stderr(output):
            log_window_result(window, {"status": "scored_research_only"})
        logged = json.loads(output.getvalue())
        for key, value in window.items():
            self.assertEqual(logged[key], value)
        self.assertEqual(logged["status"], "MODEL_WINDOW_RESULT")

    def test_event_stream_reads_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = [
                demo_event(0),
                demo_event(1),
            ]
            path.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in rows
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = list(event_stream(path))

        self.assertEqual(loaded, rows)

    def test_event_stream_reports_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                json.dumps(demo_event(0))
                + "\n"
                + "{invalid}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                InputEventError,
                "Line 2",
            ):
                list(event_stream(path))

    def test_run_service_outputs_published_payloads(self):
        first = unknown_payload(
            "evt-runner-test-001"
        )
        final = unknown_payload(
            "evt-runner-test-002"
        )
        runtime = FakeRuntime(
            outputs=[first, None],
            finish_output=final,
        )
        output = []

        count = run_service(
            [{}, {}],
            runtime,
            output=output.append,
        )

        self.assertEqual(count, 2)
        self.assertTrue(runtime.finish_called)
        self.assertEqual(len(output), 2)
        self.assertEqual(
            json.loads(output[0])["event_id"],
            "evt-runner-test-001",
        )
        self.assertEqual(
            json.loads(output[1])["event_id"],
            "evt-runner-test-002",
        )

    def test_input_error_finishes_as_missing_data(self):
        final = unknown_payload(
            "evt-runner-error-001"
        )
        runtime = FakeRuntime(
            outputs=[None],
            finish_output=final,
        )
        output = []

        def events():
            yield {}
            raise InputEventError("Line 2: invalid")

        with self.assertRaises(InputEventError):
            run_service(
                events(),
                runtime,
                output=output.append,
            )

        self.assertTrue(runtime.finish_called)
        self.assertEqual(len(output), 1)
        self.assertEqual(
            json.loads(output[0])["behavior"],
            "unknown",
        )

    def test_publish_failure_stops_without_finish(self):
        runtime = FakeRuntime(
            outputs=[
                RuntimeError("MQTT publish failed")
            ],
            finish_output=unknown_payload(
                "evt-should-not-publish"
            ),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "MQTT publish failed",
        ):
            run_service(
                [{}, {}, {}],
                runtime,
                output=lambda value: None,
            )

        self.assertEqual(len(runtime.events), 1)
        self.assertFalse(runtime.finish_called)

    def test_stdin_requires_silence_timeout(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--stdin",
                "--db",
                "state.sqlite3",
                "--sample-ms",
                "100",
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "--stdin requires",
        ):
            live_timeout_for(args)

        args = parser.parse_args(
            [
                "--stdin",
                "--db",
                "state.sqlite3",
                "--sample-ms",
                "100",
                "--silence-timeout-seconds",
                "2.5",
            ]
        )

        self.assertEqual(
            live_timeout_for(args),
            2.5,
        )

    def test_file_input_rejects_silence_timeout(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--input",
                "events.jsonl",
                "--db",
                "state.sqlite3",
                "--sample-ms",
                "100",
                "--silence-timeout-seconds",
                "2.5",
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "can only be used with --stdin",
        ):
            live_timeout_for(args)

        args = parser.parse_args(
            [
                "--input",
                "events.jsonl",
                "--db",
                "state.sqlite3",
                "--sample-ms",
                "100",
            ]
        )

        self.assertIsNone(
            live_timeout_for(args)
        )

    def test_live_ready_is_json(self):
        output = io.StringIO()

        announce_live_ready(output)

        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "LIVE_INPUT_READY"},
        )


if __name__ == "__main__":
    unittest.main()
