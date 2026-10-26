import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pandas as pd

from ha_anomaly_models import score_frame
from ha_event_history import update_history
from ha_coverage import usable_windows, observation_report
from ha_runtime_health import load_baseline, validate_selection
from ha_model_lifecycle import Lifecycle, SCHEMA, combine
from make_ha_features import build_features, parse_time


BASE = Path(__file__).resolve().parents[1]
LEVEL_RANK = {"normal": 0, "attention": 1, "risk": 2}
AE_COLUMNS = [
    "ae_reconstruction_error",
    "ae_score",
    "ae_level",
    "ae_reason",
]


def resolve_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE / path


def run(cmd):
    print("$ " + " ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


def autoencoder_artifacts_exist(model_dir):
    required = [
        "feature_columns.json",
        "scaler.json",
        "threshold.json",
        "ha_autoencoder_weights.json",
    ]
    return all((model_dir / name).exists() for name in required)


def normalize_level(value):
    level = str(value or "").strip().lower()
    if level in LEVEL_RANK:
        return level
    return "normal"


def as_int(value, default=0):
    try:
        if pd.isna(value):
            return default
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def append_reason(current, reason):
    if not reason:
        return current

    parts = [part.strip() for part in str(current or "").split(";") if part.strip()]
    if reason not in parts:
        parts.append(reason)
    return "; ".join(parts)


def merge_autoencoder_result(result_path, ae_path):
    result = pd.read_csv(result_path)
    ae = pd.read_csv(ae_path)

    result = result.drop(columns=[c for c in AE_COLUMNS if c in result.columns])
    merged = result.merge(ae, on="window_end", how="left")

    for column in AE_COLUMNS:
        if column not in merged.columns:
            merged[column] = ""
        merged[column] = merged[column].fillna("")

    if "risk_score" not in merged.columns:
        merged["risk_score"] = 0
    if "level" not in merged.columns:
        merged["level"] = "normal"
    if "primary_pattern" not in merged.columns:
        merged["primary_pattern"] = ""
    if "reasons" not in merged.columns:
        merged["reasons"] = ""

    for index, row in merged.iterrows():
        ae_level = normalize_level(row.get("ae_level", "normal"))
        current_level = normalize_level(row.get("level", "normal"))
        ae_reason = str(row.get("ae_reason", "") or "").strip()

        if ae_level in ("attention", "risk"):
            merged.at[index, "reasons"] = append_reason(row.get("reasons", ""), ae_reason)

        if LEVEL_RANK[ae_level] > LEVEL_RANK[current_level]:
            merged.at[index, "level"] = ae_level
            merged.at[index, "risk_score"] = max(
                as_int(row.get("risk_score")),
                as_int(row.get("ae_score")),
            )
            if not str(row.get("primary_pattern", "") or "").strip() or current_level == "normal":
                merged.at[index, "primary_pattern"] = "autoencoder_anomaly"

    merged["level"] = merged["level"].apply(normalize_level)
    merged["risk_score"] = (
        pd.to_numeric(merged["risk_score"], errors="coerce")
        .fillna(0)
        .round()
        .astype(int)
    )
    merged.to_csv(result_path, index=False)
    return merged


def is_standard_csv(path):
    df = pd.read_csv(path, nrows=5)
    required = {"event_time", "device_type", "signal_type", "action"}
    return required.issubset(set(df.columns))


def clean_standard_csv(input_path, output_path):
    df = pd.read_csv(input_path)

    action = df["action"].astype(str).str.strip().str.lower()
    df["action"] = action

    numeric_action = action.str.fullmatch(r"[-+]?\d+(\.\d+)?")
    bad_action = (
        action.isin(["initial", "unknown", "unavailable", "none", "nan", ""])
        | action.str.match(r"\d{4}-\d{2}-\d{2}")
    )

    valid = (
        ((df["device_type"] == "fridge")
         & (df["signal_type"] == "door")
         & action.isin(["open", "close"]))
        |
        ((df["device_type"].isin(["washer", "dryer", "dishwasher"]))
         & (df["signal_type"] == "operation")
         & action.isin(["running", "idle", "done", "paused", "power_off", "off", "on"]))
        |
        ((df["device_type"] == "air_purifier")
         & (df["signal_type"].isin(["power", "mode", "speed"]))
         & (~bad_action))
        |
        ((df["device_type"] == "door_lock")
         & (df["signal_type"] == "lock")
         & action.isin(["lock", "unlock"]))
        |
        ((df["device_type"] == "microwave")
         & (
             ((df["signal_type"] == "power") & action.isin(["on", "off"]))
             |
             ((df["signal_type"] == "operation")
              & action.isin(["running", "idle", "done", "paused", "off", "on"]))
         ))
        |
        ((df["device_type"] == "air_conditioner")
         & (
             ((df["signal_type"].isin(["power", "mode", "speed"])) & (~bad_action))
             |
             ((df["signal_type"] == "temperature") & (numeric_action | (~bad_action)))
         ))
    )

    clean = df[valid].copy()
    clean.to_csv(output_path, index=False)

    print(f"standard rows: {len(df)}")
    print(f"clean rows: {len(clean)}")


parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--baseline", default="models/user_001_real_baseline_v2.json")
parser.add_argument("--prefix", default="ha_pipeline")
parser.add_argument("--update-baseline", action="store_true")
parser.add_argument("--baseline-history", default="data/features/user_001_baseline_history_v2.csv")
parser.add_argument("--quarantine", default="data/features/user_001_quarantine_v2.csv")
parser.add_argument("--abnormal-log", default="outputs/user_001_abnormal_log_v2.csv")
parser.add_argument("--max-history-days", type=int, default=30)
parser.add_argument("--max-review-days", type=int, default=90)
parser.add_argument("--init-history-from-current-normal", action="store_true")
parser.add_argument("--autoencoder", action=argparse.BooleanOptionalAction, default=True)
parser.add_argument("--autoencoder-model-dir", default="models")
parser.add_argument("--model-dir", default="models/anomaly_current")
parser.add_argument("--data-source", choices=["local", "public", "synthetic", "unknown"], default="unknown")
parser.add_argument("--event-history")
parser.add_argument("--window-start")
parser.add_argument("--window-end")
parser.add_argument('--household-id', default='unconfigured')
parser.add_argument('--coverage-file')
parser.add_argument('--lifecycle-dir')
parser.add_argument('--allow-screened-training', action='store_true')
parser.add_argument('--model-policy', choices=['shadow', 'hybrid'], default='shadow')
parser.add_argument('--retrain-days', type=float, default=0, help='Opt-in periodic IF/AE refresh; 0 disables it')
parser.add_argument('--personalize', action=argparse.BooleanOptionalAction, default=True)
parser.add_argument('--lifecycle-learning', action=argparse.BooleanOptionalAction, default=True)
parser.add_argument('--run-id', default=None)
parser.add_argument('--entity-id', action='append', default=[])
parser.add_argument('--exclude-entity-id', action='append', default=[])
args = parser.parse_args()

input_path = resolve_path(args.input)
baseline_path = resolve_path(args.baseline)
load_baseline(baseline_path)
validate_selection(args.entity_id, args.exclude_entity_id)
run_id = args.run_id or uuid.uuid4().hex
autoencoder_model_dir = resolve_path(args.autoencoder_model_dir)

standard_path = BASE / "data/raw" / f"{args.prefix}_standard.csv"
clean_path = BASE / "data/raw" / f"{args.prefix}_clean.csv"
feature_path = BASE / "data/features" / f"{args.prefix}_features.csv"
result_path = BASE / "outputs" / f"{args.prefix}_result.csv"
episode_path = BASE / "outputs" / f"{args.prefix}_episode_summary.csv"
autoencoder_path = BASE / "outputs" / f"{args.prefix}_autoencoder_result.csv"
update_decision_path = BASE / "outputs" / f"{args.prefix}_baseline_update_decisions.csv"

standard_path.parent.mkdir(parents=True, exist_ok=True)
clean_path.parent.mkdir(parents=True, exist_ok=True)
feature_path.parent.mkdir(parents=True, exist_ok=True)
result_path.parent.mkdir(parents=True, exist_ok=True)
episode_path.parent.mkdir(parents=True, exist_ok=True)
autoencoder_path.parent.mkdir(parents=True, exist_ok=True)
update_decision_path.parent.mkdir(parents=True, exist_ok=True)

if is_standard_csv(input_path):
    print("standard CSV detected")
    shutil.copyfile(input_path, standard_path)
else:
    print("raw Home Assistant CSV detected")
    run([
        sys.executable,
        BASE / "src/entity_mapper.py",
        "--input", input_path,
        "--output", standard_path,
    ])

clean_standard_csv(standard_path, clean_path)
current = pd.read_csv(clean_path)
if args.entity_id or args.exclude_entity_id:
    if 'entity_id' not in current:
        raise ValueError('Exact entity selection requires entity_id in the input')
    mask = ~current['entity_id'].isin(args.exclude_entity_id)
    if args.entity_id:
        mask &= current['entity_id'].isin(args.entity_id)
    current = current.loc[mask].copy()
    current.to_csv(clean_path, index=False)
if args.data_source == "local" and "entity_id" in current:
    current = current.loc[~current["entity_id"].fillna("").str.contains("pauseable_virtual|virtual_", case=False, regex=True)].copy()
    current.to_csv(clean_path, index=False)
observation_start = None
if args.event_history:
    if not args.window_start or not args.window_end:
        parser.error("--event-history requires collection --window-start and --window-end")
    events, observation_start = update_history(current, resolve_path(args.event_history),
                                               args.window_start, args.window_end, args.data_source)
else:
    events = current
start = pd.Timestamp(parse_time(args.window_start)).ceil("min").to_pydatetime() if args.window_start else None
end = pd.Timestamp(parse_time(args.window_end)).floor("min").to_pydatetime() if args.window_end else None
features = build_features(current if current.empty else events, start, end)
if observation_start is not None:
    features["history_complete"] = (pd.to_datetime(features["window_end"]) >= observation_start + pd.Timedelta(hours=2)).astype(int)
features["source_type"] = args.data_source
features['household_id'] = args.household_id
features['schema_version'] = SCHEMA
features['history_complete'] = 0
if args.coverage_file:
    coverage = json.loads(resolve_path(args.coverage_file).read_text(encoding='utf-8'))
    raw = pd.read_csv(input_path)
    raw = raw.loc[~raw['entity_id'].isin(args.exclude_entity_id)]
    if args.entity_id:
        raw = raw.loc[raw['entity_id'].isin(args.entity_id)]
    if args.data_source == 'local':
        raw = raw.loc[~raw['entity_id'].fillna('').str.contains('pauseable_virtual|virtual_', case=False)]
    features['history_complete'] = usable_windows(features['window_end'], raw, coverage['intervals'], args.entity_id)
features.to_csv(feature_path, index=False)
quality_path = BASE / "outputs" / f"{args.prefix}_data_quality.json"
quality = {"status": "no_usable_data" if features.empty else "ok", "source_type": args.data_source,
           "run_id": run_id, "detection_completed": False,
           "current_usable_rows": len(current), "feature_rows": len(features),
           "history_complete_rows": int(features.get("history_complete", pd.Series(dtype=int)).sum()),
           "observed_since": str(observation_start or ""),
           "note": "No missing model input is replaced with zero; snapshot readings are state context only."}
if args.data_source == 'local' and not features.empty and not features['history_complete'].eq(1).all():
    quality['status'] = 'incomplete_observation'
if args.coverage_file:
    quality['observation'] = observation_report(raw, args.entity_id)
quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
print(f"saved: {feature_path}; rows: {len(features)}; quality: {quality['status']}")

if baseline_path.exists():
    run([
        sys.executable,
        BASE / "src/infer_ha_baseline.py",
        "--features", feature_path,
        "--baseline", baseline_path,
        "--output", result_path,
    ])

    rules = pd.read_csv(result_path)
    lifecycle = None
    if args.lifecycle_dir:
        if args.household_id == 'unconfigured':
            raise ValueError('Configure --household-id before accumulating training data')
        lifecycle = Lifecycle(resolve_path(args.lifecycle_dir), args.data_source, args.household_id,
                              args.allow_screened_training, args.model_policy, args.retrain_days)
        if args.lifecycle_learning:
            print(json.dumps({'behavior_feedback': lifecycle.feedback.drain_inbox()}))
            lifecycle.ingest(features, rules)
            print(json.dumps(lifecycle.maybe_train()))
        else:
            print(json.dumps({'status': 'frozen_demo_lifecycle_no_learning'}))
    decision_feedback_revision = lifecycle.feedback.revision() if lifecycle else 0
    comparison = lifecycle.score(features) if lifecycle else score_frame(features, resolve_path(args.model_dir))
    if not args.autoencoder:
        comparison["ae_level"] = "disabled"
        comparison["ae_reconstruction_error"] = float("nan")
    comparison_path = BASE / "outputs" / f"{args.prefix}_model_comparison.csv"
    comparison.to_csv(comparison_path, index=False)
    routine = lifecycle.routine_policy(features['window_end'].min()) if lifecycle and args.lifecycle_learning and args.personalize and not features.empty else None
    result = combine(rules, comparison, args.model_policy if lifecycle else 'shadow', features, routine)
    result['behavior_review_revision'] = decision_feedback_revision
    if lifecycle and lifecycle.feedback.revision() != decision_feedback_revision:
        result['level'], result['risk_score'] = 'unknown', 0
        result['reasons'] = 'Behavior reviews changed during inference; wait for the next consistent cycle'
    if args.data_source == 'local':
        incomplete = features.set_index('window_end')['history_complete'].ne(1)
        mask = result['window_end'].map(incomplete).fillna(True) & result['level'].eq('normal')
        result.loc[mask, 'level'] = 'unknown'
        result.loc[mask, 'reasons'] = 'Incomplete observation coverage; absence of events is not normality'
    result['history_complete'] = features['history_complete'].to_numpy()
    result["source_type"] = args.data_source
    result['run_id'] = run_id
    result.to_csv(result_path, index=False)
    print(f"model comparison: {comparison_path}")
    print(comparison["model_status"].value_counts().to_string())

    run([
        sys.executable,
        BASE / "src/summarize_ha_result.py",
        "--input", result_path,
        "--output", episode_path,
    ])

    result = pd.read_csv(result_path)
    print()
    print(result["level"].value_counts())
    print()
    print(f"result saved: {result_path}")
    print(f"episode summary saved: {episode_path}")

    if args.update_baseline:
        update_cmd = [
            sys.executable,
            BASE / "src/baseline_update.py",
            "--features", feature_path,
            "--baseline", baseline_path,
            "--history", resolve_path(args.baseline_history),
            "--quarantine", resolve_path(args.quarantine),
            "--abnormal-log", resolve_path(args.abnormal_log),
            "--output", baseline_path,
            "--decision-output", update_decision_path,
            "--max-history-days", str(args.max_history_days),
            "--max-review-days", str(args.max_review_days),
        ]
        if args.init_history_from_current_normal:
            update_cmd.append("--init-history-from-current-normal")
        run(update_cmd)
        print(f"baseline update decisions saved: {update_decision_path}")
    quality['detection_completed'] = True
    from ha_model_lifecycle import atomic_json
    atomic_json(quality_path, quality)
else:
    raise ValueError('Baseline disappeared during the cycle; detection did not complete')
