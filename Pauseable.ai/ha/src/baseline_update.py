import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    from build_baseline import build_baseline
    from infer_ha_baseline import infer_dataframe
except ImportError:
    from src.build_baseline import build_baseline
    from src.infer_ha_baseline import infer_dataframe


BASE = Path(__file__).resolve().parents[1]
WINDOW_COLUMN = "window_end"
NON_FEATURE_COLUMNS = {
    "source_type", "household_id", "history_complete", "review_status", "label", "schema_version",
    "risk_score",
    "level",
    "primary_pattern",
    "reasons",
    "baseline_update_action",
}
DECISION_COLUMNS = [
    WINDOW_COLUMN,
    "risk_score",
    "level",
    "primary_pattern",
    "baseline_update_action",
    "reasons",
]


def resolve_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE / path


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_features(path):
    df = pd.read_csv(path)
    if WINDOW_COLUMN not in df.columns:
        raise ValueError(f"{path} must contain a '{WINDOW_COLUMN}' column")
    return df


def feature_columns(df):
    return [
        col
        for col in df.columns
        if col != WINDOW_COLUMN and col not in NON_FEATURE_COLUMNS
    ]


def align_feature_frames(frames):
    columns = [WINDOW_COLUMN]
    for df in frames:
        for col in feature_columns(df):
            if col not in columns:
                columns.append(col)

    columns += [c for c in ("source_type", "household_id", "history_complete", "review_status", "schema_version")
                if any(c in frame for frame in frames)]
    aligned = []
    for df in frames:
        copy = df.copy()
        for col in columns:
            if col not in copy.columns:
                raise ValueError('History schema mismatch: ' + col)
        aligned.append(copy[columns])

    return aligned, columns


def normalize_history(history, max_history_days):
    history = history.copy()
    history["_time"] = pd.to_datetime(history[WINDOW_COLUMN], errors="coerce")
    history = history.dropna(subset=["_time"]).sort_values("_time")
    history = history.drop_duplicates(subset=[WINDOW_COLUMN], keep="last")

    if max_history_days > 0 and not history.empty:
        cutoff = history["_time"].max() - pd.Timedelta(days=max_history_days)
        history = history[history["_time"] >= cutoff]

    return history.drop(columns=["_time"])


def normalize_event_log(df, max_days=0):
    df = df.copy()
    if WINDOW_COLUMN not in df.columns:
        return df

    df["_time"] = pd.to_datetime(df[WINDOW_COLUMN], errors="coerce")
    df = df.dropna(subset=["_time"]).sort_values("_time")
    dedupe_columns = [
        col
        for col in [WINDOW_COLUMN, "level", "primary_pattern"]
        if col in df.columns
    ]
    if dedupe_columns:
        df = df.drop_duplicates(subset=dedupe_columns, keep="last")

    if max_days > 0 and not df.empty:
        cutoff = df["_time"].max() - pd.Timedelta(days=max_days)
        df = df[df["_time"] >= cutoff]

    return df.drop(columns=["_time"])


def backup_existing(path, backup_dir):
    if not path.exists():
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.stem}_{timestamp}{path.suffix}"
    shutil.copyfile(path, backup_path)
    return backup_path


def action_for_level(level):
    if level == "normal":
        return "accepted_for_baseline"
    if level == "attention":
        return "quarantined_for_review"
    if level == "risk":
        return "excluded_from_baseline"
    return "excluded_unknown"


def build_decision_frame(features, decisions):
    decision_df = pd.DataFrame(decisions)
    decision_df["baseline_update_action"] = decision_df["level"].map(action_for_level)

    return decision_df[DECISION_COLUMNS]


def attach_features(features, decision_df, mask):
    features = features.reset_index(drop=True)
    decision_df = decision_df.reset_index(drop=True)
    mask = pd.Series(mask).reset_index(drop=True)

    selected_decisions = decision_df.loc[mask, DECISION_COLUMNS].reset_index(drop=True)
    selected_features = features.loc[mask, feature_columns(features)].reset_index(drop=True)
    return pd.concat([selected_decisions, selected_features], axis=1)


def append_event_log(path, new_rows, max_days):
    if path.exists():
        existing = pd.read_csv(path)
        columns = list(existing.columns)
        for col in new_rows.columns:
            if col not in columns:
                columns.append(col)
        for col in columns:
            if col not in existing.columns:
                existing[col] = ""
            if col not in new_rows.columns:
                new_rows[col] = ""
        combined = pd.concat([existing[columns], new_rows[columns]], ignore_index=True)
    else:
        combined = new_rows.copy()

    combined = normalize_event_log(combined, max_days=max_days)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return combined


def update_baseline(
    features,
    baseline,
    history_path,
    seed_features_path,
    init_history_from_current_normal,
    max_history_days,
):
    def check_provenance(frame, household=None):
        required = {'source_type', 'household_id', 'history_complete', 'review_status'}
        if not required.issubset(frame.columns):
            raise ValueError('Baseline updates require local reviewed provenance and coverage')
        if not frame.empty and (not frame['source_type'].eq('local').all()
                or not frame['history_complete'].eq(1).all()
                or not frame['review_status'].eq('reviewed_normal').all()
                or frame['household_id'].isna().any() or frame['household_id'].nunique() != 1
                or (household and not frame['household_id'].eq(household).all())):
            raise ValueError('Baseline updates require matching local reviewed_normal data')
    check_provenance(features)
    decisions = infer_dataframe(features, baseline)
    decision_df = build_decision_frame(features, decisions)
    normal_mask = decision_df["level"] == "normal"
    attention_mask = decision_df["level"] == "attention"
    risk_mask = decision_df["level"] == "risk"
    accepted = features.loc[normal_mask.values].copy()
    quarantined = attach_features(features, decision_df, attention_mask)
    excluded = attach_features(features, decision_df, risk_mask)

    if history_path.exists():
        history = load_features(history_path)
        history_source = str(history_path)
    elif seed_features_path is not None:
        history = load_features(seed_features_path)
        history_source = str(seed_features_path)
    elif init_history_from_current_normal:
        history = features.iloc[0:0].copy()
        history_source = "current normal windows only"
    else:
        raise FileNotFoundError(
            f"baseline history not found: {history_path}. "
            "Pass --seed-features with known-normal features, or use "
            "--init-history-from-current-normal for first bootstrapping."
        )

    check_provenance(history, str(features['household_id'].iloc[0]) if len(features) else None)
    (history, accepted), columns = align_feature_frames([history, accepted])
    updated_history = normalize_history(
        pd.concat([history, accepted], ignore_index=True),
        max_history_days=max_history_days,
    )
    updated_baseline = build_baseline(updated_history[[WINDOW_COLUMN] + feature_columns(updated_history)])
    updated_baseline["update"] = {
        "source_history": history_source,
        "new_windows": int(len(features)),
        "accepted_normal_windows": int(len(accepted)),
        "quarantined_attention_windows": int(len(quarantined)),
        "excluded_risk_windows": int(len(excluded)),
        "history_windows_after_update": int(len(updated_history)),
        "max_history_days": int(max_history_days),
        "normal_only_update": True,
        "attention_policy": "quarantine_for_review",
        "risk_policy": "exclude_from_baseline",
    }

    return decision_df, updated_history[columns], quarantined, excluded, updated_baseline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--history", default="data/features/user_001_baseline_history_v2.csv")
    parser.add_argument("--quarantine", default="data/features/user_001_quarantine_v2.csv")
    parser.add_argument("--abnormal-log", default="outputs/user_001_abnormal_log_v2.csv")
    parser.add_argument("--output", required=True)
    parser.add_argument("--decision-output")
    parser.add_argument("--seed-features")
    parser.add_argument("--max-history-days", type=int, default=30)
    parser.add_argument("--max-review-days", type=int, default=90)
    parser.add_argument("--min-history-windows", type=int, default=60)
    parser.add_argument("--init-history-from-current-normal", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    features_path = resolve_path(args.features)
    baseline_path = resolve_path(args.baseline)
    history_path = resolve_path(args.history)
    quarantine_path = resolve_path(args.quarantine)
    abnormal_log_path = resolve_path(args.abnormal_log)
    output_path = resolve_path(args.output)
    seed_features_path = resolve_path(args.seed_features) if args.seed_features else None
    decision_output_path = (
        resolve_path(args.decision_output) if args.decision_output else None
    )

    features = load_features(features_path)
    baseline = load_json(baseline_path)

    (
        decision_df,
        updated_history,
        quarantined,
        excluded,
        updated_baseline,
    ) = update_baseline(
        features=features,
        baseline=baseline,
        history_path=history_path,
        seed_features_path=seed_features_path,
        init_history_from_current_normal=args.init_history_from_current_normal,
        max_history_days=args.max_history_days,
    )

    updated_baseline["update"]["quarantine_path"] = str(quarantine_path)
    updated_baseline["update"]["abnormal_log_path"] = str(abnormal_log_path)

    if decision_output_path is not None:
        decision_output_path.parent.mkdir(parents=True, exist_ok=True)
        decision_df.to_csv(decision_output_path, index=False)

    level_counts = decision_df["level"].value_counts()
    accepted_count = int((decision_df["level"] == "normal").sum())
    quarantined_count = int((decision_df["level"] == "attention").sum())
    excluded_count = int((decision_df["level"] == "risk").sum())

    if args.dry_run:
        print("dry run: no baseline, history, quarantine, or risk log files were written")
    else:
        backup_dir = BASE / "models" / "baseline_backups"
        baseline_backup = backup_existing(output_path, backup_dir)
        history_backup = backup_existing(history_path, backup_dir)

        history_path.parent.mkdir(parents=True, exist_ok=True)
        updated_history.to_csv(history_path, index=False)
        quarantine_log = append_event_log(
            quarantine_path,
            quarantined,
            max_days=args.max_review_days,
        )
        abnormal_log = append_event_log(
            abnormal_log_path,
            excluded,
            max_days=args.max_review_days,
        )
        save_json(output_path, updated_baseline)

        if baseline_backup is not None:
            print(f"baseline backup: {baseline_backup}")
        if history_backup is not None:
            print(f"history backup: {history_backup}")
        print(f"updated history saved: {history_path}")
        print(f"quarantine saved: {quarantine_path} ({len(quarantine_log)} rows)")
        print(f"risk log saved: {abnormal_log_path} ({len(abnormal_log)} rows)")
        print(f"updated baseline saved: {output_path}")

    print(level_counts.to_string())
    print(f"accepted normal windows: {accepted_count}")
    print(f"quarantined attention windows: {quarantined_count}")
    print(f"excluded risk windows: {excluded_count}")
    print(f"history windows after update: {len(updated_history)}")
    print(f"baseline version: {updated_baseline['version']}")

    if len(updated_history) < args.min_history_windows:
        print(
            "warning: baseline history is still small; keep collecting "
            "normal windows before relying on stable personalization"
        )

    if decision_output_path is not None:
        print(f"decision log saved: {decision_output_path}")


if __name__ == "__main__":
    main()
