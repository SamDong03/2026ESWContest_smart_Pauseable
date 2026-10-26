

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from ha_anomaly_models import FORMAT, dense_predict, levels, numeric_features, sha256


META_COLUMNS = {'window_end', 'source_type', 'household_id', 'label', 'review_status',
                'history_complete', 'schema_version'}


def chronological_split(frame, gap_minutes=120):
    if gap_minutes < 0:
        raise ValueError('gap_minutes must not be negative')
    times = pd.to_datetime(frame['window_end'], errors='raise', utc=True)
    if times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError('Timestamps must be unique and sorted within one household')
    if len(frame) < 150:
        raise ValueError('Need at least 150 rows before splitting')
    first, second = int(len(frame) * 0.6), int(len(frame) * 0.8)
    gap = pd.Timedelta(minutes=gap_minutes)
    train = frame.loc[times < times.iloc[first] - gap].copy()
    calibration = frame.loc[(times >= times.iloc[first]) & (times < times.iloc[second] - gap)].copy()
    test = frame.loc[times >= times.iloc[second]].copy()
    if min(len(train), len(calibration), len(test)) < 30:
        raise ValueError('Too few rows after the time gaps; collect a longer history')
    return train, calibration, test


def tail_thresholds(values):
    return {'attention': float(np.quantile(values, .95)), 'risk': float(np.quantile(values, .99))}


def train_models(input_path, output_dir, source_type, household_id, normal_basis,
                 gap_minutes=120, min_days=7, seed=42, feature_columns=None, allow_screened_normal=False):
    if not normal_basis.strip() or not household_id.strip():
        raise ValueError('Document the household and normal selection basis')
    if source_type == 'local' and (min_days < 7 or gap_minutes < 120):
        raise ValueError('Local training requires 7 observed days and a 120-minute purge at minimum')
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Use a new model directory; model versions must not be overwritten')
    frame = pd.read_csv(input_path)
    if frame.empty:
        raise ValueError('No training data')
    for column, expected in [('source_type', source_type), ('household_id', household_id)]:
        if column in frame and (frame[column].isna().any() or set(frame[column].astype(str)) != {expected}):
            raise ValueError('Mixed or mismatched ' + column)
    if 'label' in frame and not frame['label'].astype(str).str.lower().isin(['normal', '0']).all():
        raise ValueError('Training input must contain only normal-labelled rows')
    if source_type == 'local':
        required = {'source_type', 'household_id', 'history_complete', 'review_status'}
        allowed = ['reviewed_normal', 'baseline_screened'] if allow_screened_normal else ['reviewed_normal']
        if not required.issubset(frame.columns) or not frame['review_status'].isin(allowed).all():
            raise ValueError('Local training requires provenance, coverage and reviewed_normal periods')
    if 'history_complete' in frame:
        frame = frame.loc[pd.to_numeric(frame['history_complete'], errors='coerce').eq(1)].copy()
    times = pd.to_datetime(frame['window_end'], errors='raise', utc=True)
    observed_days = times.dt.date.nunique()
    if observed_days < min_days:
        raise ValueError(f'Need {min_days} observed days, found {observed_days}; no model activated')
    frame = frame.assign(_order=times).sort_values('_order').drop(columns='_order').reset_index(drop=True)
    columns = feature_columns or [c for c in frame if c not in META_COLUMNS]
    if not columns or set(columns) & META_COLUMNS:
        raise ValueError('Select numeric features only; metadata/labels cannot be predictors')
    numeric_features(frame, columns)
    train, calibration, test = chronological_split(frame, gap_minutes)
    x_train, x_cal, x_test = [numeric_features(part, columns) for part in (train, calibration, test)]
    if np.all(np.ptp(x_train, axis=0) == 0):
        raise ValueError('Training rows are constant; observations contain no learnable variation')
    behavior = [i for i, name in enumerate(columns) if name not in {'hour', 'is_night', 'hour_sin', 'hour_cos', 'weekday_sin', 'weekday_cos'}]
    if not behavior or np.all(np.ptp(x_train[:, behavior], axis=0) == 0):
        raise ValueError('Only clock features vary; collect actual appliance behavior before training')
    forest = IsolationForest(n_estimators=128, max_samples=256, contamination='auto',
                             random_state=seed, n_jobs=1).fit(x_train)
    scaler = StandardScaler().fit(x_train)
    scaled_train, scaled_cal, scaled_test = [scaler.transform(x) for x in (x_train, x_cal, x_test)]
    ae = MLPRegressor(hidden_layer_sizes=(16, 6, 16), activation='relu', solver='adam',
                      alpha=0.001, max_iter=1000, random_state=seed, early_stopping=False,
                      batch_size=min(256, len(train)), shuffle=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', ConvergenceWarning)
        ae.fit(scaled_train, scaled_train)
    layers = [{'weight': weight.T.tolist(), 'bias': bias.tolist()}
              for weight, bias in zip(ae.coefs_, ae.intercepts_)]
    if_cal, if_test = [-forest.score_samples(x) for x in (x_cal, x_test)]
    ae_cal, ae_test = [np.mean((dense_predict(x, layers) - x) ** 2, axis=1) for x in (scaled_cal, scaled_test)]
    thresholds = {'if': tail_thresholds(if_cal), 'ae': tail_thresholds(ae_cal)}
    export_error = float(np.max(np.abs(ae.predict(scaled_test) - dense_predict(scaled_test, layers))))
    if not np.isfinite(export_error) or export_error > 1e-8:
        raise ValueError('Dense AE export does not match the training model')
    model_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / 'isolation_forest.joblib'
    joblib.dump(forest, model_path)
    manifest = {
        'format': FORMAT, 'model_id': model_id, 'source_type': source_type,
        'household_id': household_id, 'normal_basis': normal_basis,
        'deployment_policy': 'shadow', 'input_sha256': sha256(input_path),
        'feature_columns': columns, 'sklearn_version': sklearn.__version__, 'seed': seed,
        'forest_sha256': sha256(model_path), 'thresholds': thresholds,
        'scaler': {'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist()},
        'ae_layers': layers, 'observed_days': int(observed_days), 'gap_minutes': gap_minutes,
        'splits': {name: {'rows': len(part), 'start': str(part['window_end'].iloc[0]), 'end': str(part['window_end'].iloc[-1])}
                   for name, part in [('train', train), ('calibration', calibration), ('test', test)]},
        'training_warnings': [str(item.message) for item in caught],
        'optimizer_converged': not any(issubclass(item.category, ConvergenceWarning) for item in caught),
        'optimizer': {'max_iter': ae.max_iter, 'iterations': int(ae.n_iter_), 'loss': float(ae.loss_)},
        'constant_features': [name for name, spread in zip(columns, np.ptp(x_train, axis=0)) if spread == 0],
    }
    if 'schema_version' in frame:
        if frame['schema_version'].isna().any() or frame['schema_version'].nunique() != 1:
            raise ValueError('Mixed or missing feature schema')
        manifest['schema_version'] = str(frame['schema_version'].iloc[0])
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    holdout = test[['window_end']].copy()
    holdout['if_anomaly_score'] = if_test
    holdout['if_level'] = levels(if_test, thresholds['if'])
    holdout['ae_reconstruction_error'] = ae_test
    holdout['ae_level'] = levels(ae_test, thresholds['ae'])
    holdout.to_csv(destination / 'holdout_scores.csv', index=False)
    if_alarm, ae_alarm = holdout['if_level'].ne('normal'), holdout['ae_level'].ne('normal')
    comparison = {
        'model_id': model_id, 'source_type': source_type, 'normal_basis': normal_basis,
        'rows': len(test), 'ae_export_max_abs_error': export_error,
        'normal_holdout_alert_fraction': {'if': float(if_alarm.mean()), 'ae': float(ae_alarm.mean()),
                                        'or': float((if_alarm | ae_alarm).mean()),
                                        'and': float((if_alarm & ae_alarm).mean())},
        'recall': None, 'precision': None,
        'limitations': ['Normal-only holdout does not measure anomaly recall or clinical performance.',
                        'Alert fraction is an assumed-normal false-alarm estimate, conditional on normal_basis.',
                        'Model selection or tuning on this holdout requires a new untouched evaluation period.',
                        'Public/synthetic models must not be presented as personalized home models.'],
    }
    (destination / 'validation.json').write_text(json.dumps(comparison, indent=2), encoding='utf-8')
    print(json.dumps(comparison, indent=2))
    return manifest, comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--source-type', choices=['synthetic', 'public', 'local'], required=True)
    parser.add_argument('--household-id', required=True)
    parser.add_argument('--normal-basis', required=True, help='How normal segments were selected/reviewed')
    parser.add_argument('--gap-minutes', type=int, default=120)
    parser.add_argument('--min-days', type=int, default=7)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if args.min_days < 7 and args.source_type == 'local':
        parser.error('Local training requires at least 7 observed days; this is a minimum, not validation proof')
    train_models(args.input, args.output_dir, args.source_type, args.household_id,
                 args.normal_basis, args.gap_minutes, args.min_days, args.seed)


if __name__ == '__main__':
    main()
