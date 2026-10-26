import csv
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from dataset import load_trajectories, verified_sources


BASE = Path(__file__).resolve().parent
RUN = BASE / "runs" / "20260909T055429194926Z"


verified_sources(BASE / "data")

trajectories = load_trajectories(
    BASE / "data" / "dataset-validacao.json"
)
paths = {path.path_id: path for path in trajectories}

with (RUN / "predictions.csv").open(
    encoding="utf-8", newline=""
) as file:
    rows = list(csv.DictReader(file))

if len(rows) != 20:
    raise ValueError("검증 경로가 20개인지 확인해 주세요.")

for row in rows:
    path = paths[row["path_id"]]
    if path.label != int(row["synthetic_label"]):
        raise ValueError("원본 라벨과 예측 파일의 라벨이 다릅니다.")


stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = RUN / f"figures-{stamp}"
output.mkdir()

LABELS = {0: "NW", 1: "W"}


def is_wrong(row):
    return int(row["synthetic_label"]) != int(row["rf_prediction"])


def draw_path(ax, row, detail=False):
    path = paths[row["path_id"]]
    points = path.points
    xs, ys = zip(*points)

    actual = int(row["synthetic_label"])
    predicted = int(row["rf_prediction"])
    score = float(row["rf_score_not_calibrated"])
    wrong = is_wrong(row)
    color = "#dc2626" if wrong else "#2563eb"

    ax.plot(
        xs, ys,
        color=color,
        linewidth=1.6,
        marker=".",
        markersize=4,
    )


    ax.scatter(
        [xs[0]], [ys[0]],
        s=90,
        facecolors="none",
        edgecolors="#16a34a",
        linewidths=2,
        zorder=4,
    )
    ax.scatter(
        [xs[-1]], [ys[-1]],
        s=55,
        marker="x",
        color="#111827",
        linewidths=2,
        zorder=5,
    )

    if detail:

        for start, end in zip(points[:-1], points[1:]):
            if start != end:
                ax.annotate(
                    "",
                    xy=end,
                    xytext=start,
                    arrowprops={
                        "arrowstyle": "->",
                        "color": color,
                        "lw": 1.2,
                    },
                )

        for index, point in enumerate(points):
            ax.annotate(
                str(index),
                xy=point,
                xytext=(5, 6),
                textcoords="offset points",
                fontsize=9,
                color="#111827",
            )

    number = row["path_id"].rsplit(":", 1)[1]
    result = "WRONG" if wrong else "OK"

    ax.set_title(
        f"Path {number} | {result}\n"
        f"True={LABELS[actual]}  Pred={LABELS[predicted]}"
        f"  Score={score:.4f}",
        fontsize=10 if not detail else 13,
        color="#dc2626" if wrong else "#111827",
    )
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.2)
    ax.tick_params(labelsize=8)

    if wrong:
        for spine in ax.spines.values():
            spine.set_color("#dc2626")
            spine.set_linewidth(2)


all_points = [
    point
    for row in rows
    for point in paths[row["path_id"]].points
]
all_x, all_y = zip(*all_points)
padding = 0.05 * max(
    max(all_x) - min(all_x),
    max(all_y) - min(all_y),
    1,
)

fig, axes = plt.subplots(
    4, 5,
    figsize=(18, 13),
    layout="constrained",
)

for ax, row in zip(axes.flat, rows):
    draw_path(ax, row)
    ax.set_xlim(min(all_x) - padding, max(all_x) + padding)

    ax.set_ylim(max(all_y) + padding, min(all_y) - padding)

fig.suptitle(
    "SmartCare: 20 synthetic validation paths\n"
    "NW = non-wandering | W = wandering | Blue = correct | Red = incorrect\n"
    "Green circle = start | Black X = end | Score is NOT a calibrated probability",
    fontsize=13,
)
fig.supxlabel("x: source image coordinates, not metres")
fig.supylabel("y: source image coordinates, increasing downward")

overview = output / "validation_paths.png"
fig.savefig(overview, dpi=160)
plt.close(fig)

print(f"전체 경로 그림: {overview}")


wrong_rows = [row for row in rows if is_wrong(row)]

for row in wrong_rows:
    fig, ax = plt.subplots(
        figsize=(10, 7),
        layout="constrained",
    )
    draw_path(ax, row, detail=True)

    points = paths[row["path_id"]].points
    xs, ys = zip(*points)
    margin = 0.12 * max(
        max(xs) - min(xs),
        max(ys) - min(ys),
        1,
    )

    ax.set_xlim(min(xs) - margin, max(xs) + margin)
    ax.set_ylim(max(ys) + margin, min(ys) - margin)
    ax.set_xlabel("x: source image coordinates")
    ax.set_ylabel("y: source image coordinates")
    fig.suptitle(
        "Misclassified synthetic path\n"
        "Numbers = point order, NOT seconds | Arrows = traversal direction",
        fontsize=13,
    )

    number = row["path_id"].rsplit(":", 1)[1]
    destination = output / f"wrong_{number}.png"
    fig.savefig(destination, dpi=180)
    plt.close(fig)

    print(f"오답 확대 그림: {destination}")

print(f"오답 수: {len(wrong_rows)}")
print(f"그림 저장 완료: {output}")
