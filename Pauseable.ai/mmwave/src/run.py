from __future__ import annotations
import argparse
import csv
import hashlib
from importlib.metadata import version
import json
import platform
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, confusion_matrix,
    precision_score, recall_score, f1_score, roc_auc_score,
)
from dataset import fetch, load_trajectories, verified_sources, decode_document, xy
from features import FEATURE_NAMES, extract_features, path_fingerprint

HERE = Path(__file__).resolve().parent
SEED = 42
LIMITATION = (
    "Synthetic drawn paths only; not real mmWave or personal routine validation. "
    "Scores are not clinical diagnoses, calibrated probabilities, or alert decisions."
)


def feature_source_hash():
    source = (HERE / "features.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def prepare(train_paths, validation_paths):
    rejected = []
    def encode(paths, split):
        encoded = []
        for path in paths:
            try:
                features = extract_features(path.points)
                fingerprint = path_fingerprint(path.points)
                if not np.isfinite(features).all():
                    raise ValueError("Nonfinite feature value")
                encoded.append((path, features, fingerprint))
            except ValueError as error:
                rejected.append({"path_id": path.path_id, "split": split,
                                 "reason": str(error)})
        return encoded
    train = encode(train_paths, "train")
    validation = encode(validation_paths, "validation")
    validation_keys = {row[2] for row in validation}
    buckets = defaultdict(list)
    for row in train:
        buckets[row[2]].append(row)
    kept = []
    for key, rows in buckets.items():
        if key in validation_keys:
            for row in rows:
                rejected.append({"path_id": row[0].path_id, "split": "train",
                                 "reason": "geometry_duplicate_of_validation"})
        elif len({row[0].label for row in rows}) > 1:
            for row in rows:
                rejected.append({"path_id": row[0].path_id, "split": "train",
                                 "reason": "same_geometry_conflicting_training_labels"})
        else:
            kept.append(rows[0])
            for row in rows[1:]:
                rejected.append({"path_id": row[0].path_id, "split": "train",
                                 "reason": "geometry_duplicate_within_train"})
    if not kept or not validation:
        raise ValueError("No usable independent training/validation paths")
    if len({r[0].label for r in kept}) < 2 or len({r[0].label for r in validation}) < 2:
        raise ValueError("Both synthetic classes are required in each evaluation split")
    if len(validation_keys) != len(validation):
        raise ValueError("Validation contains geometry duplicates; evaluate grouped paths first")
    return kept, validation, rejected


def metrics(labels, predictions, scores=None):
    result = {
        "paths": len(labels),
        "confusion_matrix_rows_actual_columns_predicted_0_1": confusion_matrix(
            labels, predictions, labels=[0, 1]).tolist(),
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "precision_positive": float(precision_score(labels, predictions, zero_division=0)),
        "recall_positive": float(recall_score(labels, predictions, zero_division=0)),
        "f1_positive": float(f1_score(labels, predictions, zero_division=0)),
    }
    if scores is not None:
        result["roc_auc_positive"] = float(roc_auc_score(labels, scores))
    n, z = len(labels), 1.96
    p = result["accuracy"]
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    half = z * np.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    result["accuracy_wilson_95pct"] = [float(center-half), float(center+half)]
    return result


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def train(data_dir: Path, output_root: Path) -> Path:
    provenance = verified_sources(data_dir)
    raw_train = load_trajectories(data_dir / "dataset.json")
    raw_validation = load_trajectories(data_dir / "dataset-validacao.json")
    train_rows, valid_rows, rejected = prepare(raw_train, raw_validation)
    x = np.stack([r[1] for r in train_rows])
    y = np.array([r[0].label for r in train_rows])
    vx = np.stack([r[1] for r in valid_rows])
    vy = np.array([r[0].label for r in valid_rows])

    rf = RandomForestClassifier(n_estimators=200, max_depth=5, min_samples_leaf=2,
                                class_weight="balanced", random_state=SEED, n_jobs=1)
    rf.fit(x, y)
    rf_score = rf.predict_proba(vx)[:, list(rf.classes_).index(1)]
    rf_pred = (rf_score >= 0.5).astype(int)
    dummy = DummyClassifier(strategy="most_frequent").fit(x, y)

    isolation = IsolationForest(n_estimators=200, max_samples="auto",
                                 contamination="auto", random_state=SEED, n_jobs=1)
    isolation.fit(x)
    train_anomaly = -isolation.score_samples(x)
    threshold = float(np.quantile(train_anomaly, 0.95))
    anomaly = -isolation.score_samples(vx)
    anomaly_pred = (anomaly > threshold).astype(int)

    run_dir = output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    versions = {"python": platform.python_version(), "numpy": np.__version__,
                "scikit_learn": sklearn.__version__, "joblib": joblib.__version__,
                "scipy": version("scipy"), "threadpoolctl": version("threadpoolctl")}
    counts = lambda rows: dict(Counter(str(row[0].label) for row in rows))
    report = {
        "purpose": "Synthetic wandering-shape research baseline, not production alerting",
        "limitation": LIMITATION,
        "source": provenance, "versions": versions, "seed": SEED,
        "feature_names": list(FEATURE_NAMES), "feature_source_sha256": feature_source_hash(),
        "label_meaning": {"0": "synthetic non-wandering", "1": "synthetic wandering"},
        "split": {"method": "Author-provided separate trajectory files; no point/window random split",
                  "raw_train_paths": len(raw_train), "raw_validation_paths": len(raw_validation),
                  "used_train_paths": len(train_rows), "used_validation_paths": len(valid_rows),
                  "train_label_counts": counts(train_rows), "validation_label_counts": counts(valid_rows),
                  "excluded": rejected, "geometry_fingerprint_overlap_after_filter": 0,
                  "duplicate_check_limit": "64-point rounded geometry fingerprint, not proof against near duplicates",
                  "train_ids": [r[0].path_id for r in train_rows],
                  "validation_ids": [r[0].path_id for r in valid_rows]},
        "random_forest": {"threshold": 0.5, "parameters": rf.get_params(),
                          "holdout": metrics(vy, rf_pred, rf_score)},
        "majority_baseline": {"holdout": metrics(vy, dummy.predict(vx))},
        "isolation_forest_exploratory": {
            "fitted_without_labels": True, "threshold_rule": "training score 95th percentile, fixed in advance",
            "threshold": threshold, "parameters": isolation.get_params(),
            "warning": "Training mixture includes about 50% wandering. Rarity is NOT a wandering label. This threshold is not a validated alert threshold.",
            "holdout_comparison_to_wandering_labels": metrics(vy, anomaly_pred, anomaly)},
        "deployment": {"pi_modified": False, "alerting_enabled": False,
                       "personalization_validated": False, "real_mmwave_validated": False},
    }
    save_json(run_dir / "metrics.json", report)
    bundle = {"format": "pauseable-smartcare-baseline-v1", "feature_names": list(FEATURE_NAMES),
              "versions": versions, "feature_source_sha256": feature_source_hash(),
              "rf": rf, "isolation": isolation,
              "isolation_threshold": threshold, "source": provenance, "limitation": LIMITATION}
    joblib.dump(bundle, run_dir / "model.joblib")
    with (run_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["path_id", "synthetic_label", "rf_prediction", "rf_score_not_calibrated",
                         "mixture_rarity_score", "above_training_95pct"])
        for row, label, pred, score, rare, above in zip(valid_rows, vy, rf_pred, rf_score, anomaly, anomaly_pred):
            writer.writerow([row[0].path_id, int(label), int(pred), float(score), float(rare), int(above)])
    report_text = markdown_report(report)
    (run_dir / "REPORT.md").write_text(report_text, encoding="utf-8")
    print(report_text)
    print(f"RUN_DIRECTORY: {run_dir.resolve()}")
    return run_dir


def markdown_report(report):
    rf = report["random_forest"]["holdout"]
    dummy = report["majority_baseline"]["holdout"]
    rare = report["isolation_forest_exploratory"]["holdout_comparison_to_wandering_labels"]
    split = report["split"]
    lines = ["# Pauseable SmartCare 첫 배회 경로 실험", "",
        "이 결과는 손으로 만든 합성 경로에 대한 실험입니다. 실제 노인, LD6004, 개인화 알림 성능이 아닙니다.", "",
        f"- 학습: {split['used_train_paths']}/{split['raw_train_paths']} 경로",
        f"- 별도 검증: {split['used_validation_paths']}/{split['raw_validation_paths']} 경로",
        f"- 제외: {len(split['excluded'])} 경로 (상세: metrics.json)",
        "- 점/겹치는 구간을 무작위로 나누지 않고 원본의 별도 경로 파일로 검증했습니다.",
        "- 모델 설정과 판정 경계값은 별도 검증 결과를 보기 전에 정했고, 이 결과에 맞춰 조정하지 않았습니다.",
        "- 지문이 같은 변환 경로는 점검하지만, 비슷하게 그린 모든 경로의 중복을 배제하는 검사는 아닙니다.",
        "- 위치·시간·환자 식별자는 입력하지 않았습니다. 경로 모양만 사용했습니다.", "",
        "| 모델 | 정확도 | 배회 재현율 | 배회 정밀도 | F1 |",
        "|---|---:|---:|---:|---:|"]
    for name, result in [("Random Forest 분류", rf), ("다수 클래스 기준", dummy),
                          ("Isolation Forest 희귀도 비교*", rare)]:
        lines.append(f"| {name} | {result['accuracy']:.1%} | {result['recall_positive']:.1%} | {result['precision_positive']:.1%} | {result['f1_positive']:.3f} |")
    lo, hi = rf["accuracy_wilson_95pct"]
    lines.extend(["", f"Random Forest 정확도 Wilson 95% 구간: {lo:.1%}–{hi:.1%}. 작은 합성 표본의 통계이며 실환경 신뢰구간이 아닙니다.", "",
        f"혼동행렬(행=실제 0/1, 열=예측 0/1): `{rf['confusion_matrix_rows_actual_columns_predicted_0_1']}`", "",
        "*Isolation Forest는 라벨을 입력하지 않고 두 클래스가 섞인 학습 경로에 맞췄습니다. 희귀함과 배회는 다르므로 점수를 배회 확률이나 자동 알림으로 사용하면 안 됩니다.", "",
        "## 다음에 검증할 것", "",
        "실제 시간 간격이 있는 LD6004 경로를 모아 구간화·추적 안정성을 확인하고, 사람별 기준선과 반복/왕복 경로 점수를 별도로 검증해야 합니다. 현재 모델은 이를 대신하지 않습니다.", "",
        f"원본: [{report['source']['repository']}]({report['source']['repository']})",
        f"고정 커밋: `{report['source']['commit']}`", ""])
    return "\n".join(lines)


def predict(model_path: Path, input_path: Path, trust: bool):
    if not trust:
        raise ValueError("joblib can execute code. Use --trust-local-model only for a model you trained locally")
    model = joblib.load(model_path)
    if model.get("format") != "pauseable-smartcare-baseline-v1" or model.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("Incompatible model format or feature order")
    if model.get("feature_source_sha256") != feature_source_hash():
        raise ValueError("Feature implementation changed; retrain the model before prediction")
    if model["versions"]["scikit_learn"] != sklearn.__version__:
        raise ValueError("Use the scikit-learn version recorded when this model was trained")
    raw = decode_document(input_path.read_bytes())

    if not all(isinstance(p, dict) for p in raw):
        raise ValueError("Prediction input must contain exactly one ordered x/y path")
    dated = [p for p in raw if "date" in p]
    if dated:
        if len(dated) != len(raw) or not all(isinstance(p["date"], str) and p["date"] for p in dated):
            raise ValueError("All points must have a valid date grouping key, or all must omit it")
        if len({p["date"] for p in dated}) != 1:
            raise ValueError("Prediction input must contain exactly one ordered x/y path")
    points = [xy(p) for p in raw]
    try:
        feature_row = extract_features(points)[None, :]
    except ValueError as error:
        print(json.dumps({"status": "insufficient_path", "detail": str(error),
                          "alert": False, "wandering_score": None}, ensure_ascii=False))
        return
    score = float(model["rf"].predict_proba(feature_row)[0, list(model["rf"].classes_).index(1)])
    rarity = float(-model["isolation"].score_samples(feature_row)[0])
    print(json.dumps({"status": "research_only", "synthetic_wandering_score_not_calibrated": score,
                      "synthetic_class": int(score >= 0.5), "mixture_rarity_score": rarity,
                      "above_training_rarity_threshold": bool(rarity > model["isolation_threshold"]),
                      "alert": False, "limitation": LIMITATION}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("fetch", "train", "demo"):
        p = sub.add_parser(command)
        p.add_argument("--data-dir", type=Path, default=HERE / "data")
        if command != "fetch":
            p.add_argument("--output-dir", type=Path, default=HERE / "runs")
    p = sub.add_parser("predict")
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--trust-local-model", action="store_true")
    args = parser.parse_args()
    if args.command in ("fetch", "demo"):
        print("Fetching/verifying two small, pinned SmartCare source files...")
        fetch(args.data_dir)
    if args.command in ("train", "demo"):
        train(args.data_dir, args.output_dir)
    elif args.command == "predict":
        predict(args.model, args.input, args.trust_local_model)
    else:
        print("SOURCE_CHECKSUMS_OK")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
