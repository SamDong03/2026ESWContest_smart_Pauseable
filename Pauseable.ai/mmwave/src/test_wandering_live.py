from datetime import datetime, timezone
import json
import os
import unittest

from trajectory_windows import (
    MAX_PACKET_BYTES,
    demo_event,
)
from wandering_contract import build_behavior_payload
from wandering_live import (
    JsonlEventDecoder,
    LiveEnd,
    LiveEvent,
    LiveInputError,
    LiveTimeout,
    run_live_source,
    run_live_stream,
)
from wandering_policy import unknown_result


FIXED_TIME = datetime(
    2026,
    9,
    20,
    1,
    30,
    tzinfo=timezone.utc,
)


def payload(event_id, reason):
    return build_behavior_payload(
        unknown_result(reason),
        event_id=event_id,
        occurred_at=FIXED_TIME,
        observation_count=0,
    )


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ScriptedSource:
    def __init__(self, clock, values):
        self.clock = clock
        self.values = list(values)
        self.timeouts = []

    def receive(self, timeout):
        self.timeouts.append(timeout)
        value = self.values.pop(0)

        if value == "timeout":
            if timeout is None:
                raise AssertionError(
                    "Indefinite wait returned timeout"
                )

            self.clock.advance(timeout)
            return LiveTimeout()

        if isinstance(value, BaseException):
            raise value

        return value


class FakeRuntime:
    def __init__(
        self,
        *,
        process_outputs=None,
        missing_outputs=None,
        finish_outputs=None,
        source_gaps=None,
    ):
        self.process_outputs = list(
            process_outputs or []
        )
        self.missing_outputs = list(
            missing_outputs or []
        )
        self.finish_outputs = list(
            finish_outputs or []
        )
        self.source_gaps = list(
            source_gaps or []
        )
        self.events = []
        self.missing_calls = 0
        self.finish_calls = 0
        self.source_gap_calls = []
        self.missing_occurred_at = []

    def _next(self, values):
        if not values:
            return None

        value = values.pop(0)

        if isinstance(value, BaseException):
            raise value

        return value

    def has_source_gap_before(
        self,
        event,
        *,
        silence_timeout,
    ):
        self.source_gap_calls.append(
            (event, silence_timeout)
        )

        if not self.source_gaps:
            return False

        return self.source_gaps.pop(0)

    def process_event(self, event):
        self.events.append(event)
        return self._next(
            self.process_outputs
        )

    def mark_input_missing(
        self,
        *,
        occurred_at=None,
    ):
        self.missing_calls += 1
        self.missing_occurred_at.append(
            occurred_at
        )
        return self._next(
            self.missing_outputs
        )

    def finish(self):
        self.finish_calls += 1
        return self._next(
            self.finish_outputs
        )


class WanderingLiveTest(unittest.TestCase):
    def test_decoder_accepts_exact_limit_crlf_and_partial_end(self):
        source = demo_event(0)
        raw = json.dumps(
            source,
            separators=(",", ":"),
        ).encode("utf-8")
        padded = raw + b" " * (
            MAX_PACKET_BYTES - len(raw)
        )

        decoder = JsonlEventDecoder()
        events = decoder.feed(
            padded + b"\r\n"
        )

        self.assertEqual(events, [source])
        self.assertEqual(
            decoder.finish(),
            [],
        )

        partial = JsonlEventDecoder()
        self.assertEqual(
            partial.feed(raw),
            [],
        )
        self.assertEqual(
            partial.finish(),
            [source],
        )

    def test_decoder_rejects_malformed_and_oversized_input(self):
        cases = [
            b"{invalid}\n",
            b"x" * (MAX_PACKET_BYTES + 1),
        ]

        for value in cases:
            with self.subTest(length=len(value)):
                decoder = JsonlEventDecoder()

                with self.assertRaises(
                    LiveInputError
                ):
                    decoder.feed(value)

    def test_silence_recovery_and_new_silence_episode(self):
        clock = FakeClock()
        missing_first = payload(
            "evt-live-missing-001",
            "mmwave_data_missing",
        )
        recovered = payload(
            "evt-live-recovered-001",
            "insufficient_evidence",
        )
        missing_second = payload(
            "evt-live-missing-002",
            "mmwave_data_missing",
        )
        runtime = FakeRuntime(
            process_outputs=[recovered],
            missing_outputs=[
                missing_first,
                missing_second,
            ],
        )
        source = ScriptedSource(
            clock,
            [
                "timeout",
                LiveEvent(
                    demo_event(0),
                    received_at=2.0,
                ),
                "timeout",
                LiveEnd(),
            ],
        )
        output = []

        count = run_live_source(
            source,
            runtime,
            silence_timeout=2.0,
            clock=clock,
            output=output.append,
        )

        self.assertEqual(count, 3)
        self.assertEqual(runtime.missing_calls, 2)
        self.assertEqual(runtime.finish_calls, 0)
        self.assertEqual(len(runtime.events), 1)
        self.assertIsNone(
            source.timeouts[1]
        )
        self.assertIsNone(
            source.timeouts[3]
        )
        self.assertEqual(
            [
                json.loads(item)["event_id"]
                for item in output
            ],
            [
                "evt-live-missing-001",
                "evt-live-recovered-001",
                "evt-live-missing-002",
            ],
        )

    def test_end_before_silence_calls_finish(self):
        clock = FakeClock()
        missing = payload(
            "evt-live-end-001",
            "mmwave_data_missing",
        )
        runtime = FakeRuntime(
            finish_outputs=[missing],
        )
        output = []

        count = run_live_source(
            ScriptedSource(
                clock,
                [LiveEnd()],
            ),
            runtime,
            silence_timeout=2.0,
            clock=clock,
            output=output.append,
        )

        self.assertEqual(count, 1)
        self.assertEqual(runtime.finish_calls, 1)
        self.assertEqual(runtime.missing_calls, 0)

    def test_input_error_marks_missing_then_raises(self):
        clock = FakeClock()
        missing = payload(
            "evt-live-error-001",
            "mmwave_data_missing",
        )
        runtime = FakeRuntime(
            missing_outputs=[missing],
        )
        output = []

        with self.assertRaisesRegex(
            LiveInputError,
            "invalid input",
        ):
            run_live_source(
                ScriptedSource(
                    clock,
                    [
                        LiveInputError(
                            "invalid input"
                        )
                    ],
                ),
                runtime,
                silence_timeout=2.0,
                clock=clock,
                output=output.append,
            )

        self.assertEqual(runtime.missing_calls, 1)
        self.assertEqual(runtime.finish_calls, 0)
        self.assertEqual(len(output), 1)

    def test_publish_failure_does_not_emit_missing(self):
        clock = FakeClock()
        runtime = FakeRuntime(
            process_outputs=[
                RuntimeError(
                    "MQTT publish failed"
                )
            ],
            missing_outputs=[
                payload(
                    "evt-live-should-not-send",
                    "mmwave_data_missing",
                )
            ],
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "MQTT publish failed",
        ):
            run_live_source(
                ScriptedSource(
                    clock,
                    [
                        LiveEvent(
                            demo_event(0),
                            received_at=0.0,
                        )
                    ],
                ),
                runtime,
                silence_timeout=2.0,
                clock=clock,
                output=lambda value: None,
            )

        self.assertEqual(runtime.missing_calls, 0)
        self.assertEqual(runtime.finish_calls, 0)

    def test_real_pipe_stream_reads_event_and_end(self):
        read_fd, write_fd = os.pipe()
        source = demo_event(0)

        try:
            os.write(
                write_fd,
                (
                    json.dumps(source)
                    + "\n"
                ).encode("utf-8"),
            )
        finally:
            os.close(write_fd)

        runtime = FakeRuntime(
            process_outputs=[None],
            finish_outputs=[
                payload(
                    "evt-live-pipe-end-001",
                    "mmwave_data_missing",
                )
            ],
        )
        output = []

        with os.fdopen(
            read_fd,
            "rb",
            buffering=0,
        ) as stream:
            count = run_live_stream(
                stream,
                runtime,
                silence_timeout=2.0,
                output=output.append,
            )

        self.assertEqual(count, 1)
        self.assertEqual(
            runtime.events,
            [source],
        )
        self.assertEqual(runtime.finish_calls, 1)

    def test_buffered_source_gap_emits_missing_before_recovery(self):
        clock = FakeClock()
        first = demo_event(0)
        recovered_event = demo_event(12)
        missing = payload(
            "evt-live-buffered-missing-001",
            "mmwave_data_missing",
        )
        recovered = payload(
            "evt-live-buffered-recovered-001",
            "insufficient_evidence",
        )
        runtime = FakeRuntime(
            process_outputs=[
                None,
                recovered,
            ],
            missing_outputs=[missing],
            source_gaps=[
                False,
                True,
            ],
        )
        output = []

        count = run_live_source(
            ScriptedSource(
                clock,
                [
                    LiveEvent(
                        first,
                        received_at=0.0,
                    ),
                    LiveEvent(
                        recovered_event,
                        received_at=0.0,
                    ),
                    LiveEnd(),
                ],
            ),
            runtime,
            silence_timeout=0.4,
            clock=clock,
            output=output.append,
        )

        self.assertEqual(count, 2)
        self.assertEqual(
            runtime.missing_occurred_at,
            [recovered_event["occurred_at"]],
        )
        self.assertEqual(
            [
                json.loads(item)["event_id"]
                for item in output
            ],
            [
                "evt-live-buffered-missing-001",
                "evt-live-buffered-recovered-001",
            ],
        )


if __name__ == "__main__":
    unittest.main()
