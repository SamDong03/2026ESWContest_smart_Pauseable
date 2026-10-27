import hashlib
import json
import os
import tempfile
from pathlib import Path

cache = tempfile.TemporaryDirectory(prefix=".mpl-cache-", dir=Path(__file__).resolve().parent)
os.environ.setdefault("MPLCONFIGDIR", cache.name)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
EVAL = OUT / "data"
SOURCE = EVAL / "visual_data.json"
COMPARISON = EVAL / "baseline_comparison.json"
data = json.loads(SOURCE.read_text(encoding="utf-8"))
comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
if comparison.get("source_type") != "synthetic" or comparison.get("clinical_validation") is not False:
    raise ValueError("Review the figure disclosure before changing its data provenance")
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 15,
    "axes.titleweight": "bold", "axes.labelcolor": "#52665b", "text.color": "#203b30",
    "axes.edgecolor": "#cedad2", "xtick.color": "#5b6f63", "ytick.color": "#5b6f63",
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.spines.top": False, "axes.spines.right": False,
})
manifest = {
    "scope": "Stored synthetic verification fixture; not patient performance",
    "model_training_performed": False,
    "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE, COMPARISON)},
    "source_paths": {p.name: "data/" + p.name for p in (SOURCE, COMPARISON)},
    "figures": [],
}


def save(fig, name, details):
    fig.savefig(OUT / name, dpi=170, bbox_inches="tight", metadata={"Software": "PAUSEABLE documentation"})
    plt.close(fig)
    manifest["figures"].append({"file": name, **details})


heat = data["heatmaps"]
events = np.asarray(heat["event_matrix"], dtype=float)
features = np.asarray(heat["standardized_features"], dtype=float)
if events.shape != (8, 48) or features.shape != (54, 48):
    raise ValueError("Unexpected stored matrix dimensions")
if not np.isfinite(events).all() or not np.isfinite(features).all():
    raise ValueError("Stored heatmap includes nonfinite values")
if int(events.sum()) != 52 or not np.equal(events, events.astype(int)).all():
    raise ValueError("Stored event counts disagree with the checked fixture")
labels = ["Fridge", "Door lock", "Microwave", "Washer", "Dryer", "Air purifier", "Air conditioner", "Dishwasher"]
fig, axes = plt.subplots(2, 1, figsize=(12, 8.2), gridspec_kw={"height_ratios": [1, 1.35]})
fig.subplots_adjust(hspace=0.48, left=0.14, right=0.92, top=0.92, bottom=0.09)
top = axes[0].imshow(events, aspect="auto", interpolation="nearest", cmap="YlGnBu", vmin=0, vmax=heat["event_max"])
axes[0].set_yticks(range(8), labels)
axes[0].set_title("State-change events per hour", loc="left", pad=14)
cb = fig.colorbar(top, ax=axes[0], pad=0.02, fraction=0.025)
cb.set_label("Events / hour")
cb.set_ticks(range(heat["event_max"] + 1))
bottom = axes[1].imshow(features, aspect="auto", interpolation="nearest", cmap="viridis", vmin=-2, vmax=4)
sizes = np.asarray(heat["feature_group_sizes"])
ends = np.cumsum(sizes)
centers = ends - sizes / 2 - 0.5
axes[1].set_yticks(centers, [*labels, "Time / weekday"])
for boundary in ends[:-1]:
    axes[1].axhline(boundary - 0.5, color="white", alpha=0.8, linewidth=0.7)
axes[1].set_title("Standardized model features: 54 variables x 48 hours", loc="left", pad=14)
cb = fig.colorbar(bottom, ax=axes[1], pad=0.02, fraction=0.025)
cb.set_label("Standardized value")
cb.set_ticks([-2, 0, 2, 4])
for ax in axes:
    ax.set_xticks([-0.5, 11.5, 23.5, 35.5, 47.5], ["0", "12", "24", "36", "48"])
    ax.set_xlabel("Elapsed hour")
    ax.tick_params(length=0, pad=7)
save(fig, "ha-event-features.png", {"event_shape": [8, 48], "feature_shape": [54, 48], "event_total": 52, "standardization": "stored training scaler; no refit", "color_clip_only": [-2, 4]})

held = data["holdout"]
if len(held["times"]) != 144 or len(held["ae_errors"]) != 144 or len(held["if_scores"]) != 144:
    raise ValueError("Unexpected stored holdout length")
fig, axes = plt.subplots(2, 1, figsize=(12, 6.8), sharex=True)
fig.subplots_adjust(hspace=0.72, left=0.09, right=0.97, top=0.86, bottom=0.1)
for ax, values, kind, label, color in [
    (axes[0], held["if_scores"], "if", "Isolation Forest anomaly score", "#315f92"),
    (axes[1], held["ae_errors"], "ae", "Autoencoder reconstruction error", "#147f82"),
]:
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite model score")
    x = np.arange(len(values))
    ax.plot(x, values, color=color, linewidth=1.7, label="Stored test score")
    ax.scatter(x, values, color=color, s=9, zorder=3)
    for key, line_color in [("attention", "#a46a1e"), ("risk", "#a54545")]:
        ax.axhline(data["thresholds"][kind][key], color=line_color, linestyle="--", linewidth=1.3, label=f"{key} threshold")
    ax.set_title(label, loc="left", pad=40)
    ax.set_ylabel("Score" if kind == "if" else "Mean squared error")
    ax.grid(axis="y", color="#e6ece8", linewidth=0.8)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), borderaxespad=0, frameon=False, ncol=3, fontsize=9)
    ax.set_xlim(0, 143)
axes[1].set_xlabel("Chronological holdout sample (144 normal-candidate samples)")
save(fig, "ha-model-scores.png", {"sample_count": 144, "kind": "saved holdout scores, not training loss", "thresholds": data["thresholds"]})

methods = ["baseline", "baseline_if", "baseline_ae", "hybrid"]
method_names = ["Baseline", "+ IF", "+ AE", "Hybrid"]
colors = ["#245c45", "#315f92", "#147f82", "#a46a1e"]
fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
fig.subplots_adjust(wspace=0.17, left=0.08, right=0.98, top=0.82, bottom=0.15)
cohorts = []
for ax, family, title, expected_total in [
    (axes[0], "repetition_hypothesis", "Repetition hypothesis scenarios", 24),
    (axes[1], "benign_context", "Benign-context control scenarios", 48),
]:
    counts = [comparison["families"][family][method]["alert_cases"] for method in methods]
    if any(comparison["families"][family][method]["cases"] != expected_total for method in methods):
        raise ValueError("Scenario denominator disagrees with stored cohort")
    if any(not 0 <= value <= expected_total for value in counts):
        raise ValueError("Alert count outside cohort")
    rates = np.asarray(counts) / expected_total * 100
    bars = ax.bar(method_names, rates, color=colors, width=0.65)
    ax.set_ylim(0, 114)
    ax.set_yticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100"])
    ax.set_title(title + f" (n={expected_total})", loc="left", pad=16, fontsize=13)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#e6ece8", linewidth=0.8)
    for bar, count, rate in zip(bars, counts, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 3, f"{count}/{expected_total}", ha="center", fontsize=11, weight="bold")
    cohorts.append({"family": family, "total": expected_total, "alert_cases": counts})
axes[0].set_ylabel("Scenarios with an alert (%)")
save(fig, "ha-component-comparison.png", {"methods": methods, "cohorts": cohorts,
    "routine_correction_applied": comparison["routine_correction_applied"],
    "ablation_semantics": comparison["ablation_semantics"],
    "interpretation": "scenario alert counts, not clinical accuracy"})

manifest["loss_curve"] = "Not plotted: epoch/iteration loss history is not present in the selected tracked evaluation JSON."
(OUT / "evaluation_figure_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
