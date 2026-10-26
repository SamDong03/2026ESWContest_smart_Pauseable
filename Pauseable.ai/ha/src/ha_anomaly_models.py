

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


FORMAT = 'ha_anomaly_bundle_v1'
SCORE_COLUMNS = ['window_end', 'model_status', 'model_id', 'model_source',
                 'if_anomaly_score', 'if_level', 'ae_reconstruction_error',
                 'ae_level', 'model_reason']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric_features(frame, columns):
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError('Missing model features: ' + ', '.join(missing))
    values = frame[columns].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError('Model input contains missing or non-finite values')
    return values


def levels(scores, thresholds):
    return np.where(scores > thresholds['risk'], 'risk',
                    np.where(scores > thresholds['attention'], 'attention', 'normal'))


def dense_predict(values, layers):
    for index, layer in enumerate(layers):
        values = values @ np.asarray(layer['weight']).T + np.asarray(layer['bias'])
        if index < len(layers) - 1:
            values = np.maximum(values, 0)
    return values


def validate_model_numbers(manifest):
    columns = manifest['feature_columns']
    if not columns or len(set(columns)) != len(columns):
        raise ValueError('Model feature columns must be unique and nonempty')
    size = len(columns)
    for name in ('mean', 'scale'):
        values = np.asarray(manifest['scaler'][name], dtype=float)
        if values.shape != (size,) or not np.isfinite(values).all():
            raise ValueError('Invalid scaler shape or values')
        if name == 'scale' and (values <= 0).any():
            raise ValueError('Scaler scale must be positive')
    for name in ('ae', 'if'):
        thresholds = manifest['thresholds'][name]
        attention, risk = float(thresholds['attention']), float(thresholds['risk'])
        if not np.isfinite([attention, risk]).all() or attention < 0 or risk < attention:
            raise ValueError('Invalid anomaly thresholds')
    layers = manifest['ae_layers']
    if not layers:
        raise ValueError('No autoencoder layers')
    for layer in layers:
        weight, bias = np.asarray(layer['weight'], dtype=float), np.asarray(layer['bias'], dtype=float)
        if weight.ndim != 2 or weight.shape[1] != size or bias.shape != (weight.shape[0],):
            raise ValueError('Autoencoder layer shape mismatch')
        if not np.isfinite(weight).all() or not np.isfinite(bias).all():
            raise ValueError('Nonfinite autoencoder weights')
        size = weight.shape[0]
    if size != len(columns):
        raise ValueError('Autoencoder output does not reconstruct the inputs')


def unavailable(frame, status, reason, manifest=None):
    manifest = manifest or {}
    result = pd.DataFrame({'window_end': frame['window_end']})
    result['model_status'] = status
    result['model_id'] = manifest.get('model_id', '')
    result['model_source'] = manifest.get('source_type', '')
    result['if_anomaly_score'] = np.nan
    result['if_level'] = 'unavailable'
    result['ae_reconstruction_error'] = np.nan
    result['ae_level'] = 'unavailable'
    result['model_reason'] = reason
    return result[SCORE_COLUMNS]


def score_frame(frame, model_dir):
    try:
        return _score_frame(frame, model_dir)
    except Exception as error:
        return unavailable(frame, 'invalid_model', f'Model could not be scored: {type(error).__name__}')


def _score_frame(frame, model_dir):
    model_dir = Path(model_dir)
    manifest_path = model_dir / 'manifest.json'
    if not manifest_path.exists():
        return unavailable(frame, 'not_trained', 'No compatible model bundle; collect and review normal history first')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != FORMAT:
        return unavailable(frame, 'incompatible_model', 'Unsupported model format', manifest)
    validate_model_numbers(manifest)
    for column in ('source_type', 'household_id'):
        if column not in frame or not manifest.get(column) or not frame[column].eq(manifest[column]).all():
            return unavailable(frame, 'incompatible_source', f'Missing or mismatched {column}', manifest)
    if 'history_complete' not in frame:
        return unavailable(frame, 'insufficient_history', 'Coverage metadata is required', manifest)
    if manifest.get('schema_version') is not None:
        if 'schema_version' not in frame or not frame['schema_version'].eq(manifest['schema_version']).all():
            return unavailable(frame, 'incompatible_schema', 'Missing or mismatched schema_version', manifest)
    try:
        values = numeric_features(frame, manifest['feature_columns'])
    except ValueError as error:
        return unavailable(frame, 'invalid_features', str(error), manifest)
    if frame.empty:
        return unavailable(frame, 'no_data', 'No feature rows', manifest)
    try:
        import joblib
        import sklearn
    except ImportError:
        return unavailable(frame, 'dependency_missing', 'Install the pinned model dependencies', manifest)
    if sklearn.__version__ != manifest['sklearn_version']:
        return unavailable(frame, 'incompatible_runtime', 'scikit-learn version differs from training', manifest)
    model_path = model_dir / 'isolation_forest.joblib'
    if not model_path.exists() or sha256(model_path) != manifest['forest_sha256']:
        return unavailable(frame, 'invalid_model', 'Model file missing or checksum mismatch', manifest)

    forest = joblib.load(model_path)
    if_scores = -forest.score_samples(values)
    scaler = manifest['scaler']
    scaled = (values - np.asarray(scaler['mean'])) / np.asarray(scaler['scale'])
    reconstructed = dense_predict(scaled, manifest['ae_layers'])
    errors = np.mean((reconstructed - scaled) ** 2, axis=1)
    if not np.isfinite(errors).all() or not np.isfinite(if_scores).all():
        return unavailable(frame, 'invalid_model', 'Non-finite model output', manifest)
    result = unavailable(frame, 'shadow', 'Comparison only; model scores do not change rule alerts', manifest)
    result['if_anomaly_score'] = if_scores
    result['if_level'] = levels(if_scores, manifest['thresholds']['if'])
    result['ae_reconstruction_error'] = errors
    result['ae_level'] = levels(errors, manifest['thresholds']['ae'])
    if 'history_complete' in frame:
        incomplete = pd.to_numeric(frame['history_complete'], errors='coerce').ne(1)
        result.loc[incomplete, ['if_anomaly_score', 'ae_reconstruction_error']] = np.nan
        result.loc[incomplete, ['if_level', 'ae_level']] = 'unavailable'
        result.loc[incomplete, 'model_status'] = 'insufficient_history'
        result.loc[incomplete, 'model_reason'] = 'Rolling history does not cover the complete feature lookback'
    return result
