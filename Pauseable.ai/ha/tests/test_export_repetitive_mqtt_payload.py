import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pi-src"
sys.path.insert(0, str(SOURCE if SOURCE.exists() else ROOT / "src"))

from export_repetitive_mqtt_payload import convert_row  # noqa: E402


ROW = {
    "episode_id": "3",
    "start_time": "2026-10-04 19:12:00",
    "duration_minutes": "10",
    "level": "attention",
    "max_score": "35",
    "primary_pattern": "learned_behavior_anomaly",
    "window_count": "10",
    "reasons": "Learned model alert",
}


class ConvertRowTests(unittest.TestCase):
    def test_omits_unknown_model_metadata(self):
        payload = convert_row(ROW, "patient", "device", "model")

        self.assertNotIn("decision_policy", payload["evidence"])
        self.assertNotIn("model_status", payload["evidence"])

    def test_uses_explicit_model_metadata(self):
        payload = convert_row(
            ROW,
            "patient",
            "device",
            "model",
            decision_policy="rules_plus_validated_if_ae",
            model_status="shadow",
        )

        self.assertEqual(
            payload["evidence"]["decision_policy"],
            "rules_plus_validated_if_ae",
        )
        self.assertEqual(payload["evidence"]["model_status"], "shadow")


if __name__ == "__main__":
    unittest.main()
