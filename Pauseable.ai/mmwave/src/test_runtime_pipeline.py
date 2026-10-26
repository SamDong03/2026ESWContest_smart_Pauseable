import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from mmwave_pipeline import Flow, assigned
from score_windows import DEFAULT_MODEL, WindowScorer, demo_windows

HERE = Path(__file__).resolve().parent


def window(index, target=1, session="unit-session", origin="simulated", duration=30000):
    result = copy.deepcopy(next(demo_windows()))
    start = index * duration
    result.update(window_id=f"unit:{session}:{index}:{target}",
                  sensor_id="unit-radar", session_id=session, target_id=target,
                  data_origin=origin, window_start_ms=start, window_end_ms=start + duration,
                  expected_period_ms=duration // 10, expected_slots=10,
                  occupied_slots=10, observed_samples=10)
    for i, point in enumerate(result["points"]):
        time = start + i * duration // 10
        point.update(frame_time_ms=time, uptime_ms=time,
                     occurred_at=(datetime(2026, 1, 1, tzinfo=timezone.utc)
                                  + timedelta(milliseconds=time)).isoformat())
    return result


class FixedScorer:
    model_id = "fixed-test-model"

    def score(self, value):
        return {"window_id": value["window_id"], "model_sha256": self.model_id,
                "decision_threshold": 0.66, "feature_schema": "unit-test",
                "status": "scored_research_only" if value["ready_for_shape_features"] else "skipped",
                "quality_flags": list(value["quality_flags"]),
                "rf_shape_score_not_calibrated": 0.9, "alert": False}


class FlowEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.flow = Flow(self.db, FixedScorer())

    def test_shape_without_person_assignment(self):
        rows = [self.flow.process(window(i)) for i in range(3)]
        self.assertEqual(rows[-1]["experimental_decision"], "shape_review_candidate")
        self.assertIsNone(rows[-1]["profile_id"])
        self.assertFalse(rows[-1]["alert"])
        self.assertEqual(self.flow.summary()["usable_records"], 0)

    def test_bad_utc_blocks_personal_not_shape(self):
        for i in range(3):
            item = window(i)
            item["quality_flags"] = ["source_clock_unsynced"]
            for point in item["points"]:
                point["occurred_at"] = None
            result = self.flow.process(item, assigned(item))
        self.assertEqual(result["experimental_decision"], "shape_review_candidate")
        self.assertEqual(result["personal_baseline"]["status"], "record_unavailable")
        self.assertEqual(self.flow.summary()["usable_records"], 0)

    def test_interleaved_targets_do_not_reset_each_other(self):
        for i in range(3):
            for target in (1, 2):
                result = self.flow.process(window(i, target=target))
                if i == 2:
                    self.assertEqual(result["experimental_decision"], "shape_review_candidate")

    def test_duplicate_does_not_inflate_support(self):
        item = window(0)
        first = self.flow.process(item)
        self.assertEqual(first, self.flow.process(item))
        self.assertEqual(self.flow.summary()["stored_windows"], 1)
        self.assertEqual(first["consecutive_windows"]["shape"], 1)

    def test_same_window_different_model_refuses_stale_cached_result(self):
        self.flow.process(window(0))
        self.flow.scorer = FixedScorer()
        self.flow.scorer.model_id = "another-model"
        with self.assertRaisesRegex(ValueError, "model/policy"):
            self.flow.process(window(0))

    def test_same_window_new_baseline_refuses_stale_cached_result(self):
        self.flow.process(window(0))
        self.flow.put("active", "new-baseline-version")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "model/policy"):
            self.flow.process(window(0))

    def test_quality_gap_breaks_evidence(self):
        self.flow.process(window(0))
        item = window(1)
        item.update(ready_for_shape_features=False, quality_flags=["low_coverage"])
        result = self.flow.process(item)
        self.assertEqual(result["experimental_decision"], "insufficient_evidence")
        result = self.flow.process(window(2))
        self.assertEqual(result["consecutive_windows"]["shape"], 1)

    def test_live_cannot_queue_test_alert(self):
        for i in range(3):
            item = window(i, origin="live")
            result = self.flow.process(item, assigned(item), emit_test=True)
        self.assertEqual(result["experimental_decision"], "shape_review_candidate")
        self.assertFalse(result["test_notification_queued"])
        self.assertFalse(result["alert"])
        self.assertEqual(self.flow.summary()["pending_test_notifications"], 0)

    def test_explicit_synthetic_outbox_has_cooldown(self):
        for i in range(4):
            item = window(i)
            self.flow.process(item, assigned(item), emit_test=True)
        self.assertEqual(self.flow.summary()["pending_test_notifications"], 1)

    def test_state_survives_flow_reopen(self):
        self.flow.process(window(0))
        self.flow.process(window(1))
        reopened = Flow(self.db, FixedScorer())
        result = reopened.process(window(2))
        self.assertEqual(result["experimental_decision"], "shape_review_candidate")

    def test_personal_scope_conflict_preserves_shape(self):
        first = window(0)
        self.flow.process(first, assigned(first))
        for i in (1, 2):
            item = window(i)
            assignment = {**assigned(item), "profile_id": "different-person"}
            result = self.flow.process(item, assignment)
        self.assertEqual(result["experimental_decision"], "shape_review_candidate")
        self.assertEqual(result["personal_baseline"]["status"], "record_unavailable")


@unittest.skipUnless(DEFAULT_MODEL.is_file(), "Frozen v2 artifact not installed")
class V2ScorerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scorer = WindowScorer()

    def test_uses_36_features_and_saved_threshold(self):
        from shape_v2.portable_forest import predict_path
        item = window(0)
        result = self.scorer.score(item)
        direct = predict_path(self.scorer.forest, [(p["x"], p["y"]) for p in item["points"]])
        self.assertEqual(result["feature_count"], 36)
        self.assertEqual(result["decision_threshold"], 0.66)
        self.assertEqual(result["rf_shape_score_not_calibrated"], direct["shape_score_not_calibrated"])

    def test_unsynced_can_score_but_missing_observation_cannot(self):
        item = window(0)
        item["quality_flags"] = ["source_clock_unsynced"]
        self.assertEqual(self.scorer.score(item)["status"], "scored_research_only")
        item["quality_flags"].append("interrupted_window")
        result = self.scorer.score(item)
        self.assertEqual(result["status"], "skipped")
        self.assertIsNone(result["rf_shape_score_not_calibrated"])

    def test_cli_stdout_is_only_json_without_banner(self):
        completed = subprocess.run([sys.executable, str(HERE / "score_windows.py")],
                                   capture_output=True, text=True, check=True)
        rows = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(completed.stderr, "")
        self.assertTrue(all(row["data_origin"] == "simulated" for row in rows))


if __name__ == "__main__":
    unittest.main()
