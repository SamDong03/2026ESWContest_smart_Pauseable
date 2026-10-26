import copy
import unittest

from rolling_windows import RollingTrajectoryWindows
from trajectory_windows import demo_event
from temporal_evidence import advance_evidence
from test_temporal_evidence import result, window


def frame(index):
    value = demo_event(index)
    value["targets"] = [{"id": 1, "x": index / 100, "y": (index % 9) / 100,
                         "z": 1.3, "doppler": 0}]
    value["target_count"] = 1
    return value


class RollingWindowsTest(unittest.TestCase):
    def test_gap_override_reaches_every_phase_without_changing_defaults(self):
        builder = RollingTrajectoryWindows(200, 30000, 10000, max_gap_ms=300)
        self.assertEqual([phase.gap_ms for phase in builder.builders], [300] * 3)
        defaults = RollingTrajectoryWindows(200, 30000, 10000)
        self.assertEqual([phase.gap_ms for phase in defaults.builders], [600] * 3)
        for index in range(4):
            event = frame(index)
            event["uptime_ms"] = index * 200
            builder.feed(event)
        event = frame(4)
        event["uptime_ms"] = 901
        output = builder.feed(event)
        self.assertTrue(output)
        self.assertTrue(all(w["close_reason"] == "observation_gap" for w in output))
        self.assertTrue(all(not w["ready_for_shape_features"] for w in output))

    def test_irregular_realistic_cadence_keeps_original_points_and_gap_protection(self):
        builder = RollingTrajectoryWindows(200, 30000, 10000, max_gap_ms=300)
        old_slots = RollingTrajectoryWindows(100, 30000, 10000, max_gap_ms=300)
        original = {}
        output, old_output = [], []
        uptime, index = 0, 0
        intervals = (65, 65, 146)
        while uptime <= 91000:
            event = frame(index)
            event["uptime_ms"] = uptime
            original[event["event_id"]] = copy.deepcopy(event)
            output.extend(builder.feed(event))
            old_output.extend(old_slots.feed(event))
            self.assertEqual(event, original[event["event_id"]])
            uptime += intervals[index % len(intervals)]
            index += 1
        self.assertEqual([w["window_end_ms"] for w in output], list(range(30000, 90001, 10000)))
        self.assertTrue(all(w["coverage"] >= 0.90 and w["ready_for_shape_features"] for w in output))
        self.assertTrue(any("low_coverage" in w["quality_flags"] for w in old_output))
        for item in output:
            self.assertEqual(item["expected_slots"], 150)
            self.assertEqual(item["expected_period_ms"], 200)
            for point in item["points"]:
                source = original[point["event_id"]]
                self.assertEqual(point["frame_time_ms"], source["uptime_ms"])
                for key in ("x", "y", "z", "doppler"):
                    self.assertEqual(point[key], source["targets"][0][key])

    def test_full_windows_every_ten_seconds_with_original_points(self):
        builder = RollingTrajectoryWindows(100, 30000, 10000)
        output = []
        original = {}
        for index in range(901):
            event = frame(index)
            original[event["event_id"]] = copy.deepcopy(event)
            output.extend(builder.feed(event))
            self.assertEqual(event, original[event["event_id"]])
        self.assertEqual([w["window_end_ms"] for w in output], list(range(30000, 90001, 10000)))
        self.assertEqual(len({w["window_id"] for w in output}), 7)
        self.assertEqual(builder.counts["packets"], 901)
        for item in output:
            self.assertEqual(item["occupied_slots"], 300)
            self.assertTrue(item["ready_for_shape_features"])
            for point in item["points"]:
                source = original[point["event_id"]]
                self.assertEqual(point["uptime_ms"], source["uptime_ms"])
                self.assertEqual(point["occurred_at"], source["occurred_at"])
                for key in ("x", "y", "z", "doppler"):
                    self.assertEqual(point[key], source["targets"][0][key])

    def test_session_and_target_loss_preserve_quality_gates(self):
        builder = RollingTrajectoryWindows(100, 30000, 10000)
        for index in range(10):
            builder.feed(frame(index))
        lost = frame(10)
        lost.update(target_count=0, targets=[])
        output = builder.feed(lost)
        self.assertTrue(output)
        self.assertTrue(all("interrupted_window" in w["quality_flags"] for w in output))
        self.assertTrue(all(not w["ready_for_shape_features"] for w in output))
        old = frame(9)
        self.assertEqual(builder.feed(old), [])
        self.assertEqual(builder.counts["duplicate_or_old"], 1)

    def test_overlap_does_not_achieve_ninety_seconds_in_three_windows(self):
        state = {}
        for index in range(7):
            state, report = advance_evidence(state, window(index * 10000, window_step_ms=10000), result())
            self.assertEqual(state["shape"]["high_ms"], 30000 + index * 10000)
            self.assertEqual(state["shape"]["active"], index == 6)
        self.assertEqual(report["experimental_decision"], "shape_review_candidate")

    def test_gap_invalid_result_and_duplicate_cannot_extend_evidence(self):
        state, _ = advance_evidence({}, window(0, window_step_ms=10000), result())
        same, report = advance_evidence(state, window(0, window_step_ms=10000), result())
        self.assertEqual(same, state)
        self.assertEqual(report["experimental_decision"], "out_of_order_not_evaluated")
        state, _ = advance_evidence(state, window(20000, window_step_ms=10000), result())
        self.assertEqual(state["shape"]["high_ms"], 30000)
        state, _ = advance_evidence(state, window(30000, window_step_ms=10000), result(status="skipped"))
        self.assertEqual(state["shape"]["high_ms"], 0)
        state, _ = advance_evidence(state, window(40000, window_step_ms=10000), result())
        self.assertEqual(state["shape"]["high_ms"], 30000)


if __name__ == "__main__":
    unittest.main()
