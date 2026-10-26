import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pi-src"
if not SOURCE.exists():
    SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))

from run_repetitive_hybrid_demo import recent_open_count, run_cycle  # noqa: E402


class RefrigeratorRetakeTests(unittest.TestCase):
    def test_rearm_time_excludes_previous_opens(self):
        now = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)
        history = [
            {
                "state": "on",
                "last_changed": (now - timedelta(minutes=minute)).isoformat(),
            }
            for minute in (9, 5, 1)
        ]

        self.assertEqual(recent_open_count(history, now), 3)
        self.assertEqual(
            recent_open_count(history, now, after=now - timedelta(minutes=2)),
            1,
        )

    def test_hybrid_alert_publishes_below_old_fixed_count(self):
        now = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)
        history = [
            {
                "state": "on",
                "last_changed": (now - timedelta(minutes=1)).isoformat(),
            }
        ]
        args = SimpleNamespace(
            history_hours=2.25,
            entity_id="binary_sensor.naengjanggo_door",
            prefix="test_fridge",
            patient_id="patient",
            device_id="device",
            model_version="model",
        )
        decision = {
            "level": "attention",
            "risk_score": 35,
            "if_level": "normal",
            "ae_level": "normal",
            "decision_policy": "rules_plus_validated_if_ae",
            "model_status": "shadow",
            "reasons": "statistical rule alert",
        }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (
                patch("run_repetitive_hybrid_demo.fetch_history", return_value=(history, now - timedelta(hours=2), now)),
                patch("run_repetitive_hybrid_demo.write_observation", return_value=Path(directory) / "coverage.json"),
                patch("run_repetitive_hybrid_demo.run_pipeline"),
                patch("run_repetitive_hybrid_demo.latest_decision", return_value=decision),
                patch("run_repetitive_hybrid_demo.publish") as publish,
            ):
                run_cycle(args, state_path)

        publish.assert_called_once()
        self.assertEqual(publish.call_args.args[1]["behavior"], "repetitive")


if __name__ == "__main__":
    unittest.main()
