import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest, RandomForestClassifier

from dataset import Trajectory, decode_document, load_trajectories, verified_sources, xy
from features import FEATURE_NAMES, extract_features
from run import feature_source_hash, metrics, predict, prepare


class DatasetTest(unittest.TestCase):
    def test_double_json_and_group_order(self):
        records = [
            {"date": "group-b", "x": 2, "y": 0, "stress": False},
            {"date": "group-a", "x": 7, "y": 1, "stress": True},
            {"date": "group-b", "x": 1, "y": 0, "stress": False},
        ]
        raw = json.dumps(json.dumps(records))
        self.assertEqual(decode_document(raw), records)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text(raw, encoding="utf-8")
            rows = load_trajectories(path)
        self.assertEqual(rows[0].points, ((2.0, 0.0), (1.0, 0.0)))
        self.assertEqual([r.label for r in rows], [0, 1])

    def test_mixed_labels_rejected(self):
        records = [{"date": "a", "x": i, "y": 0, "stress": bool(i)} for i in range(2)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Mixed class"):
                load_trajectories(path)

    def test_invalid_coordinate(self):
        for bad in (True, "12", None, float("nan"), float("inf"), 10 ** 500):
            with self.subTest(bad=str(bad)[:30]):
                with self.assertRaises(ValueError):
                    xy({"x": bad, "y": 0})

    def test_modified_source_not_silently_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                verified_sources(Path(directory))
            self.assertEqual(path.read_text(), "[]")


class PipelineTest(unittest.TestCase):
    straight = ((0, 0), (1, 0), (2, 0))
    loop = ((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))
    zigzag = ((0, 0), (1, 1), (0, 2), (1, 3), (0, 4))
    curve = ((0, 0), (1, 0.5), (2, 0.1), (3, 1))

    def test_geometry_overlap_removed_from_train_not_holdout(self):
        transformed = tuple((2*x+10, 2*y-7) for x, y in self.loop)
        train = [Trajectory("train0", self.straight, 0),
                 Trajectory("train1", self.zigzag, 1),
                 Trajectory("overlap", transformed, 1),
                 Trajectory("invalid", ((1, 1),), 0)]
        valid = [Trajectory("valid0", self.curve, 0), Trajectory("valid1", self.loop, 1)]
        selected, heldout, rejected = prepare(train, valid)
        self.assertEqual([r[0].path_id for r in selected], ["train0", "train1"])
        self.assertEqual([r[0].path_id for r in heldout], ["valid0", "valid1"])
        self.assertEqual({r["path_id"] for r in rejected}, {"overlap", "invalid"})

    def test_confusion_matrix_orientation(self):
        result = metrics(np.array([0, 0, 0, 1]), np.array([0, 1, 1, 1]))
        self.assertEqual(result["confusion_matrix_rows_actual_columns_predicted_0_1"], [[1, 2], [0, 1]])

    def _model(self):
        x = np.stack([extract_features(p) for p in (self.straight, self.loop, self.zigzag, self.curve)])
        return {"format": "pauseable-smartcare-baseline-v1", "feature_names": list(FEATURE_NAMES),
                "feature_source_sha256": feature_source_hash(),
                "versions": {"scikit_learn": sklearn.__version__},
                "rf": RandomForestClassifier(n_estimators=5, random_state=42).fit(x, [0, 1, 1, 0]),
                "isolation": IsolationForest(n_estimators=5, random_state=42).fit(x),
                "isolation_threshold": 0.5}

    def test_saved_model_prediction_and_stationary_abstention(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            input_path = Path(directory) / "path.json"
            model = self._model()
            joblib.dump(model, model_path)
            input_path.write_text(json.dumps([{"x": x, "y": y} for x, y in self.loop]))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                predict(model_path, input_path, True)
            result = json.loads(output.getvalue())
            expected = model["rf"].predict_proba(extract_features(self.loop)[None, :])[0, 1]
            self.assertAlmostEqual(result["synthetic_wandering_score_not_calibrated"], expected)
            self.assertFalse(result["alert"])
            input_path.write_text('[{"x":1,"y":1},{"x":1,"y":1},{"x":1,"y":1}]')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                predict(model_path, input_path, True)
            self.assertEqual(json.loads(output.getvalue())["status"], "insufficient_path")

    def test_prediction_rejects_untrusted_model_and_mixed_trajectories(self):
        with self.assertRaisesRegex(ValueError, "joblib can execute"):
            predict(Path("missing"), Path("missing"), False)
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            input_path = Path(directory) / "path.json"
            joblib.dump(self._model(), model_path)
            for dates in (("a", None, None), ("a", "b", "a"), ([], [], [])):
                records = []
                for (x, y), date in zip(self.straight, dates):
                    record = {"x": x, "y": y}
                    if date is not None:
                        record["date"] = date
                    records.append(record)
                input_path.write_text(json.dumps(records))
                with self.assertRaises(ValueError):
                    predict(model_path, input_path, True)

    def test_changed_features_refuse_old_model(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            model = self._model()
            model["feature_source_sha256"] = "outdated"
            joblib.dump(model, model_path)
            with self.assertRaisesRegex(ValueError, "Feature implementation changed"):
                predict(model_path, Path("not_needed"), True)


if __name__ == "__main__":
    unittest.main()
