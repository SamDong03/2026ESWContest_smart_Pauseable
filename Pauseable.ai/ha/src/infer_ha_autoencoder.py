import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd


FIELDNAMES = [
    "window_end",
    "ae_reconstruction_error",
    "ae_score",
    "ae_level",
    "ae_reason",
]

LEVEL_SCORE = {
    "normal": 0,
    "attention": 45,
    "risk": 75,
}


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def relu(values):
    return np.maximum(values, 0.0)


def forward_autoencoder(x_scaled, weights):
    values = x_scaled
    layers = weights["layers"]
    for index, layer in enumerate(layers):
        weight = np.asarray(layer["weight"], dtype=np.float32)
        bias = np.asarray(layer["bias"], dtype=np.float32)
        values = values @ weight.T + bias
        if index < len(layers) - 1:
            values = relu(values)
    return values


def prepare_features(df, feature_columns):
    prepared = df.copy()
    missing = sorted(set(feature_columns) - set(prepared.columns))
    if missing:
        raise ValueError("Legacy AE schema mismatch; retrain using current features: " + ", ".join(missing))
    values = prepared[feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype="float32")
    if not np.isfinite(values).all():
        raise ValueError("AE features contain missing or non-finite values")

    return (
        prepared[feature_columns]
        .apply(pd.to_numeric, errors="coerce")
        .astype("float32")
        .to_numpy()
    )


def level_for_error(error, thresholds):
    if error >= float(thresholds["risk_threshold"]):
        return "risk"
    if error >= float(thresholds["attention_threshold"]):
        return "attention"
    return "normal"


def reason_for_error(error, level, thresholds):
    if level == "risk":
        return (
            "autoencoder reconstruction error "
            f"{error:.6f} reached risk threshold "
            f"{float(thresholds['risk_threshold']):.6f}"
        )
    if level == "attention":
        return (
            "autoencoder reconstruction error "
            f"{error:.6f} reached attention threshold "
            f"{float(thresholds['attention_threshold']):.6f}"
        )
    return ""


def infer(features_path, model_dir):
    model_dir = Path(model_dir)
    df = pd.read_csv(features_path)

    feature_columns = load_json(model_dir / "feature_columns.json")
    scaler = load_json(model_dir / "scaler.json")
    thresholds = load_json(model_dir / "threshold.json")
    weights = load_json(model_dir / "ha_autoencoder_weights.json")

    if df.empty:
        return []

    x = prepare_features(df, feature_columns)
    mean = np.asarray(scaler["mean"], dtype=np.float32)
    scale = np.asarray(scaler["scale"], dtype=np.float32)
    scale = np.where(scale == 0, 1.0, scale)

    x_scaled = (x - mean) / scale
    output = forward_autoencoder(x_scaled, weights)
    errors = np.mean((x_scaled - output) ** 2, axis=1)

    rows = []
    for index, error in enumerate(errors.tolist()):
        level = level_for_error(error, thresholds)
        rows.append(
            {
                "window_end": df.loc[index, "window_end"],
                "ae_reconstruction_error": f"{error:.6f}",
                "ae_score": LEVEL_SCORE[level],
                "ae_level": level,
                "ae_reason": reason_for_error(error, level, thresholds),
            }
        )
    return rows


def write_rows(path, rows):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "--features", dest="input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--model-dir", default="models")
    args = parser.parse_args()

    rows = infer(args.input, args.model_dir)

    if args.output:
        write_rows(args.output, rows)
        print(f"saved: {args.output}")

    if rows:
        print(pd.DataFrame(rows)["ae_level"].value_counts().to_string())
    else:
        print("ae_level")
        print("(no feature rows)")


if __name__ == "__main__":
    main()
