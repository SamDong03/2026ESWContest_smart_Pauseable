from __future__ import annotations

import json
import unittest
from pathlib import Path

from pipeline.prepare_dataset import expected_names_for_config


class DatasetCountTest(unittest.TestCase):
    def setUp(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "configs" / "guardian-medium-v1.json"
        self.dataset_config = json.loads(config_path.read_text(encoding="utf-8"))["dataset"]

    def test_default_and_selected_clip_counts(self) -> None:
        for count in (160, 200, 240):
            with self.subTest(count=count):
                names = expected_names_for_config(self.dataset_config, count)
                self.assertEqual(len(names), count)
                self.assertEqual(names[0], "S001.wav")
                self.assertEqual(names[-1], f"S{count:03d}.wav")
        self.assertEqual(
            expected_names_for_config(self.dataset_config),
            expected_names_for_config(self.dataset_config, 160),
        )

    def test_count_outside_supported_range_is_rejected(self) -> None:
        for count in (159, 241):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    expected_names_for_config(self.dataset_config, count)


if __name__ == "__main__":
    unittest.main()
