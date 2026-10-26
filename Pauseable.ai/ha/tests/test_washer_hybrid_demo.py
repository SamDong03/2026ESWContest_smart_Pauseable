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

from run_washer_hybrid_demo import (  # noqa: E402
    build_payload,
    normalize_power_state,
    recent_power_transitions,
    run_cycle,
)


def event(now, minutes_ago, state):
    changed = (now - timedelta(minutes=minutes_ago)).isoformat()
    return {"state": state, "last_changed": changed, "last_updated": changed}


class WasherHybridDemoTests(unittest.TestCase):
    def test_normalizes_real_lg_washer_power_states(self):
        self.assertEqual(normalize_power_state("initial"), "on")
        self.assertEqual(normalize_power_state("power_off"), "off")
        self.assertIsNone(normalize_power_state("unknown"))

    def test_counts_only_real_state_transitions(self):
        now = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
        history = [event(now, 15, "off")]
        for minute in (9, 8, 7, 6, 5, 4, 3, 2, 1, 0):
            history.append(event(now, minute, "on" if minute % 2 else "off"))
        history.insert(4, event(now, 7, "on"))

        on_transitions, transitions = recent_power_transitions(history, now)

        self.assertEqual(on_transitions, 5)
        self.assertEqual(transitions, 10)

    def test_rearm_time_excludes_previous_transitions(self):
        now = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
        history = [
            event(now, 8, "power_off"),
            event(now, 7, "initial"),
            event(now, 6, "power_off"),
            event(now, 1, "initial"),
        ]

        self.assertEqual(recent_power_transitions(history, now), (2, 3))
        self.assertEqual(
            recent_power_transitions(
                history,
                now,
                after=now - timedelta(minutes=2),
            ),
            (1, 1),
        )

    def test_payload_has_washer_route(self):
        args = SimpleNamespace(
            patient_id="patient",
            device_id="device",
            model_version="model",
        )
        row = {
            "level": "attention",
            "risk_score": 35,
            "if_level": "normal",
            "ae_level": "risk",
            "decision_policy": "rules_plus_validated_if_ae",
            "model_status": "shadow",
            "reasons": "Learned model alert",
        }

        payload = build_payload(row, 5, 10, args)

        self.assertEqual(payload["evidence"]["pattern_code"], "washer_power_repetition")
        self.assertEqual(payload["evidence"]["observation_count"], 10)
        self.assertIn("model_contributed", payload["evidence"]["reason_codes"])

    def test_hybrid_alert_publishes_below_old_fixed_count(self):
        now = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
        history = [event(now, 2, "power_off"), event(now, 1, "initial")]
        args = SimpleNamespace(
            history_hours=2.25,
            entity_id="sensor.setaggi_current_status",
            window_minutes=10,
            prefix="test_washer",
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
                patch("run_washer_hybrid_demo.fetch_history", return_value=(history, now - timedelta(hours=2), now)),
                patch("run_washer_hybrid_demo.write_observation", return_value=Path(directory) / "coverage.json"),
                patch("run_washer_hybrid_demo.run_pipeline"),
                patch("run_washer_hybrid_demo.latest_decision", return_value=decision),
                patch("run_washer_hybrid_demo.publish") as publish,
            ):
                run_cycle(args, state_path)

        publish.assert_called_once()
        self.assertEqual(publish.call_args.args[1]["behavior"], "repetitive")


if __name__ == "__main__":
    unittest.main()
