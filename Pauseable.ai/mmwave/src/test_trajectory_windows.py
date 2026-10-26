import unittest

from trajectory_windows import TrajectoryWindows, demo_event


def event(index, *, session="demo-session", seq=None, uptime=None, synced=True):
    value = demo_event(index)
    value["session_id"] = session
    value["seq"] = index if seq is None else seq
    value["event_id"] = f"demo-radar:{session}:{value['seq']}"
    if uptime is not None:
        value["uptime_ms"] = uptime
    if not synced:
        value.update(time_status="unsynced", occurred_at=None)
    return value


class TrajectoryWindowsTest(unittest.TestCase):
    def test_timing_requires_positive_integer_multiples(self):
        for sample, window in [
            (True, 1000), (100, True), (100.0, 1000), (100, 1000.0),
            ("100", 1000), (None, 1000), (0, 1000), (-1, 1000),
            (100, 0), (100, -1000), (2000, 1000), (300, 1000),
        ]:
            with self.subTest(sample=sample, window=window):
                with self.assertRaises(ValueError):
                    TrajectoryWindows(sample, window)
        self.assertEqual(TrajectoryWindows(100).window_ms, 30000)

    def test_gap_defaults_are_backward_compatible_and_override_is_positive_integer(self):
        self.assertEqual(TrajectoryWindows(100).gap_ms, 300)
        self.assertEqual(TrajectoryWindows(200).gap_ms, 600)
        self.assertEqual(TrajectoryWindows(200, max_gap_ms=300).gap_ms, 300)
        for invalid in (True, 0, -1, 300.0, "300"):
            with self.subTest(max_gap_ms=invalid):
                with self.assertRaises(ValueError):
                    TrajectoryWindows(200, max_gap_ms=invalid)

    def test_coarser_slots_keep_explicit_observation_gap_limit(self):
        builder = TrajectoryWindows(200, 1000, max_gap_ms=300)
        for index in range(4):
            builder.feed(event(index, uptime=index * 200))
        interrupted = builder.feed(event(4, uptime=901))
        self.assertEqual(interrupted[0]["close_reason"], "observation_gap")
        self.assertFalse(interrupted[0]["ready_for_shape_features"])
        self.assertEqual(builder.buffers[1]["points"][0]["frame_time_ms"], 901)

    def test_coarser_slots_keep_explicit_stale_frame_limit(self):
        builder = TrajectoryWindows(200, 1000, max_gap_ms=300)
        for index in range(4):
            builder.feed(event(index, uptime=index * 200))
        stale = event(4, uptime=1000)
        stale["frame_age_ms"] = 301
        interrupted = builder.feed(stale)
        self.assertEqual(interrupted[0]["close_reason"], "stale_frame")
        self.assertFalse(interrupted[0]["ready_for_shape_features"])
        self.assertEqual(builder.buffers, {})

    def test_exact_gap_limit_does_not_interrupt(self):
        builder = TrajectoryWindows(200, 1000, max_gap_ms=300)
        for index, uptime in enumerate((0, 200, 500)):
            self.assertEqual(builder.feed(event(index, uptime=uptime)), [])
        self.assertEqual(len(builder.buffers[1]["points"]), 3)

    def test_coarser_slots_do_not_lower_ninety_percent_coverage_requirement(self):
        builder = TrajectoryWindows(200, 2000, max_gap_ms=300)
        output = []
        for index in range(2, 11):
            output.extend(builder.feed(event(index, uptime=index * 200)))
        self.assertEqual(output[0]["coverage"], 0.8)
        self.assertIn("low_coverage", output[0]["quality_flags"])
        self.assertFalse(output[0]["ready_for_shape_features"])

    def test_complete_windows_at_absent_target_boundary(self):
        builder = TrajectoryWindows(100, 1000)
        windows = []
        for index in range(31):
            windows.extend(builder.feed(event(index)))
        windows.extend(builder.finish())
        self.assertEqual(len(windows), 3)
        self.assertTrue(all(w["ready_for_shape_features"] for w in windows))
        self.assertEqual([w["occupied_slots"] for w in windows], [10] * 3)
        self.assertEqual([w["window_start_ms"] for w in windows], [0, 1000, 2000])

    def test_unsynced_utc_does_not_block_geometry(self):
        builder = TrajectoryWindows(100, 1000)
        windows = []
        for index in range(11):
            windows.extend(builder.feed(event(index, synced=False)))
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["quality_flags"], ["source_clock_unsynced"])
        self.assertTrue(windows[0]["ready_for_shape_features"])
        self.assertEqual(windows[0]["window_end_ms"], 1000)

    def test_unsynced_utc_does_not_hide_low_coverage(self):
        builder = TrajectoryWindows(100, 1000)
        windows = []
        for index in range(3, 11):
            windows.extend(builder.feed(event(index, synced=False)))
        self.assertIn("source_clock_unsynced", windows[0]["quality_flags"])
        self.assertIn("low_coverage", windows[0]["quality_flags"])
        self.assertFalse(windows[0]["ready_for_shape_features"])

    def test_duplicate_and_old_packets_do_not_add_points(self):
        builder = TrajectoryWindows(100, 1000)
        for index in range(5):
            builder.feed(event(index))
        self.assertEqual(builder.feed(event(4)), [])
        self.assertEqual(builder.feed(event(2)), [])
        self.assertEqual(len(builder.buffers[1]["points"]), 5)
        self.assertEqual(builder.counts["duplicate_or_old"], 2)
        self.assertEqual(builder.last_seq, 4)

    def test_cached_uart_frame_is_not_a_new_observation(self):
        builder = TrajectoryWindows(100, 1000)
        for index in range(5):
            builder.feed(event(index))
        cached = event(5)
        cached["frame_age_ms"] = 100
        self.assertEqual(builder.feed(cached), [])
        self.assertEqual(builder.counts["cached_frames"], 1)
        self.assertEqual(len(builder.buffers[1]["points"]), 5)
        builder.feed(event(6))
        self.assertEqual(len(builder.buffers[1]["points"]), 6)

    def test_rejected_uptime_regression_does_not_poison_sequence(self):
        builder = TrajectoryWindows(100, 1000)
        for index in range(6):
            builder.feed(event(index))
        interrupted = builder.feed(event(1, seq=1000))
        self.assertEqual(interrupted[0]["close_reason"], "uptime_regression")
        self.assertFalse(interrupted[0]["ready_for_shape_features"])
        self.assertEqual(builder.last_seq, 5)
        self.assertEqual(builder.last_uptime, 500)
        builder.feed(event(6))
        self.assertEqual(builder.last_seq, 6)
        self.assertEqual(builder.buffers[1]["points"][0]["uptime_ms"], 600)
        self.assertEqual(builder.counts["duplicate_or_old"], 0)
        self.assertEqual(builder.counts["uptime_regressions"], 1)

    def test_session_switch_closes_old_window_and_rejects_retired_session(self):
        builder = TrajectoryWindows(100, 1000)
        for index in range(5):
            builder.feed(event(index))
        interrupted = builder.feed(event(0, session="second-session"))
        self.assertEqual(interrupted[0]["session_id"], "demo-session")
        self.assertEqual(interrupted[0]["close_reason"], "session_changed")
        self.assertFalse(interrupted[0]["ready_for_shape_features"])
        self.assertEqual(builder.feed(event(5)), [])
        self.assertEqual(builder.session, "second-session")
        self.assertEqual(builder.last_seq, 0)
        self.assertEqual(builder.counts["old_sessions"], 1)

    def test_gap_remains_blocking(self):
        builder = TrajectoryWindows(100, 1000)
        for index in range(6):
            builder.feed(event(index))
        interrupted = builder.feed(event(10))
        self.assertEqual(interrupted[0]["close_reason"], "observation_gap")
        self.assertIn("interrupted_window", interrupted[0]["quality_flags"])
        self.assertFalse(interrupted[0]["ready_for_shape_features"])
        self.assertEqual(builder.buffers[1]["start"], 1000)

    def test_finish_does_not_promote_partial_window(self):
        builder = TrajectoryWindows(100, 1000)
        for index in range(10):
            builder.feed(event(index))
        windows = builder.finish()
        self.assertEqual(windows[0]["coverage"], 1.0)
        self.assertEqual(windows[0]["close_reason"], "end_of_input")
        self.assertIn("interrupted_window", windows[0]["quality_flags"])
        self.assertFalse(windows[0]["ready_for_shape_features"])
        self.assertEqual(builder.finish(), [])

    def test_slot_coverage_is_not_inflated_by_dense_packets(self):
        builder = TrajectoryWindows(100, 1000)
        windows = []
        for index in range(21):
            windows.extend(builder.feed(event(index, uptime=index * 50)))
        self.assertEqual(windows[0]["observed_samples"], 20)
        self.assertEqual(windows[0]["occupied_slots"], 10)
        self.assertEqual(windows[0]["coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
