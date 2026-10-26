

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from trajectory_windows import TrajectoryWindows, demo_event, MAX_PACKET_BYTES, parse_event

DEFAULT_MODEL = Path(__file__).resolve().parent / "shape_v2" / "artifacts" / "model.json"
NONBLOCKING_FLAGS = {"source_clock_unsynced"}


class WindowScorer:
    def __init__(self, model_path=DEFAULT_MODEL, trust_local_model=False):
        model_path = Path(model_path)
        self.model_id = hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.forest = None
        if model_path.suffix.lower() == ".json":
            from shape_v2.portable_forest import load_forest

            self.forest = load_forest(model_path)
            self.model_format = self.forest["format"]
            contract = self.forest["feature_contract"]
            self.feature_schema = hashlib.sha256(
                json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self.decision_threshold = self.forest["decision_threshold"]
        else:
            self._load_legacy(model_path, trust_local_model)

    def _load_legacy(self, model_path, trust_local_model):
        if not trust_local_model:
            raise ValueError("Legacy joblib requires --trust-local-model for your own model.")
        import joblib
        import sklearn
        from sklearn.ensemble import RandomForestClassifier
        from features import FEATURE_NAMES
        from run import feature_source_hash

        bundle = joblib.load(model_path)
        if not isinstance(bundle, dict) or bundle.get("format") != "pauseable-smartcare-baseline-v1":
            raise ValueError("Unsupported legacy model format.")
        if bundle.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("Feature order differs from the trained model.")
        if bundle.get("feature_source_sha256") != feature_source_hash():
            raise ValueError("Feature code differs from the trained model.")
        if bundle.get("versions", {}).get("scikit_learn") != sklearn.__version__:
            raise ValueError("Use the scikit-learn version recorded at training.")
        rf = bundle.get("rf")
        if not isinstance(rf, RandomForestClassifier):
            raise ValueError("Random Forest is missing.")
        if list(getattr(rf, "classes_", [])) != [0, 1]:
            raise ValueError("Expected synthetic class labels 0 and 1.")
        if getattr(rf, "n_features_in_", None) != len(FEATURE_NAMES):
            raise ValueError("Model feature count differs.")
        self.rf = rf
        self.model_format = bundle["format"]
        self.feature_schema = feature_source_hash()
        self.decision_threshold = 0.5

    def score(self, window):
        if (window.get("kind") != "trajectory_window"
                or window.get("window_schema_version") != "0.1"):
            raise ValueError("Unsupported trajectory window format.")
        result = {
            "kind": "mmwave_shape_score",
            **{key: window[key] for key in (
                "window_id", "sensor_id", "session_id", "target_id", "data_origin",
                "time_basis", "window_start_ms", "window_end_ms", "identity_status",
            )},
            "model_sha256": self.model_id,
            "model_format": self.model_format,
            "feature_schema": self.feature_schema,
            "decision_threshold": self.decision_threshold,
            "status": "skipped",
            "quality_flags": list(window["quality_flags"]),
            "feature_count": 0,
            "rf_shape_score_not_calibrated": None,
            "synthetic_shape_class": None,
            "personal_baseline": {"status": "not_connected", "reference_percentile": None},
            "wandering_decision": "not_evaluated",
            "alert": False,
        }
        blocking = set(result["quality_flags"]) - NONBLOCKING_FLAGS
        if not window["ready_for_shape_features"] or blocking:
            return result
        xy = [(point["x"], point["y"]) for point in window["points"]]
        try:
            if self.forest is not None:
                from shape_v2.portable_forest import feature_vector, score_features

                values = feature_vector(xy, self.forest["feature_contract"]["variant"])
                score = score_features(self.forest, values)
            else:
                from features import extract_features

                values = extract_features(xy)
                score = float(self.rf.predict_proba(values[None, :])[0, 1])
        except ValueError as error:
            result["quality_flags"].append("feature_extraction_failed")
            result["detail"] = str(error)
            return result
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("Model produced an invalid score.")
        result.update(
            status="scored_research_only",
            feature_count=len(values),
            rf_shape_score_not_calibrated=score,
            synthetic_shape_class=int(score >= self.decision_threshold),
        )
        return result


def event_windows(path, sample_ms, window_ms):
    builder = TrajectoryWindows(sample_ms, window_ms)
    with Path(path).open("rb") as handle:
        line_number = 0
        while True:
            line = handle.readline(MAX_PACKET_BYTES + 3)
            if not line:
                break
            line_number += 1
            payload = line.rstrip(b"\r\n")
            if not payload.strip():
                continue
            try:
                yield from builder.feed(parse_event(payload))
            except ValueError as error:
                raise ValueError(f"Line {line_number}: {error}") from error
    yield from builder.finish()


def demo_windows():
    builder = TrajectoryWindows(sample_ms=100, window_ms=1000)
    for index in range(31):
        yield from builder.feed(demo_event(index))
    yield from builder.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--trust-local-model", action="store_true")
    parser.add_argument("--input", type=Path, help="Original v1 event JSONL; omitted = synthetic demo")
    parser.add_argument("--sample-ms", type=int)
    parser.add_argument("--window-ms", type=int, default=30000)
    parser.add_argument("--verbose", action="store_true", help="Write summary to stderr")
    args = parser.parse_args()
    if args.input is not None and args.sample_ms is None:
        parser.error("--input requires --sample-ms.")
    scorer = WindowScorer(args.model, args.trust_local_model)
    windows = (demo_windows() if args.input is None
               else event_windows(args.input, args.sample_ms, args.window_ms))
    counts = {"windows": 0, "scored": 0, "skipped": 0}
    for window in windows:
        result = scorer.score(window)
        counts["windows"] += 1
        counts["scored" if result["status"] == "scored_research_only" else "skipped"] += 1
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if args.verbose:
        print(json.dumps({"kind": "summary", **counts}), file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
