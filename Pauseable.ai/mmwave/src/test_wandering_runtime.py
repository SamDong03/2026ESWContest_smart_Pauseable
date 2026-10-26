from datetime import datetime, timezone
import unittest

from wandering_decision import WanderingDecisionEmitter
from wandering_runtime import STATE_KEY, WanderingRuntime


FIXED_TIME = datetime(
    2026,
    9,
    20,
    1,
    30,
    tzinfo=timezone.utc,
)


class FakeDatabase:
    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False


class FakeFlow:
    def __init__(self, stored_signature=None):
        self.db = FakeDatabase()
        self.meta = {}

        if stored_signature is not None:
            self.meta[STATE_KEY] = stored_signature

    def get(self, key, default=None):
        return self.meta.get(key, default)

    def put(self, key, value):
        self.meta[key] = value

    def process(
        self,
        window,
        assignment=None,
        emit_test=False,
    ):
        return window["result"]


class FakeBuilder:
    def __init__(
        self,
        outputs=None,
        final_windows=None,
    ):
        self.outputs = list(outputs or [])
        self.final_windows = list(final_windows or [])
        self.counts = {
            "duplicate_or_old": 0,
        }
        self.scope = None
        self.session = None
        self.last_seq = -1
        self.last_uptime = -1

    def feed(self, event):
        if not self.outputs:
            return []

        return self.outputs.pop(0)

    def finish(self):
        return self.final_windows


class CapturingPublisher:
    def __init__(self):
        self.payloads = []

    def publish(self, payload):
        self.payloads.append(payload)
        return payload["event_id"]


class RuntimeGapConfigurationTest(unittest.TestCase):
    def test_gap_override_reaches_both_runtime_builder_modes(self):
        for step_ms in (None, 30000, 10000):
            with self.subTest(step_ms=step_ms):
                publisher = CapturingPublisher()
                emitter = WanderingDecisionEmitter(publisher, stale_after_ms=300)
                runtime = WanderingRuntime(FakeFlow(), emitter, sample_ms=200,
                                          window_ms=30000, step_ms=step_ms,
                                          max_gap_ms=300)
                self.assertEqual(runtime.builder.gap_ms, 300)
                self.assertEqual(runtime.emitter.stale_after_ms, 300)
                if step_ms == 10000:
                    self.assertEqual([phase.gap_ms for phase in runtime.builder.builders],
                                     [300] * 3)


def event(**overrides):
    value = {
        "occurred_at": "2026-09-20T01:30:00.000Z",
        "session_id": "session-1",
        "sensor_status": "ok",
        "frame_age_ms": 0,
        "target_count": 1,
        "targets_truncated": False,
    }
    value.update(overrides)
    return value


def result(
    decision="shape_review_candidate",
    *,
    score=0.83,
    status="scored_research_only",
):
    return {
        "experimental_decision": decision,
        "status": status,
        "rf_shape_score_not_calibrated": score,
        "model_sha256": "a" * 64,
    }


def window(
    decision="shape_review_candidate",
    *,
    score=0.83,
    status="scored_research_only",
    window_id="window-1",
):
    return {
        "window_id": window_id,
        "window_start_ms": 0,
        "window_end_ms": 30000,
        "observed_samples": 30,
        "occupied_slots": 30,
        "result": result(
            decision,
            score=score,
            status=status,
        ),
    }


def service(
    outputs=None,
    *,
    final_windows=None,
    stored_signature=None,
):
    publisher = CapturingPublisher()
    emitter = WanderingDecisionEmitter(
        publisher,
        stale_after_ms=1500,
        clock=lambda: FIXED_TIME,
    )
    flow = FakeFlow(stored_signature)
    runtime = WanderingRuntime(
        flow,
        emitter,
        sample_ms=500,
        window_ms=30000,
        builder=FakeBuilder(
            outputs,
            final_windows,
        ),
    )
    return runtime, publisher, flow


class WanderingRuntimeTest(unittest.TestCase):
    def test_first_healthy_frame_is_insufficient_data(self):
        runtime, publisher, flow = service([[]])

        payload = runtime.process_event(event())

        self.assertEqual(len(publisher.payloads), 1)
        self.assertEqual(payload["behavior"], "unknown")
        self.assertEqual(
            payload["inference_status"],
            "insufficient_data",
        )
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "insufficient_evidence",
        )
        self.assertEqual(
            flow.meta[STATE_KEY],
            [
                "unknown",
                "unknown",
                "insufficient_data",
                "insufficient_evidence",
            ],
        )

    def test_candidate_is_not_reset_while_next_window_builds(self):
        runtime, publisher, flow = service(
            [
                [window()],
                [],
            ]
        )

        first = runtime.process_event(event())
        second = runtime.process_event(event())

        self.assertEqual(first["behavior"], "wandering")
        self.assertIsNone(second)
        self.assertEqual(len(publisher.payloads), 1)

    def test_no_target_after_candidate_publishes_unknown(self):
        runtime, publisher, flow = service(
            [
                [window()],
                [],
            ]
        )

        runtime.process_event(event())
        payload = runtime.process_event(
            event(target_count=0)
        )

        self.assertEqual(len(publisher.payloads), 2)
        self.assertEqual(payload["behavior"], "unknown")
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "no_target_observations",
        )

    def test_candidate_wins_over_insufficient_target(self):
        runtime, publisher, flow = service(
            [
                [
                    window(
                        "insufficient_evidence",
                        score=None,
                        status="skipped",
                        window_id="window-1",
                    ),
                    window(
                        "shape_review_candidate",
                        score=0.78,
                        window_id="window-2",
                    ),
                ]
            ]
        )

        payload = runtime.process_event(event())

        self.assertEqual(payload["behavior"], "wandering")
        self.assertEqual(payload["risk_level"], "caution")
        self.assertEqual(payload["risk_score"], 78)

    def test_sensor_error_has_priority(self):
        runtime, publisher, flow = service(
            [
                [window()]
            ]
        )

        payload = runtime.process_event(
            event(
                sensor_status="error",
                frame_age_ms=None,
                target_count=0,
            )
        )

        self.assertEqual(payload["behavior"], "unknown")
        self.assertEqual(
            payload["inference_status"],
            "sensor_error",
        )
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "mmwave_sensor_error",
        )

    def test_out_of_order_window_is_ignored(self):
        runtime, publisher, flow = service(
            [
                [
                    window(
                        "out_of_order_not_evaluated",
                    )
                ]
            ]
        )

        payload = runtime.process_event(event())

        self.assertIsNone(payload)
        self.assertEqual(publisher.payloads, [])

    def test_session_change_clears_candidate(self):
        runtime, publisher, flow = service(
            [
                [window()],
                [],
            ]
        )

        runtime.process_event(event())
        payload = runtime.process_event(
            event(session_id="session-2")
        )

        self.assertEqual(len(publisher.payloads), 2)
        self.assertEqual(payload["behavior"], "unknown")
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "insufficient_evidence",
        )

    def test_stored_signature_suppresses_restart_duplicate(self):
        stored = [
            "wandering",
            "caution",
            "ok",
            "shape_review_candidate",
        ]
        runtime, publisher, flow = service(
            [[window()]],
            stored_signature=stored,
        )

        payload = runtime.process_event(event())

        self.assertIsNone(payload)
        self.assertEqual(publisher.payloads, [])

    def test_end_of_input_publishes_missing_data(self):
        runtime, publisher, flow = service([])

        payload = runtime.finish()

        self.assertEqual(payload["behavior"], "unknown")
        self.assertEqual(payload["risk_level"], "unknown")
        self.assertIsNone(payload["risk_score"])
        self.assertEqual(
            payload["inference_status"],
            "insufficient_data",
        )
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "mmwave_data_missing",
        )

    def test_source_gap_requires_same_monotonic_stream(self):
        runtime, publisher, flow = service([])
        runtime.builder.scope = (
            "test-radar",
            "simulated",
        )
        runtime.builder.session = "session-1"
        runtime.builder.last_seq = 2
        runtime.builder.last_uptime = 400
        candidate = event(
            sensor_id="test-radar",
            data_origin="simulated",
            seq=6,
            uptime_ms=1200,
        )

        self.assertTrue(
            runtime.has_source_gap_before(
                candidate,
                silence_timeout=0.4,
            )
        )

        self.assertFalse(
            runtime.has_source_gap_before(
                {
                    **candidate,
                    "seq": 2,
                    "uptime_ms": 5000,
                },
                silence_timeout=0.4,
            )
        )

        self.assertFalse(
            runtime.has_source_gap_before(
                {
                    **candidate,
                    "session_id": "session-2",
                },
                silence_timeout=0.4,
            )
        )

        self.assertFalse(
            runtime.has_source_gap_before(
                {
                    **candidate,
                    "uptime_ms": 800,
                },
                silence_timeout=0.4,
            )
        )

    def test_missing_uses_supplied_occurrence_time(self):
        runtime, publisher, flow = service([])
        occurred_at = "2026-09-20T01:30:01.200Z"

        payload = runtime.mark_input_missing(
            occurred_at=occurred_at
        )

        self.assertEqual(
            payload["occurred_at"],
            occurred_at,
        )

if __name__ == "__main__":
    unittest.main()
