from datetime import datetime, timezone
import unittest

from wandering_decision import WanderingDecisionEmitter


FIXED_TIME = datetime(
    2026,
    9,
    20,
    1,
    30,
    tzinfo=timezone.utc,
)


class CapturingPublisher:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.payloads: list[dict[str, object]] = []

    def publish(self, payload: dict[str, object]) -> str:
        self.payloads.append(payload)

        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("publish failed")

        return str(payload["event_id"])


def event(**overrides):
    value = {
        "occurred_at": "2026-09-20T01:30:00.000Z",
        "sensor_status": "ok",
        "frame_age_ms": 0,
        "target_count": 1,
        "targets_truncated": False,
    }
    value.update(overrides)
    return value


def result(
    decision: str = "shape_review_candidate",
    *,
    score: float = 0.83,
):
    return {
        "experimental_decision": decision,
        "status": "scored_research_only",
        "rf_shape_score_not_calibrated": score,
    }


def emitter(publisher):
    return WanderingDecisionEmitter(
        publisher,
        stale_after_ms=1500,
        clock=lambda: FIXED_TIME,
    )


class WanderingDecisionEmitterTest(unittest.TestCase):
    def test_same_state_and_pattern_is_suppressed(self):
        publisher = CapturingPublisher()
        service = emitter(publisher)

        first = service.emit(
            event(),
            result(score=0.83),
            observation_count=30,
            window_seconds=30,
        )
        second = service.emit(
            event(),
            result(score=0.91),
            observation_count=30,
            window_seconds=30,
        )

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(publisher.payloads), 1)

    def test_candidate_to_unknown_transition_is_published(self):
        publisher = CapturingPublisher()
        service = emitter(publisher)

        service.emit(
            event(),
            result(),
            observation_count=30,
            window_seconds=30,
        )
        payload = service.emit(
            event(target_count=0),
            None,
            observation_count=0,
        )

        self.assertEqual(len(publisher.payloads), 2)
        self.assertEqual(payload["behavior"], "unknown")
        self.assertEqual(payload["risk_level"], "unknown")
        self.assertIsNone(payload["risk_score"])
        self.assertEqual(
            payload["inference_status"],
            "insufficient_data",
        )

    def test_insufficient_data_to_sensor_error_is_published(self):
        publisher = CapturingPublisher()
        service = emitter(publisher)

        service.emit(
            event(target_count=0),
            None,
            observation_count=0,
        )
        payload = service.emit(
            event(
                sensor_status="disconnected",
                frame_age_ms=None,
                target_count=0,
            ),
            None,
            observation_count=0,
        )

        self.assertEqual(len(publisher.payloads), 2)
        self.assertEqual(
            payload["inference_status"],
            "sensor_error",
        )
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "mmwave_sensor_disconnected",
        )

    def test_out_of_order_result_is_not_published(self):
        publisher = CapturingPublisher()
        service = emitter(publisher)

        payload = service.emit(
            event(),
            result("out_of_order_not_evaluated"),
            observation_count=30,
            window_seconds=30,
        )

        self.assertIsNone(payload)
        self.assertEqual(publisher.payloads, [])

    def test_failed_publish_reuses_pending_event_id(self):
        publisher = CapturingPublisher(failures=1)
        service = emitter(publisher)

        with self.assertRaises(RuntimeError):
            service.emit(
                event(),
                result(),
                observation_count=30,
                window_seconds=30,
            )

        payload = service.emit(
            event(),
            result(),
            observation_count=30,
            window_seconds=30,
        )

        self.assertEqual(len(publisher.payloads), 2)
        self.assertEqual(
            publisher.payloads[0]["event_id"],
            publisher.payloads[1]["event_id"],
        )
        self.assertEqual(
            payload["event_id"],
            publisher.payloads[0]["event_id"],
        )

    def test_missing_input_is_published_as_unknown(self):
        publisher = CapturingPublisher()
        service = emitter(publisher)

        payload = service.emit(
            None,
            None,
            input_missing=True,
            observation_count=0,
        )

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
        self.assertEqual(
            payload["occurred_at"],
            "2026-09-20T01:30:00.000Z",
        )


if __name__ == "__main__":
    unittest.main()
