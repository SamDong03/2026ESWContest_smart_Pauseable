

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np

from portable_forest import feature_contract, load_forest, score_features
from legacy.features import extract_features as legacy_features
from shape_features import extract_features as multiscale_features


HERE = Path(__file__).resolve().parent
PROTOCOL = "pauseable-frozen-synthetic-robustness-v1"
CONDITIONS = ("original", "drop_interior_30pct", "gaussian_005_diameter",
              "gaussian_020_diameter")
TITLES = ("Original", "Drop 30% interior", "Gaussian 0.5% D", "Gaussian 2% D")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def perturb(points, path_id: str, condition: str) -> np.ndarray:
    coordinates = np.asarray(points, dtype=np.float64)
    if condition == "original":
        return coordinates.copy()
    seed = int.from_bytes(hashlib.sha256(
        f"{PROTOCOL}:{path_id}:{condition}".encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    if condition == "drop_interior_30pct":
        interior = np.arange(1, len(coordinates) - 1)
        dropped = rng.choice(interior, size=int(np.floor(0.3 * len(interior))), replace=False)
        keep = np.ones(len(coordinates), dtype=bool)
        keep[dropped] = False
        return coordinates[keep]
    deviation = {"gaussian_005_diameter": 0.005, "gaussian_020_diameter": 0.02}[condition]
    differences = coordinates[:, None, :] - coordinates[None, :, :]
    diameter = float(np.hypot(differences[:, :, 0], differences[:, :, 1]).max())
    return coordinates + rng.normal(0.0, deviation * diameter, size=coordinates.shape)


def metrics(labels, predictions) -> dict:
    actual, predicted = np.asarray(labels), np.asarray(predictions)
    if len(actual) == 0 or actual.shape != predicted.shape:
        raise ValueError("Need nonempty paired labels and predictions")
    if not np.isin(actual, [0, 1]).all() or not np.isin(predicted, [-1, 0, 1]).all():
        raise ValueError("Labels must be binary; -1 means abstention")
    matrix = [[int(np.sum((actual == label) & (predicted == output)))
               for output in (0, 1, -1)] for label in (0, 1)]
    total, scored = len(actual), int(np.sum(predicted >= 0))
    tn, fp, abstain_negative = matrix[0]
    fn, tp, abstain_positive = matrix[1]
    negative_recall = tn / (tn + fp + abstain_negative) if sum(matrix[0]) else None
    positive_recall = tp / (tp + fn + abstain_positive) if sum(matrix[1]) else None
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = positive_recall if positive_recall is not None else 0.0
    return {"total_original_paths": total, "scored": scored, "abstentions": total - scored,
            "coverage": scored / total, "accuracy_all_paths": (tn + tp) / total,
            "accuracy_scored_paths": (tn + tp) / scored if scored else None,
            "class_0_recall_all_paths": negative_recall,
            "class_1_recall_all_paths": positive_recall,
            "balanced_accuracy_all_paths": (negative_recall + positive_recall) / 2
              if negative_recall is not None and positive_recall is not None else None,
            "class_1_precision": precision,
            "class_1_f1_with_abstentions": 2 * precision * recall / (precision + recall)
              if precision + recall else 0.0,
            "confusion_rows_actual_0_1_columns_predicted_0_1_abstain": matrix}


def check_metric_logic():
    example = metrics([0, 0, 1, 1], [0, 1, -1, 1])
    assert example["coverage"] == 0.75
    assert example["accuracy_all_paths"] == 0.5
    assert example["accuracy_scored_paths"] == 2 / 3
    assert example["class_1_recall_all_paths"] == 0.5
    assert example["class_0_recall_all_paths"] == 0.5
    assert example["confusion_rows_actual_0_1_columns_predicted_0_1_abstain"] == [[1, 1, 0], [0, 1, 1]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--trust-local-models", action="store_true")
    args = parser.parse_args()
    if not args.trust_local_models:
        parser.error("Local joblib loading requires --trust-local-models; use only your own trained models")
    run = args.run_dir.resolve()
    for name in ("robustness.json", "robustness.png", "ROBUSTNESS.md"):
        if (run / name).exists():
            parser.error(f"Audit output already exists: {name}; refusing to overwrite")
    protocol_text = (HERE / "ROBUSTNESS-PROTOCOL.md").read_text(encoding="utf-8")
    if "before executing" not in protocol_text:
        raise ValueError("Missing predeclared audit protocol")
    check_metric_logic()
    paths = [run / name for name in ("model.json", "model.joblib", "historical_baseline.joblib",
                                     "datasets/generated_test.jsonl")]
    original_hashes = {str(p.relative_to(run)): sha(p) for p in paths}
    portable = load_forest(run / "model.json")
    selected = joblib.load(run / "model.joblib")
    if selected["feature_contract"] != feature_contract(portable["feature_contract"]["variant"]):
        raise ValueError("Selected joblib feature contract differs")
    if selected["selection"] != portable["selection"]:
        raise ValueError("Selected JSON/joblib selection metadata differs")
    models = {
        "historical_baseline": (joblib.load(run / "historical_baseline.joblib"), "legacy9", 0.5),
        "selected_model": (selected["rf"], portable["feature_contract"]["variant"],
                           portable["decision_threshold"]),
    }
    rows = [json.loads(line) for line in paths[-1].read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != 1000 or len({r["path_id"] for r in rows}) != 1000:
        raise ValueError("Expected exactly 1000 unique frozen generated_test paths")
    labels = [int(row["label"]) for row in rows]
    if Counter(labels) != {0: 500, 1: 500}:
        raise ValueError("Unexpected class distribution in frozen audit inputs")
    results, details, verification = {}, [], {}
    for condition in CONDITIONS:
        print(f"AUDIT {condition}: same {len(rows)} base paths", flush=True)
        feature_rows, reasons = {name: [] for name in models}, {name: {} for name in models}
        for index, row in enumerate(rows):
            coordinates = perturb(row["points"], row["path_id"], condition)
            for name, (_, variant, _) in models.items():
                try:
                    vector = (legacy_features if variant == "legacy9" else multiscale_features)(coordinates)
                    feature_rows[name].append((index, vector))
                except ValueError as error:
                    reasons[name][index] = str(error)
        results[condition] = {}
        for name, (forest, _, threshold) in models.items():
            pairs = feature_rows[name]
            predictions = np.full(len(rows), -1, dtype=int)
            scores = np.full(len(rows), np.nan)
            if pairs:
                indices = [index for index, _ in pairs]
                matrix = np.vstack([vector for _, vector in pairs])
                positive_column = list(forest.classes_).index(1)
                values = forest.predict_proba(matrix)[:, positive_column]
                predictions[indices] = (values >= threshold).astype(int)
                scores[indices] = values
                if name == "selected_model":
                    compared = min(5, len(pairs))
                    if compared != 5:
                        raise ValueError("Need five scored cases for portable JSON verification")
                    errors = [abs(score_features(portable, matrix[i]) - float(values[i]))
                              for i in range(compared)]
                    if max(errors) > 1e-12:
                        raise ValueError("Portable and sklearn model predictions differ")
                    verification[condition] = {"compared_paths": compared,
                                               "max_absolute_score_error": max(errors)}
            result = metrics(labels, predictions)
            result["threshold_frozen"] = threshold
            result["families"] = {}
            for family in sorted({row["family"] for row in rows}):
                indices = [i for i, row in enumerate(rows) if row["family"] == family]
                result["families"][family] = metrics(np.asarray(labels)[indices], predictions[indices])
            results[condition][name] = result
            print(f"  {name}: accuracy_all={result['accuracy_all_paths']:.4f}, "
                  f"coverage={result['coverage']:.4f}, label1_recall={result['class_1_recall_all_paths']:.4f}",
                  flush=True)
            for index, row in enumerate(rows):
                details.append({"condition": condition, "model": name, "path_id": row["path_id"],
                                "family": row["family"], "label": row["label"],
                                "prediction": int(predictions[index]) if predictions[index] >= 0 else None,
                                "score": float(scores[index]) if np.isfinite(scores[index]) else None,
                                "abstention_reason": reasons[name].get(index)})
    final_hashes = {str(p.relative_to(run)): sha(p) for p in paths}
    if original_hashes != final_hashes:
        raise ValueError("Frozen model or original dataset changed during audit")
    report = {"protocol": PROTOCOL, "created_at": datetime.now(timezone.utc).isoformat(),
              "post_freeze_audit": True, "model_or_threshold_updated": False,
              "unique_base_paths": len(rows), "conditions": list(CONDITIONS),
              "path_ids_sha256": hashlib.sha256("\n".join(r["path_id"] for r in rows).encode()).hexdigest(),
              "source_hashes": original_hashes, "frozen_inputs_unchanged": True,
              "protocol_sha256": sha(HERE / "ROBUSTNESS-PROTOCOL.md"),
              "audit_code_sha256": sha(Path(__file__)),
              "portable_score_verification": verification,
              "limitation": "Paired synthetic geometry sensitivity only; not LD6004 noise or clinical wandering accuracy.",
              "metrics": results, "predictions": details}
    (run / "robustness.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                          encoding="utf-8")
    lines = ["# Frozen-model synthetic sensitivity audit", "",
             "This post-freeze audit did not train or tune either model. Each row reuses the same 1,000 original paths.",
             "Perturbed inputs keep their underlying generator label. Settings are arbitrary stress levels, not measured LD6004 noise.", "",
             "| Condition | Model | Coverage | Accuracy / all paths | Label 0 recall | Label 1 recall | Abstentions |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for condition, title in zip(CONDITIONS, TITLES):
        for name in models:
            m = results[condition][name]
            lines.append(f"| {title} | {name} | {m['coverage']:.1%} | {m['accuracy_all_paths']:.1%} | "
                         f"{m['class_0_recall_all_paths']:.1%} | {m['class_1_recall_all_paths']:.1%} | {m['abstentions']} |")
    lines += ["", "Accuracy counts abstentions as unsuccessful; per-class recall retains them in the denominator.",
              "Rows are paired conditions, not independent additional samples. No clinical or actual radar accuracy follows from this audit.",
              "Five selected-model scores per condition matched the portable JSON evaluator within 1e-12.",
              "Frozen models and original test-file hashes are unchanged. Full per-path/family results are in robustness.json.",
              "", "![Paired synthetic sensitivity](robustness.png)", ""]
    (run / "ROBUSTNESS.md").write_text("\n".join(lines), encoding="utf-8")
    os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    positions = np.arange(len(CONDITIONS))
    for offset, (name, color) in enumerate((("historical_baseline", "#64748b"), ("selected_model", "#0f766e"))):
        for axis, metric, title in zip(axes, ("accuracy_all_paths", "class_1_recall_all_paths"),
                                      ("Accuracy, all 1,000 base paths", "Repetitive-shape recall, all 500 label-1 paths")):
            values = [results[c][name][metric] * 100 for c in CONDITIONS]
            bars = axis.bar(positions + (offset - 0.5) * 0.36, values, 0.36, label=name.replace("_", " "), color=color)
            axis.bar_label(bars, labels=[f"{v:.1f}" for v in values], padding=3, fontsize=8)
            axis.set_xticks(positions, ["Original", "Drop30%", "Noise0.5%D", "Noise2%D"])
            axis.set_ylim(0, 110)
            axis.set_ylabel("Percent")
            axis.set_title(title, fontsize=11)
            axis.grid(axis="y", alpha=0.2)
            axis.set_axisbelow(True)
    axes[0].legend(loc="lower left")
    figure.suptitle("Frozen-model sensitivity to synthetic perturbations", fontsize=15)
    figure.text(0.5, 0.03, "Paired reuse of 1,000 base paths; arbitrary noise, not LD6004 measurements. D = original path diameter.",
                ha="center", fontsize=10)
    figure.tight_layout(rect=(0, 0.08, 1, 0.94))
    figure.savefig(run / "robustness.png", dpi=170)
    plt.close(figure)
    print(f"SAVED {run / 'ROBUSTNESS.md'}", flush=True)


if __name__ == "__main__":
    main()
