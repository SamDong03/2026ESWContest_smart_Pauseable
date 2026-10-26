import math
import unittest

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


class WanderingPolicyTest(unittest.TestCase):
    def classify(self, raw_event=None, model_result=None, **kwargs):
        return classify_wandering(
            event() if raw_event is None else raw_event,
            result() if model_result is None else model_result,
            stale_after_ms=1500,
            **kwargs,
        )

    def test_shape_candidate_is_caution(self):
        decision = self.classify()

        self.assertEqual(decision["behavior"], "wandering")
        self.assertEqual(decision["risk_level"], "caution")
        self.assertEqual(decision["risk_score"], 83)
        self.assertEqual(decision["inference_status"], "ok")
        self.assertEqual(
            decision["pattern_code"],
            "shape_review_candidate",
        )

    def test_combined_candidate_is_caution_not_danger(self):
        decision = self.classify(
            model_result=result(
                "combined_review_candidate",
                score=0.91,
            )
        )

        self.assertEqual(decision["behavior"], "wandering")
        self.assertEqual(decision["risk_level"], "caution")
        self.assertEqual(decision["risk_score"], 91)
        self.assertNotEqual(decision["risk_level"], "danger")

    def test_missing_input_is_unknown(self):
        decision = classify_wandering(
            None,
            None,
            input_missing=True,
            stale_after_ms=1500,
        )

        self.assertEqual(decision["behavior"], "unknown")
        self.assertEqual(decision["risk_level"], "unknown")
        self.assertIsNone(decision["risk_score"])
        self.assertEqual(
            decision["inference_status"],
            "insufficient_data",
        )

    def test_empty_target_is_not_sensor_error(self):
        decision = self.classify(
            raw_event=event(target_count=0),
            model_result=None,
        )

        self.assertEqual(decision["behavior"], "unknown")
        self.assertEqual(
            decision["inference_status"],
            "insufficient_data",
        )
        self.assertEqual(
            decision["pattern_code"],
            "no_target_observations",
        )
        self.assertIsNone(decision["risk_score"])

    def test_sensor_error_and_disconnection(self):
        cases = {
            "error": "mmwave_sensor_error",
            "disconnected": "mmwave_sensor_disconnected",
        }

        for sensor_status, reason in cases.items():
            with self.subTest(sensor_status=sensor_status):
                decision = self.classify(
                    raw_event=event(
                        sensor_status=sensor_status,
                        frame_age_ms=None,
                        target_count=0,
                    ),
                    model_result=None,
                )

                self.assertEqual(decision["behavior"], "unknown")
                self.assertEqual(decision["risk_level"], "unknown")
                self.assertIsNone(decision["risk_score"])
                self.assertEqual(
                    decision["inference_status"],
                    "sensor_error",
                )
                self.assertEqual(decision["pattern_code"], reason)

    def test_stale_frame_is_insufficient_data(self):
        decision = self.classify(
            raw_event=event(frame_age_ms=1501),
            model_result=None,
        )

        self.assertEqual(decision["behavior"], "unknown")
        self.assertEqual(
            decision["inference_status"],
            "insufficient_data",
        )
        self.assertEqual(
            decision["pattern_code"],
            "mmwave_stale_frame",
        )

    def test_personal_change_alone_is_not_wandering(self):
        decision = self.classify(
            model_result=result("personal_change_candidate")
        )

        self.assertEqual(decision["behavior"], "unknown")
        self.assertEqual(decision["risk_level"], "unknown")
        self.assertIsNone(decision["risk_score"])
        self.assertEqual(
            decision["pattern_code"],
            "personal_change_without_shape",
        )

    def test_no_current_rule_flag_is_not_normal(self):
        decision = self.classify(
            model_result=result(
                "no_current_rule_flag",
                score=0.2,
            )
        )

        self.assertEqual(decision["behavior"], "unknown")
        self.assertNotEqual(decision["behavior"], "normal")
        self.assertIsNone(decision["risk_score"])

    def test_invalid_model_score_is_model_error(self):
        for score in (None, True, -0.1, 1.1, math.nan, math.inf):
            with self.subTest(score=score):
                decision = self.classify(
                    model_result=result(score=score)
                )

                self.assertEqual(decision["behavior"], "unknown")
                self.assertEqual(
                    decision["inference_status"],
                    "model_error",
                )
                self.assertIsNone(decision["risk_score"])

    def test_out_of_order_result_is_ignored(self):
        decision = self.classify(
            model_result=result("out_of_order_not_evaluated")
        )

        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
