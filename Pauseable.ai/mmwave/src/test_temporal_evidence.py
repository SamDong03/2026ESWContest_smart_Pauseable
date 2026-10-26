import copy
import math
import unittest

from temporal_evidence import EvidencePolicy, advance_evidence


def window(start, duration=30000, **overrides):
    return {
        "sensor_id": "test-radar",
        "data_origin": "simulated",
        "session_id": "session-a",
        "target_id": 1,
        "time_basis": "sender_uart_uptime_estimate",
        "expected_period_ms": 100,
        "window_start_ms": start,
        "window_end_ms": start + duration,
        **overrides,
    }


def result(score=0.8, **overrides):
    return {
        "decision_threshold": 0.6,
        "status": "scored_research_only",
        "rf_shape_score_not_calibrated": score,
        "model_sha256": "model-a",
        **overrides,
    }


def sequence(scores, *, duration=30000, percentile=None, **kwargs):
    state = {}
    report = None
    for index, score in enumerate(scores):
        state, report = advance_evidence(
            state, window(index * duration, duration), result(score),
            percentile=percentile, **kwargs,
        )
    return state, report


class TemporalEvidenceTest(unittest.TestCase):
    def test_shape_candidate_does_not_require_personal_anomaly(self):
        for percentile in (None, 0.0, 40.0):
            with self.subTest(percentile=percentile):
                state, report = sequence([0.8] * 3, percentile=percentile)
                self.assertEqual(report["experimental_decision"], "shape_review_candidate")
                self.assertTrue(state["shape"]["active"])
                self.assertFalse(state["personal"]["active"])

    def test_personal_candidate_does_not_require_high_shape_score(self):
        state, report = sequence([0.1] * 3, percentile=98.0)
        self.assertEqual(report["experimental_decision"], "personal_change_candidate")
        self.assertFalse(state["shape"]["active"])
        self.assertTrue(state["personal"]["active"])

    def test_combined_candidate_preserves_both_lanes(self):
        state, report = sequence([0.8] * 3, percentile=98.0)
        self.assertEqual(report["experimental_decision"], "combined_review_candidate")
        self.assertTrue(state["shape"]["active"])
        self.assertTrue(state["personal"]["active"])

    def test_onset_requires_count_and_duration(self):
        state, report = sequence([0.8] * 3, duration=1000)
        self.assertFalse(state["shape"]["active"])
        self.assertEqual(state["shape"]["high_windows"], 3)
        self.assertEqual(state["shape"]["high_ms"], 3000)
        state, report = sequence([0.8] * 2, duration=90000)
        self.assertFalse(state["shape"]["active"])
        self.assertEqual(state["shape"]["high_ms"], 180000)
        state, report = sequence([0.8] * 3, duration=30000)
        self.assertTrue(state["shape"]["active"])
        self.assertEqual(state["shape"]["high_ms"], 90000)

    def test_near_threshold_does_not_create_initial_evidence(self):
        state, report = sequence([0.8, 0.55, 0.55, 0.55, 0.8, 0.8])
        self.assertFalse(state["shape"]["active"])
        self.assertEqual(state["shape"]["high_windows"], 2)
        self.assertEqual(state["shape"]["high_ms"], 60000)
        state, _ = sequence([0.55] * 10, percentile=92.0)
        self.assertEqual(state["shape"]["support_ms"], 0)
        self.assertEqual(state["personal"]["support_ms"], 0)
        self.assertFalse(state["personal"]["active"])

    def test_hysteresis_retains_then_releases_active_shape(self):
        state, _ = sequence([0.8] * 3)
        state, report = advance_evidence(state, window(90000), result(0.55))
        self.assertEqual(report["experimental_decision"], "shape_review_candidate")
        self.assertEqual(state["shape"]["high_windows"], 0)
        self.assertEqual(state["shape"]["support_ms"], 120000)
        state, _ = advance_evidence(state, window(120000), result(0.5))
        self.assertTrue(state["shape"]["active"])
        state, report = advance_evidence(state, window(150000), result(0.49))
        self.assertFalse(state["shape"]["active"])
        self.assertEqual(state["shape"]["support_ms"], 0)
        self.assertEqual(report["experimental_decision"], "partial_evidence")

    def test_personal_hysteresis_and_missing_percentile(self):
        state, _ = sequence([0.1] * 3, percentile=98.0)
        state, _ = advance_evidence(state, window(90000), result(0.1), percentile=90.0)
        self.assertTrue(state["personal"]["active"])
        state, _ = advance_evidence(state, window(120000), result(0.1), percentile=89.9)
        self.assertFalse(state["personal"]["active"])
        state, _ = sequence([0.8] * 3, percentile=98.0)
        state, report = advance_evidence(state, window(90000), result(0.8))
        self.assertTrue(state["shape"]["active"])
        self.assertFalse(state["personal"]["active"])
        self.assertEqual(report["experimental_decision"], "shape_review_candidate")

    def test_gap_resets_accumulation(self):
        state, _ = sequence([0.8] * 3, percentile=98.0)
        state, report = advance_evidence(state, window(120000), result(), percentile=98.0)
        self.assertFalse(report["temporal_evidence"]["continuous"])
        self.assertEqual(state["shape"]["high_windows"], 1)
        self.assertFalse(state["shape"]["active"])
        self.assertFalse(state["personal"]["active"])

    def test_invalid_observation_resets_both_lanes(self):
        for score, status in [(None, "skipped"), (0.8, "skipped"), (math.nan, "scored_research_only")]:
            with self.subTest(score=score, status=status):
                state, _ = sequence([0.8] * 3, percentile=98.0)
                state, report = advance_evidence(
                    state, window(90000), result(score, status=status), percentile=98.0,
                )
                self.assertEqual(report["experimental_decision"], "insufficient_evidence")
                self.assertFalse(state["shape"]["active"])
                self.assertFalse(state["personal"]["active"])
                state, _ = advance_evidence(state, window(120000), result())
                self.assertEqual(state["shape"]["high_windows"], 1)

    def test_old_or_overlapping_windows_do_not_mutate_state(self):
        state, _ = sequence([0.8] * 3)
        before = copy.deepcopy(state)
        for start in (0, 60000, 75000):
            returned, report = advance_evidence(state, window(start), result(0.1))
            self.assertIs(returned, state)
            self.assertEqual(returned, before)
            self.assertEqual(report["experimental_decision"], "out_of_order_not_evaluated")

    def test_new_session_can_restart_monotonic_clock(self):
        state, _ = sequence([0.8] * 3)
        state, report = advance_evidence(
            state, window(0, session_id="session-b"), result(),
        )
        self.assertEqual(state["end_ms"], 30000)
        self.assertEqual(state["shape"]["high_windows"], 1)
        self.assertFalse(state["shape"]["active"])
        self.assertEqual(report["temporal_evidence"]["status"], "evaluated")

    def test_model_change_resets_evidence(self):
        for changes in ({"model_sha256": "model-b"}, {"decision_threshold": 0.7}):
            state, _ = sequence([0.8] * 3)
            state, _ = advance_evidence(state, window(90000), result(**changes))
            self.assertFalse(state["shape"]["active"])
            self.assertEqual(state["shape"]["high_windows"], 1)
    def test_baseline_or_profile_change_resets_only_personal_evidence(self):
        for baseline, profile in [("baseline-b", "person-a"), ("baseline-a", "person-b")]:
            state, _ = sequence(
                [0.8] * 3, baseline_version="baseline-a",
                profile_id="person-a", percentile=98.0,
            )
            state, report = advance_evidence(
                state, window(90000), result(),
                baseline_version=baseline, profile_id=profile, percentile=98.0,
            )
            self.assertTrue(state["shape"]["active"])
            self.assertFalse(state["personal"]["active"])
            self.assertEqual(state["personal"]["high_windows"], 1)
            self.assertEqual(report["experimental_decision"], "shape_review_candidate")

    def test_invalid_intervals_and_external_thresholds(self):
        for start, end in [(True, 30000), (0, True), (0.0, 30000), (-1, 30000), (0, 0), (1, 0)]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    advance_evidence({}, window(0, window_start_ms=start, window_end_ms=end), result())
        for threshold in (True, -0.1, 1.1, math.nan, math.inf, "0.6", None):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    advance_evidence({}, window(0), result(decision_threshold=threshold))
        for percentile in (True, -1, 101, math.nan, math.inf, "95"):
            with self.subTest(percentile=percentile):
                with self.assertRaises(ValueError):
                    advance_evidence({}, window(0), result(), percentile=percentile)

    def test_invalid_policy_values(self):
        for config in [
            {"minimum_windows": 0}, {"minimum_windows": True},
            {"minimum_duration_ms": -1}, {"minimum_duration_ms": 1.0},
            {"shape_release_margin": -0.1}, {"shape_release_margin": 1.0},
            {"shape_release_margin": math.nan},
            {"shape_release_margin": False}, {"shape_release_margin": "0.1"},
            {"personal_off": 95.0}, {"personal_on": 101.0},
            {"personal_off": -1}, {"personal_on": math.nan},
            {"personal_off": False}, {"personal_off": "90"},
            {"personal_on": True}, {"personal_on": "95"},
        ]:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    EvidencePolicy(**config)


if __name__ == "__main__":
    unittest.main()
