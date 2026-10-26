

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import time

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
    confusion_matrix, precision_score, recall_score, f1_score, roc_auc_score)
from sklearn.model_selection import train_test_split

from legacy.dataset import load_trajectories, verified_sources
from legacy.features import extract_features as legacy_features, path_fingerprint
from portable_forest import export_forest, feature_contract, score_features
from scenarios import Scenario, generate_split, generate_ambiguous
from shape_features import extract_features as multiscale_features

HERE = Path(__file__).resolve().parent
SEED = 20260911
PER_FAMILY = {"train": 180, "selection": 60, "test": 100, "challenge": 50}
CANDIDATES = [
    {"name": "matched_legacy9_public", "variant": "legacy9", "augmented": False,
     "n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2},
    {"name": "legacy9_augmented", "variant": "legacy9", "augmented": True,
     "n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2},
    {"name": "multiscale_public", "variant": "multiscale", "augmented": False,
     "n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2},
    {"name": "multiscale_augmented", "variant": "multiscale", "augmented": True,
     "n_estimators": 200, "max_depth": 5, "min_samples_leaf": 2},
    {"name": "multiscale_augmented_depth10", "variant": "multiscale", "augmented": True,
     "n_estimators": 300, "max_depth": 10, "min_samples_leaf": 3},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def progress(message):
    print(message, flush=True)


def geometry_key(points):
    return min(path_fingerprint(points), path_fingerprint(np.asarray(points)[::-1]))


def public_records(data_dir: Path):
    records, rejected = [], []
    audit = []
    for filename, output in (("dataset.json", records), ("dataset-validacao.json", audit)):
        for path in load_trajectories(data_dir / filename):
            try:
                geometry_key(path.points)
                legacy_features(path.points)
            except ValueError as error:
                rejected.append({"path_id": path.path_id, "reason": str(error)})
                continue
            output.append(Scenario(path_id=path.path_id, group_id=geometry_key(path.points),
                family="smartcare_drawn", label=path.label, points=np.asarray(path.points),
                split="legacy_audit" if output is audit else "public_unsplit",
                metadata={"source": "smartcare", "data_origin": "simulated",
                          "label_basis": "upstream synthetic stress boolean"}))


    reserved = {r.group_id for r in audit}
    buckets = {}
    for record in records:
        buckets.setdefault(record.group_id, []).append(record)
    unique = []
    for key, bucket in buckets.items():
        if key in reserved or len({r.label for r in bucket}) > 1:
            reason = "geometry_overlaps_legacy_audit" if key in reserved else "conflicting_geometry_labels"
            rejected.extend({"path_id": r.path_id, "reason": reason} for r in bucket)
        else:
            unique.append(bucket[0])
            rejected.extend({"path_id": r.path_id, "reason": "duplicate_geometry"} for r in bucket[1:])
    train, selection = train_test_split(unique, test_size=0.25, random_state=SEED,
                                       stratify=[r.label for r in unique])
    train = [replace(row, split="public_train") for row in train]
    selection = [replace(row, split="public_selection") for row in selection]
    return train, selection, audit, rejected


def separate_geometry(splits: dict, rejected: list):
    pass
    seen, groups = {}, {}
    order = ("legacy_audit", "generated_challenge", "generated_test",
             "public_selection", "generated_selection", "public_train", "generated_train")
    for split in order:
        kept = []
        for row in splits[split]:
            key = geometry_key(row.points)
            if key in seen or row.group_id in groups:
                previous = seen.get(key, groups.get(row.group_id))
                rejected.append({"path_id": row.path_id, "split": split,
                                 "reason": "reserved_or_same_split_geometry_duplicate",
                                 "retained": previous})
                continue
            seen[key] = {"path_id": row.path_id, "split": split, "label": row.label}
            groups[row.group_id] = seen[key]
            kept.append(row)
        splits[split] = kept
    return splits


def describe(rows):
    return {"paths": len(rows), "classes": dict(Counter(str(r.label) for r in rows)),
            "families": dict(Counter(r.family for r in rows)),
            "unique_groups": len({r.group_id for r in rows})}


def save_rows(path: Path, rows):
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            value = asdict(row)
            value["points"] = np.asarray(row.points).tolist()
            output.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def fit_weights(rows):
    sources = [r.metadata.get("source", "generated") for r in rows]
    source_count = len(set(sources))
    counts = Counter(zip(sources, (r.label for r in rows)))
    return np.asarray([len(rows) / (source_count * 2 * counts[(source, row.label)])
                       for source, row in zip(sources, rows)])


def feature_matrix(rows, variant, cache):
    count = 9 if variant == "legacy9" else len(feature_contract("multiscale")["names"])
    return np.stack([cache[r.path_id][:count] for r in rows])


def positive_scores(model, matrix):
    return model.predict_proba(matrix)[:, list(model.classes_).index(1)]


def metrics(rows, scores, threshold):
    labels = np.asarray([r.label for r in rows], dtype=int)
    predictions = np.asarray(scores) >= threshold
    accuracy = float(accuracy_score(labels, predictions))
    n, z = len(rows), 1.96
    center = (accuracy + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(accuracy * (1 - accuracy) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    family_results = {}
    for family in sorted({r.family for r in rows}):
        indices = [i for i, r in enumerate(rows) if r.family == family]
        family_results[family] = {
            "paths": len(indices),
            "correct": int(np.sum(labels[indices] == predictions[indices])),
            "accuracy": float(np.mean(labels[indices] == predictions[indices])),
        }
    return {"paths": n, "threshold": float(threshold), "accuracy": accuracy,
            "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
            "precision": float(precision_score(labels, predictions, zero_division=0)),
            "recall": float(recall_score(labels, predictions, zero_division=0)),
            "f1": float(f1_score(labels, predictions, zero_division=0)),
            "roc_auc": float(roc_auc_score(labels, scores)),
            "confusion_matrix_rows_actual_columns_predicted": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
            "accuracy_wilson95_synthetic_only": [float(center-half), float(center+half)],
            "by_family": family_results}


def selection_objective(public_rows, public_scores, gen_rows, gen_scores, threshold):
    public_balanced = balanced_accuracy_score([r.label for r in public_rows], public_scores >= threshold)
    generated_balanced = balanced_accuracy_score([r.label for r in gen_rows], gen_scores >= threshold)
    return float((public_balanced + generated_balanced) / 2)


def train(data_dir: Path, output_root: Path):
    started = time.perf_counter()
    provenance = verified_sources(data_dir)
    run_dir = output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "datasets").mkdir()

    protocol = {"seed": SEED, "per_family": PER_FAMILY, "candidates": CANDIDATES,
                "thresholds": np.round(np.arange(0.2, 0.8001, 0.02), 2).tolist(),
                "selection_objective": "mean source-specific balanced accuracy",
                "refit_after_selection": False, "protocol_sha256": sha(HERE / "PROTOCOL.md"),
                "source": provenance}
    dump(run_dir / "protocol.json", protocol)
    progress(f"RUN_DIRECTORY: {run_dir.resolve()}")
    public_train, public_selection, audit, rejected = public_records(data_dir)
    historical_rows = sorted(public_train + public_selection, key=lambda r: r.path_id)
    splits = {"public_train": public_train, "public_selection": public_selection, "legacy_audit": audit}
    for split, count in PER_FAMILY.items():
        splits[f"generated_{split}"] = generate_split(split, count, SEED)
    splits = separate_geometry(splits, rejected)
    for name, rows in splits.items():
        if {r.label for r in rows} != {0, 1}:
            raise ValueError(f"Both classes required after filtering: {name}")
        save_rows(run_dir / "datasets" / f"{name}.jsonl", rows)
    dump(run_dir / "splits.json", {name: describe(rows) for name, rows in splits.items()})
    dump(run_dir / "excluded.json", rejected)
    progress("SPLITS " + json.dumps({name: len(rows) for name, rows in splits.items()}))

    cache = {}
    for split, rows in splits.items():
        progress(f"FEATURES {split}: {len(rows)} paths")
        for row in rows:
            if row.path_id in cache:
                raise ValueError(f"Nonunique path ID: {row.path_id}")
            cache[row.path_id] = multiscale_features(row.points)

    selected = None
    candidate_results = []
    fitted = {}
    for index, spec in enumerate(CANDIDATES):
        rows = splits["public_train"] + (splits["generated_train"] if spec["augmented"] else [])
        progress(f"TRAIN {spec['name']}: {len(rows)} paths")
        model = RandomForestClassifier(n_estimators=spec["n_estimators"], max_depth=spec["max_depth"],
            min_samples_leaf=spec["min_samples_leaf"], random_state=42, n_jobs=2)
        model.fit(feature_matrix(rows, spec["variant"], cache), [r.label for r in rows], sample_weight=fit_weights(rows))
        ps = positive_scores(model, feature_matrix(splits["public_selection"], spec["variant"], cache))
        gs = positive_scores(model, feature_matrix(splits["generated_selection"], spec["variant"], cache))
        threshold, objective = max(
            ((t, selection_objective(splits["public_selection"], ps, splits["generated_selection"], gs, t))
             for t in protocol["thresholds"]),
            key=lambda pair: (round(pair[1], 12), -abs(pair[0] - 0.5), -pair[0]))
        result = {"candidate": spec, "train_paths": len(rows), "threshold": threshold,
                  "selection_objective": objective,
                  "public_selection": metrics(splits["public_selection"], ps, threshold),
                  "generated_selection": metrics(splits["generated_selection"], gs, threshold)}
        candidate_results.append(result)
        fitted[spec["name"]] = (model, spec, threshold)
        if selected is None or round(objective, 12) > round(selected[0], 12):
            selected = (objective, index, model, spec, threshold, rows)
        progress(f"SELECTION {spec['name']}: objective={objective:.4f}, threshold={threshold:.2f}")
    dump(run_dir / "candidate_selection.json", candidate_results)
    _, selected_index, model, spec, threshold, train_rows = selected
    frozen = {"candidate": spec, "threshold": threshold, "train_paths": len(train_rows),
              "train_by_source": dict(Counter(r.metadata.get("source", "generated") for r in train_rows)),
              "selection_objective": selected[0], "candidate_index": selected_index,
              "frozen_before_final_evaluation": True, "refit": False}
    dump(run_dir / "selected.json", frozen)
    joblib.dump({"format": "pauseable-shape-v2-sklearn", "rf": model, "selection": frozen,
                 "feature_contract": feature_contract(spec["variant"])}, run_dir / "model.joblib")
    portable = export_forest(model, spec["variant"], threshold, frozen)
    dump(run_dir / "model.json", portable)
    progress(f"FROZEN {spec['name']} threshold={threshold:.2f}; evaluating final partitions now")

    historical = RandomForestClassifier(n_estimators=200, max_depth=5, min_samples_leaf=2,
        class_weight="balanced", random_state=42, n_jobs=2)

    historical.fit(np.stack([legacy_features(r.points) for r in historical_rows]),
                   [r.label for r in historical_rows])
    joblib.dump(historical, run_dir / "historical_baseline.joblib")
    comparisons = {"historical_baseline": (historical, "legacy9", 0.5),
                   "selected_model": (model, spec["variant"], threshold)}
    matched, matched_spec, matched_threshold = fitted["matched_legacy9_public"]
    comparisons["matched_baseline"] = (matched, matched_spec["variant"], matched_threshold)
    evaluations, prediction_rows = {}, []
    all_final_values, all_final_scores = [], []
    for split in ("generated_test", "generated_challenge", "legacy_audit"):
        evaluations[split] = {}
        for model_name, (estimator, variant, boundary) in comparisons.items():
            rows = splits[split]
            values = feature_matrix(rows, variant, cache)
            scores = positive_scores(estimator, values)
            result = metrics(rows, scores, boundary)
            evaluations[split][model_name] = result
            for row, score in zip(rows, scores):
                prediction_rows.append({"split": split, "path_id": row.path_id, "group_id": row.group_id,
                    "family": row.family, "label": row.label, "model": model_name,
                    "score_not_calibrated": float(score), "threshold": float(boundary),
                    "prediction": int(score >= boundary), "correct": bool(int(score >= boundary) == row.label)})
            if model_name == "selected_model":
                all_final_values.extend(values)
                all_final_scores.extend(scores)
            progress(f"FINAL {split} {model_name}: accuracy={result['accuracy']:.4f} recall={result['recall']:.4f}")
    portable_scores = [score_features(portable, vector) for vector in all_final_values]
    export_error = float(np.max(np.abs(np.asarray(portable_scores) - all_final_scores)))
    if export_error > 1e-12:
        raise AssertionError(f"Portable forest mismatch: {export_error}")

    ambiguous_rows = generate_ambiguous(SEED)
    save_rows(run_dir / "datasets" / "ambiguous_unlabelled.jsonl", ambiguous_rows)
    ambiguous = []
    for row in ambiguous_rows:
        values = multiscale_features(row.points)
        for model_name in ("historical_baseline", "selected_model"):
            estimator, variant, boundary = comparisons[model_name]
            count = 9 if variant == "legacy9" else len(values)
            score = float(positive_scores(estimator, values[:count][None, :])[0])
            ambiguous.append({"path_id": row.path_id, "family": row.family, "metadata": row.metadata,
                "label": None, "model": model_name, "score_not_calibrated": score,
                "synthetic_shape_class": int(score >= boundary), "accuracy": None})
    dump(run_dir / "ambiguous_scores.json", ambiguous)
    with (run_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)

    report = {"purpose": "Improved geometric repetition research model",
              "data_origin": "simulated_only", "personal_baseline_trained": False,
              "real_ld6004_validated": False, "clinical_wandering_validated": False,
              "automatic_alerts_enabled": False, "source": provenance,
              "splits": {name: describe(rows) for name, rows in splits.items()},
              "selection": frozen, "evaluations": evaluations,
              "historical_baseline_train_paths": len(historical_rows),
              "portable_export_check": {"paths": len(portable_scores), "max_absolute_error": export_error},
              "feature_contract": feature_contract(spec["variant"]),
              "versions": {"python": platform.python_version(), "numpy": np.__version__,
                           "scikit_learn": sklearn.__version__, "scipy": scipy.__version__,
                           "joblib": joblib.__version__},
              "duration_seconds": round(time.perf_counter() - started, 2)}
    dump(run_dir / "metrics.json", report)
    source_paths = sorted(HERE.glob("*.py")) + sorted((HERE / "legacy").glob("*.py")) + [HERE / "PROTOCOL.md"]
    dump(run_dir / "manifest.json", {"code": {str(p.relative_to(HERE)): sha(p) for p in source_paths},
        "model_sha256": sha(run_dir / "model.json"), "joblib_sha256": sha(run_dir / "model.joblib"),
        "datasets": {p.name: sha(p) for p in sorted((run_dir / "datasets").glob("*.jsonl"))}})
    write_report(run_dir, report)
    make_plots(run_dir, splits, prediction_rows, report)
    progress(f"COMPLETE: {run_dir.resolve()}")
    return run_dir


def write_report(run_dir, report):
    chosen = report["selection"]
    lines = ["# Pauseable 경로 형태 모델 개선 실험", "",
        "이 모델은 합성 경로의 반복 이동 형태를 분류합니다. 실제 치매 환자 배회나 개인 생활패턴을 학습한 모델은 아닙니다.", "",
        f"- 선택 모델: `{chosen['candidate']['name']}`",
        f"- 입력 특징: {len(report['feature_contract']['names'])}개",
        f"- 실제 학습 경로: {chosen['train_paths']}개; 출처별 {chosen['train_by_source']}",
        f"- 별도 선택 자료로 정한 판정 기준: {chosen['threshold']:.2f}",
        "- 선택 이후 최종 평가를 실시했으며, 평가 결과에 맞춘 재학습은 하지 않았습니다.",
        "- 모형 선택용 자료는 최종 모델 학습에 다시 포함하지 않았습니다.", "",
        "| 평가 자료 | 모델 | 경로 수 | 정확도 | 재현율 | 정밀도 | F1 |",
        "|---|---|---:|---:|---:|---:|---:|"]
    labels = {"generated_test": "새 합성 경로", "generated_challenge": "다른 구성의 합성 경로",
              "legacy_audit": "기존 SmartCare 재점검"}
    model_labels = {"historical_baseline": f"기존 {report['historical_baseline_train_paths']}경로 RF", "matched_baseline": "동일 개발 분할 기준 RF",
                    "selected_model": "선택 모델"}
    for split, results in report["evaluations"].items():
        for model_name, values in results.items():
            lines.append(f"| {labels[split]} | {model_labels[model_name]} | {values['paths']} | "
                f"{values['accuracy']:.1%} | {values['recall']:.1%} | {values['precision']:.1%} | {values['f1']:.3f} |")
    lines.extend(["", "## 결과를 해석하는 범위", "",
        "새 합성 경로는 학습 경로와 다른 기하 표본이지만 같은 생성기 계열의 자료입니다. 실제 환경 일반화 근거는 아닙니다.",
        "다른 구성 시험도 우리가 정의한 합성 규칙에 따른 시험입니다. 실제 레이더의 잡음·추적 누락·생활 맥락은 검증하지 않았습니다.",
        "기존 SmartCare 20개는 개발 중 이미 확인한 자료라 최종 독립 시험으로 부르지 않습니다.",
        "합성 증강 라벨은 반복/왕복 경로 생성 규칙에서 정했습니다. 원본 SmartCare 라벨과 의미가 완전히 같다고 보장할 수 없습니다.",
        "애매한 경로는 정답 미정으로 보존했으며 정확도에 포함하지 않았습니다. 점수는 실제 배회 확률이 아닙니다.",
        "정확도 구간과 혼동행렬도 합성 경로 라벨에 대한 값입니다. 모델이 반복 운동의 목적과 배회를 좌표만으로 구별하지는 못합니다.",
        "", "## 파일", "",
        "- `model.json`: pickle 없이 읽는 숲 구조와 특징 계약. 새 predict.py로 실행합니다.",
        "- `model.joblib`: 로컬에서 학습한 sklearn 모델. 이 실험 환경과 함께 보관합니다.",
        "- `candidate_selection.json`: 후보별 선택 자료 성능 및 기준값.",
        "- `predictions.csv`: 최종 시험 경로별 결과; 틀린 경로도 포함.",
        "- `datasets/`: 출처·그룹·분할·좌표·라벨 기록.",
        "- `manifest.json`: 코드·데이터·모델 해시.",
        "- `ambiguous_scores.json`: 정답 없는 경로의 점수 비교.",
        "", "## Pi5와의 관계", "",
        "JSON 숲을 C++로 실행할 수 있도록 내보냈지만, 현재 Pi5 앱에 설치하지 않았습니다. 동일한 특징 추출기의 C++ 이식과 값 일치 검증이 필요합니다.",
        "개인 기준선 학습·갱신 및 보호자 알림 정책은 이 모델과 별도로 Pi5에서 구현·검증해야 합니다.",
        f"내보낸 숲의 점수 비교: {report['portable_export_check']['paths']}경로, "
        f"최대 절대오차 {report['portable_export_check']['max_absolute_error']:.3g}.",
        "", "## 방법 참고", "",
        "- [SmartCare 원본](https://github.com/Unilasalle-SmartCare/smartcare-machinelearning)",
        "- [scikit-learn 그룹별 평가](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)",
        "- [scikit-learn 판정 기준 조정](https://scikit-learn.org/stable/modules/classification_threshold.html)", ""])
    (run_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def make_plots(run_dir, splits, predictions, report):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, 3, figsize=(13, 4))
    titles = {"generated_test": "Fresh synthetic paths", "generated_challenge": "Alternate construction",
              "legacy_audit": "Legacy audit (already studied)"}
    for axis, (split, results) in zip(axes, report["evaluations"].items()):
        values = [results[name]["accuracy"] for name in ("historical_baseline", "matched_baseline", "selected_model")]
        bars = axis.bar(["Prior RF", "Matched RF", "Selected"], values, color=["#93a0ae", "#6b89a7", "#206bb5"])
        axis.set_ylim(0, 1.13)
        axis.set_title(titles[split], fontsize=11)
        axis.set_ylabel("Accuracy against synthetic labels")
        for bar, value in zip(bars, values):
            axis.text(bar.get_x()+bar.get_width()/2, value+0.02, f"{value:.1%}", ha="center")
    figure.suptitle("Pauseable geometric repetition experiment — no real radar/patient validation", fontsize=12)
    figure.tight_layout()
    figure.savefig(run_dir / "comparison.png", dpi=160)
    plt.close(figure)


    rows_by_id = {r.path_id: r for r in splits["generated_test"]}
    chosen = [p for p in predictions if p["split"] == "generated_test" and p["model"] == "selected_model"]
    chosen.sort(key=lambda p: (p["correct"], abs(p["score_not_calibrated"] - p["threshold"])))
    figure, axes = plt.subplots(3, 4, figsize=(14, 10))
    for axis, prediction in zip(axes.flat, chosen[:12]):
        row = rows_by_id[prediction["path_id"]]
        points = np.asarray(row.points)
        axis.plot(points[:, 0], points[:, 1], color="#2967a1" if prediction["correct"] else "#c74740", linewidth=1)
        axis.scatter(*points[0], facecolors="none", edgecolors="#1e9d68", s=45, zorder=3)
        axis.scatter(*points[-1], marker="x", c="#243142", s=35, zorder=3)
        axis.set_aspect("equal", adjustable="datalim")
        axis.set_title(f"{row.family}\nlabel={row.label} pred={prediction['prediction']} score={prediction['score_not_calibrated']:.3f}", fontsize=9)
        axis.grid(alpha=0.2)
    figure.suptitle("Selected model: errors / boundary cases on fresh synthetic paths\nCoordinates are arbitrary units; green=start, x=end", fontsize=12)
    figure.tight_layout(rect=(0, 0, 1, .94))
    figure.savefig(run_dir / "inspect_paths.png", dpi=130)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=HERE / "training-runs")
    args = parser.parse_args()
    train(args.data_dir, args.output_dir)


if __name__ == "__main__":
    main()
