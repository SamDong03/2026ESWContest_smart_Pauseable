import csv
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ha_recorder_observation import validate_history


class RecorderObservationTests(unittest.TestCase):
    def setUp(self):
        self.end = datetime(2026, 10, 17, 3, tzinfo=timezone.utc)
        self.start = self.end - timedelta(hours=2)
        self.history = [
            {"state": "off", "last_changed": (self.start - timedelta(days=1)).isoformat()},
            {"state": "on", "last_changed": (self.end - timedelta(seconds=2)).isoformat()},
            {"state": "off", "last_changed": self.end.isoformat()},
        ]

    def test_old_initial_state_is_accepted_but_device_delivery_is_not_certified(self):
        result = validate_history(self.history, self.start, self.end)
        self.assertEqual(result["device_delivery_completeness"], "not_measured")

    def test_recent_only_history_must_not_grant_two_hour_coverage(self):
        with self.assertRaisesRegex(ValueError, "initial state"):
            validate_history(self.history[1:], self.start, self.end)

    def test_unavailable_state_is_not_bridged_as_continuous_history(self):
        for state in ("unavailable", "unknown", ""):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, "unavailable"):
                validate_history([self.history[0], {**self.history[1], "state": state}], self.start, self.end)

    def test_invalid_clock_and_wrong_entity_are_rejected(self):
        for invalid in (
            [{**self.history[0], "last_changed": "2026-10-17T01:00:00"}],
            self.history + [{"state": "on", "last_changed": (self.end + timedelta(seconds=1)).isoformat()}],
            [self.history[0], self.history[2], self.history[1]],
            [{**self.history[0], "entity_id": "wrong"}],
        ):
            with self.subTest(history=invalid), self.assertRaises(ValueError):
                validate_history(invalid, self.start, self.end, "expected")

    def test_writers_anchor_snapshot_to_observation_start_and_keep_two_second_event(self):
        for name in ("run_repetitive_hybrid_demo", "run_washer_hybrid_demo"):
            module = importlib.import_module(name)
            with self.subTest(module=name), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "raw.csv"
                extra = ("binary_sensor.fridge_door",) if "washer" not in name else ()
                coverage = module.write_observation(self.history, self.start, self.end, path, *extra)
                with path.open(newline="", encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(rows[0]["recorded_at"], self.start.isoformat())
                self.assertEqual(rows[0]["record_type"], "state_snapshot")
                self.assertEqual(len(rows), 3)
                self.assertEqual(json.loads(coverage.read_text())["observation_validation"]
                                 ["device_delivery_completeness"], "not_measured")

    def test_washer_cannot_use_later_power_state_to_backfill_initial_unknown_mode(self):
        module = importlib.import_module("run_washer_hybrid_demo")
        history = [{**self.history[0], "state": "rinsing"}, *self.history[1:]]
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(ValueError, "initial washer"):
            module.write_observation(history, self.start, self.end, Path(root) / "raw.csv")

    def test_once_error_has_nonzero_exit_code(self):
        for name in ("run_repetitive_hybrid_demo", "run_washer_hybrid_demo"):
            module = importlib.import_module(name)
            with self.subTest(module=name), patch.object(sys, "argv", [name, "--once", "--dry-run"]), \
                    patch.object(module, "run_cycle", side_effect=RuntimeError("incomplete_history")), \
                    self.assertRaises(SystemExit) as raised:
                module.main()
            self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
