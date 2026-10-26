import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from portable_forest import (
    FORMAT, INPUT_CAST, feature_contract, feature_vector, load_forest,
    score_features, validate_forest,
)


def small_forest():
    return {
        "format": FORMAT,
        "feature_contract": feature_contract("legacy9"),
        "decision_threshold": 0.5,
        "input_cast": INPUT_CAST,
        "classes": [0, 1],
        "score_is_calibrated_real_wandering_probability": False,
        "automatic_alerts_enabled": False,
        "personal_baseline_trained": False,
        "trees": [{
            "left": [1, -1, -1], "right": [2, -1, -1],
            "feature": [0, -2, -2], "threshold": [0.5, -2.0, -2.0],
            "positive_probability": [0.5, 0.0, 1.0],
        }],
    }


class PortableValidationTest(unittest.TestCase):
    def assert_invalid(self, model):
        with self.assertRaises(ValueError):
            validate_forest(model)

    def test_valid_tree_and_float32_threshold(self):
        model = small_forest()
        validate_forest(model)
        for value, expected in [(0.0, 0.0), (0.5, 0.0), (0.5 + 1e-10, 0.0), (0.6, 1.0)]:
            row = [value] + [0.0] * 8
            self.assertEqual(score_features(model, row), expected)

    def test_invalid_headers(self):
        for bad in (None, [], 1, {}, "model"):
            self.assert_invalid(bad)
        mutations = {
            "format": "other", "feature_contract": [], "classes": [False, True],
            "input_cast": "float64", "automatic_alerts_enabled": True,
            "score_is_calibrated_real_wandering_probability": True,
            "personal_baseline_trained": True, "trees": [],
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                model = small_forest()
                model[key] = value
                self.assert_invalid(model)
        for key in ("feature_contract", "decision_threshold", "input_cast", "trees", "classes"):
            model = small_forest()
            del model[key]
            self.assert_invalid(model)

    def test_nonfinite_and_out_of_range_thresholds(self):
        for value in (True, None, "0.5", float("nan"), float("inf"), -0.1, 1.1, 10 ** 1000):
            with self.subTest(value=repr(value)[:50]):
                model = small_forest()
                model["decision_threshold"] = value
                self.assert_invalid(model)

    def test_feature_contract_hash_and_variant_rejected(self):
        for field, value in (("variant", "other"), ("names", ["x"]), ("source_sha256", {})):
            model = small_forest()
            model["feature_contract"][field] = value
            self.assert_invalid(model)

    def test_tree_arrays_have_matching_nonempty_lengths(self):
        model = small_forest()
        for key in model["trees"][0]:
            for replacement in (None, [], [0]):
                bad = copy.deepcopy(model)
                bad["trees"][0][key] = replacement
                self.assert_invalid(bad)
            bad = copy.deepcopy(model)
            del bad["trees"][0][key]
            self.assert_invalid(bad)

    def test_invalid_node_indices_and_sentinels(self):
        mutations = [("left", 0, -2), ("left", 0, 3), ("left", 0, True),
                     ("right", 0, 1), ("feature", 0, -1), ("feature", 0, 9),
                     ("feature", 0, 0.0), ("left", 1, 2), ("feature", 1, 0)]
        for key, index, value in mutations:
            with self.subTest(key=key, index=index, value=value):
                model = small_forest()
                model["trees"][0][key][index] = value
                self.assert_invalid(model)

    def test_invalid_node_numeric_values(self):
        for field, values in (("threshold", (True, None, "0", float("nan"), float("inf"))),
                              ("positive_probability", (True, None, -0.01, 1.01, float("nan")))):
            for value in values:
                model = small_forest()
                model["trees"][0][field][1] = value
                self.assert_invalid(model)

    def test_cycles_and_unreachable_nodes_rejected(self):
        cyclic = small_forest()
        cyclic["trees"][0]["left"][0] = 0
        self.assert_invalid(cyclic)
        with self.assertRaisesRegex(ValueError, "traversal"):
            score_features(cyclic, [0.0] * 9)
        unreachable = small_forest()
        for field, value in (("left", -1), ("right", -1), ("feature", -2),
                             ("threshold", -2.0), ("positive_probability", 0.0)):
            unreachable["trees"][0][field].append(value)
        self.assert_invalid(unreachable)

    def test_limits_are_enforced(self):
        with patch("portable_forest.MAX_TREES", 0):
            self.assert_invalid(small_forest())
        with patch("portable_forest.MAX_NODES_PER_TREE", 2):
            self.assert_invalid(small_forest())
        with patch("portable_forest.MAX_TOTAL_NODES", 2):
            self.assert_invalid(small_forest())

    def test_model_json_rejects_duplicate_keys_and_nonfinite_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            for text in ('{"format": 1, "format": 2}', '{"x": NaN}', '[]', '[',
                         json.dumps({"format": FORMAT}), '[' * 2000 + ']' * 2000):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_forest(path)
            path.write_text(json.dumps(small_forest()), encoding="utf-8")
            self.assertEqual(load_forest(path), small_forest())
            with patch("portable_forest.MAX_MODEL_BYTES", 10):
                with self.assertRaisesRegex(ValueError, "file size"):
                    load_forest(path)

    def test_invalid_feature_vectors_rejected(self):
        for row in ([0] * 8, [0] * 10, [[0] * 9], [True] * 9, ["1"] * 9,
                    [None] * 9, [1j] * 9, [float("nan")] * 9, [1e100] * 9):
            with self.subTest(row=repr(row)[:40]):
                with self.assertRaises(ValueError):
                    score_features(small_forest(), row)

    def test_direct_feature_imports_match_frozen_implementations(self):
        from legacy.features import extract_features as legacy
        from shape_features import extract_features as multiscale
        points = np.column_stack([np.linspace(0, 1, 101), np.sin(np.linspace(0, 5, 101))])
        np.testing.assert_array_equal(feature_vector(points, "legacy9"), legacy(points))
        np.testing.assert_array_equal(feature_vector(points, "multiscale"), multiscale(points))

    def test_package_import_does_not_alias_host_modules(self):
        root = Path(__file__).resolve().parent.parent
        code = '''
import sys
before_path = list(sys.path)
from shape_v2.portable_forest import feature_vector, load_forest, predict_path
from pathlib import Path
model = load_forest(Path("shape_v2/artifacts/model.json"))
result = predict_path(model, [(0, 0), (1, 0), (1, 1), (0, 1)])
assert result["feature_count"] == 36
assert sys.path == before_path
assert "legacy" not in sys.modules
assert "legacy.features" not in sys.modules
assert "shape_features" not in sys.modules
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_reports_invalid_model_without_traceback(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "invalid.json"
            model.write_text(json.dumps({"format": FORMAT}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(root / "predict.py"), "--model", str(model),
                 "--input", str(root / "examples/repeated_shuttle.json")],
                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("ERROR:"), result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
