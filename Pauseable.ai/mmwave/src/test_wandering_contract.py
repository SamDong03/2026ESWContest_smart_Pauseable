from datetime import datetime, timezone
import json
import re
import unittest

from wandering_contract import (
    build_behavior_payload,
    serialize_behavior_payload,
    validate_behavior_payload,
)
from wandering_policy import classify_wandering


def event(**overrides):
    value = {
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
    status="scored_research_only",
    score=0.83,
):
    return {
        "experimental_decision": decision,
        "status": status,
        "rf_shape_score_not_calibrated": score,
    }


FIXED_TIME = datetime(
    2026,
    9,
    20,
    1,
    30,
    tzinfo=timezone.utc,
)


class WanderingContractTest(unittest.TestCase):
    def candidate_classification(self):
        return classify_wandering(
            event(),
            result(),
            stale_after_ms=1500,
        )

    def test_candidate_payload_matches_schema(self):
        payload = build_behavior_payload(
            self.candidate_classification(),
            event_id="evt-wandering-contract-001",
            occurred_at=FIXED_TIME,
            observation_count=30,
            window_seconds=30,
            model_version="mmwave-shape-v2",
            reason_text=(
                "Persistent path-shape evidence requires review. "
                "The score is not a wandering probability."
            ),
        )

        validate_behavior_payload(payload)

        self.assertEqual(
            payload["contract_version"],
            "1.0",
        )
        self.assertEqual(
            payload["source"],
            "wandering-ai",
        )
        self.assertEqual(
            payload["behavior"],
            "wandering",
        )
        self.assertEqual(
            payload["risk_level"],
            "caution",
        )
        self.assertEqual(payload["risk_score"], 83)
        self.assertEqual(
            payload["inference_status"],
            "ok",
        )
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "shape_review_candidate",
        )
        self.assertEqual(
            payload["evidence"]["model_status"],
            "research_only_unvalidated",
        )

    def test_missing_input_payload_is_unknown(self):
        classification = classify_wandering(
            None,
            None,
            input_missing=True,
            stale_after_ms=1500,
        )

        payload = build_behavior_payload(
            classification,
            event_id="evt-wandering-missing-001",
            occurred_at=FIXED_TIME,
            observation_count=0,
            reason_text="No mmWave event was received.",
        )

        validate_behavior_payload(payload)

        self.assertEqual(
            payload["behavior"],
            "unknown",
        )
        self.assertEqual(
            payload["risk_level"],
            "unknown",
        )
        self.assertIsNone(payload["risk_score"])
        self.assertEqual(
            payload["inference_status"],
            "insufficient_data",
        )
        self.assertEqual(
            payload["evidence"]["pattern_code"],
            "mmwave_data_missing",
        )

    def test_sensor_error_payload_matches_schema(self):
        classification = classify_wandering(
            event(
                sensor_status="error",
                frame_age_ms=None,
                target_count=0,
            ),
            None,
            stale_after_ms=1500,
        )

        payload = build_behavior_payload(
            classification,
            event_id="evt-wandering-sensor-error-001",
            occurred_at=FIXED_TIME,
            observation_count=0,
            reason_text="The mmWave sensor reported an error.",
        )

        validate_behavior_payload(payload)

        self.assertEqual(
            payload["behavior"],
            "unknown",
        )
        self.assertEqual(
            payload["risk_level"],
            "unknown",
        )
        self.assertIsNone(payload["risk_score"])
        self.assertEqual(
            payload["inference_status"],
            "sensor_error",
        )

    def test_supplied_event_id_is_preserved(self):
        event_id = "evt-retry-stable-001"

        first = build_behavior_payload(
            self.candidate_classification(),
            event_id=event_id,
            occurred_at=FIXED_TIME,
            observation_count=30,
            window_seconds=30,
        )

        second = build_behavior_payload(
            self.candidate_classification(),
            event_id=event_id,
            occurred_at=FIXED_TIME,
            observation_count=30,
            window_seconds=30,
        )

        self.assertEqual(first["event_id"], event_id)
        self.assertEqual(second["event_id"], event_id)
        self.assertEqual(
            serialize_behavior_payload(first),
            serialize_behavior_payload(second),
        )

    def test_event_id_is_created_when_omitted(self):
        payload = build_behavior_payload(
            self.candidate_classification(),
            occurred_at=FIXED_TIME,
            observation_count=30,
            window_seconds=30,
        )

        self.assertRegex(
            payload["event_id"],
            r"^evt-[0-9a-f-]{36}$",
        )

    def test_timezone_is_converted_to_utc(self):
        payload = build_behavior_payload(
            self.candidate_classification(),
            event_id="evt-timezone-test-001",
            occurred_at="2026-09-20T10:30:00+09:00",
            observation_count=30,
            window_seconds=30,
        )

        self.assertEqual(
            payload["occurred_at"],
            "2026-09-20T01:30:00.000Z",
        )

    def test_unknown_payload_rejects_old_risk_score(self):
        classification = classify_wandering(
            None,
            None,
            input_missing=True,
            stale_after_ms=1500,
        )

        payload = build_behavior_payload(
            classification,
            event_id="evt-invalid-unknown-score-001",
            occurred_at=FIXED_TIME,
        )

        payload["risk_score"] = 83

        with self.assertRaises(ValueError):
            validate_behavior_payload(payload)

    def test_unexpected_field_is_rejected(self):
        payload = build_behavior_payload(
            self.candidate_classification(),
            event_id="evt-extra-field-test-001",
            occurred_at=FIXED_TIME,
            observation_count=30,
            window_seconds=30,
        )

        payload["confidence"] = 0.83

        with self.assertRaises(ValueError):
            validate_behavior_payload(payload)

    def test_serialized_payload_is_valid_json(self):
        payload = build_behavior_payload(
            self.candidate_classification(),
            event_id="evt-json-test-001",
            occurred_at=FIXED_TIME,
            observation_count=30,
            window_seconds=30,
        )

        encoded = serialize_behavior_payload(payload)
        decoded = json.loads(encoded)

        self.assertEqual(decoded, payload)
        self.assertNotIn("NaN", encoded)
        self.assertNotIn("Infinity", encoded)


if __name__ == "__main__":
    unittest.main()
