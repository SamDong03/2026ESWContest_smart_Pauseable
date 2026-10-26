import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from portable_forest import export_forest, feature_contract, load_forest, score_features
from predict import load_one_path
from scenarios import Scenario, generate_split
from train import fit_weights, geometry_key, separate_geometry, public_records


class TrainingIntegrityTest(unittest.TestCase):
    def test_portable_probabilities_match_sklearn_and_float32_boundary(self):
        rng = np.random.default_rng(54)
        x = rng.normal(size=(140, 9))
        labels = (x[:, 0] + x[:, 1] > 0).astype(int)
        forest = RandomForestClassifier(n_estimators=11, max_depth=5, random_state=9).fit(x, labels)
        exported = export_forest(forest, "legacy9", 0.46, {})
        inputs = [*x, *rng.normal(size=(45, 9))]


        for tree in exported["trees"]:
            for feature, threshold in zip(tree["feature"], tree["threshold"]):
                if feature >= 0:
                    for delta in (-1e-8, 0.0, 1e-8):
                        row = np.zeros(9)
                        row[feature] = threshold + delta
                        inputs.append(row)
        expected = forest.predict_proba(np.asarray(inputs))[:, 1]
        np.testing.assert_allclose([score_features(exported, row) for row in inputs], expected,
                                   atol=1e-14, rtol=0)

    def test_model_contract_mismatch_rejected(self):
        x = np.arange(54).reshape(6, 9)
        model = RandomForestClassifier(n_estimators=2, random_state=1).fit(x, [0, 0, 0, 1, 1, 1])
        exported = export_forest(model, "legacy9", 0.5, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forest.json"
            path.write_text(json.dumps(exported), encoding="utf-8")
            self.assertEqual(load_forest(path)["format"], exported["format"])
            exported["feature_contract"]["names"][0] = "incompatible"
            path.write_text(json.dumps(exported), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_forest(path)

    def test_reverse_transformed_duplicate_is_excluded_from_training(self):
        points = np.array([[0, 0], [1, .1], [1.3, 1.5], [.2, 1.]])
        transformed = points[::-1] * [-3, 3] + [8, 4]
        self.assertEqual(geometry_key(points), geometry_key(transformed))
        splits = {k: [] for k in ("legacy_audit", "generated_challenge", "generated_test",
                                  "public_selection", "generated_selection", "public_train", "generated_train")}
        splits["generated_test"] = [Scenario("test", "test", "test", 1, points, "test", {})]
        splits["generated_train"] = [Scenario("train", "train", "test", 1, transformed, "train", {})]
        rejected = []
        result = separate_geometry(splits, rejected)
        self.assertEqual(len(result["generated_test"]), 1)
        self.assertEqual(len(result["generated_train"]), 0)
        self.assertEqual(rejected[0]["path_id"], "train")

    def test_fitting_weights_balance_sources_and_classes(self):
        rows = []
        for source, counts in (("public", (3, 5)), ("generated", (40, 20))):
            for label, count in enumerate(counts):
                for index in range(count):
                    rows.append(Scenario(f"{source}-{label}-{index}", "x", "x", label,
                                         np.empty((0, 2)), "train", {"source": source}))
        weights = fit_weights(rows)
        for source in ("public", "generated"):
            for label in (0, 1):
                total = sum(w for r, w in zip(rows, weights) if r.label == label and r.metadata["source"] == source)
                self.assertAlmostEqual(total, len(rows) / 4)

    def test_mixed_prediction_trajectories_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for records in ([{"x": 0, "y": 0, "date": "a"}, {"x": 1, "y": 1, "date": "b"}],
                            [{"x": 0, "y": 0, "target_id": 1}, {"x": 1, "y": 1, "target_id": 2}]):
                path.write_text(json.dumps(records), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_one_path(path)


if __name__ == "__main__":
    unittest.main()
