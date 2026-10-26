
import json
from pathlib import Path
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from ha_anomaly_models import dense_predict, numeric_features, sha256
from public_clinical_data import TIHM_FEATURES, CASAS_FEATURES, MIRATAR_FEATURES


FORMAT = 'public_clinical_research_v1'


def fit_score(train, calibration, test, features, output, *, basis, seed=42):
    allowed = set(TIHM_FEATURES + CASAS_FEATURES + MIRATAR_FEATURES)
    if not features or len(features) != len(set(features)) or not set(features).issubset(allowed):
        raise ValueError('Only explicitly named sensor features are permitted')
    identities = []
    for frame in [train, calibration, test]:
        if frame.empty or not frame.source_type.eq('public').all():
            raise ValueError('Research inputs must be nonempty and public')
        keys = ['subject_id', 'day'] if 'day' in frame else ['subject_id']
        if frame[keys].isna().any().any() or frame.duplicated(keys).any():
            raise ValueError('Missing or duplicate sample identity')
        identities.append(set(frame[keys].itertuples(index=False, name=None)))
    if any(identities[i] & identities[j] for i, j in [(0, 1), (0, 2), (1, 2)]):
        raise ValueError('Training/calibration/test identity overlap')
    if pd.concat([f.dataset for f in [train, calibration, test]]).nunique() != 1:
        raise ValueError('Do not mix research datasets')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new research model directory')
    raw = [numeric_features(f, features) for f in [train, calibration, test]]
    if any(np.any(x < 0) for x in raw):
        raise ValueError('Count/duration features must be nonnegative')
    variable = np.ptp(raw[0], axis=0) > 1e-10
    if not variable.any():
        raise ValueError('Constant reference features')
    selected = [c for c, keep in zip(features, variable) if keep]
    scale = StandardScaler().fit(np.log1p(raw[0][:, variable]))
    x, cal, held = [scale.transform(np.log1p(values[:, variable])) for values in raw]
    forest = IsolationForest(n_estimators=128, max_samples=min(256, len(x)),
                             random_state=seed, n_jobs=1).fit(x)
    ae = MLPRegressor(hidden_layer_sizes=(8, 3, 8), activation='relu', solver='adam', alpha=.001,
                      batch_size=min(64, len(x)), max_iter=400, early_stopping=False, random_state=seed)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        ae.fit(x, x)
    layers = [{'weight': w.T.tolist(), 'bias': b.tolist()} for w, b in zip(ae.coefs_, ae.intercepts_)]
    cal_scores = {'if': -forest.score_samples(cal),
                  'ae': np.mean((cal - dense_predict(cal, layers)) ** 2, axis=1)}
    scores = {'if': -forest.score_samples(held),
              'ae': np.mean((held - dense_predict(held, layers)) ** 2, axis=1)}
    thresholds = {name: float(np.quantile(values, .95)) for name, values in cal_scores.items()}
    metadata_columns = [c for c in ['dataset', 'source_type', 'subject_id', 'day', 'diagnosis',
                                  'label_status', 'label_types', 'coverage_verified'] if c in test]
    result = test[metadata_columns].reset_index(drop=True).copy()
    for name, values in scores.items():
        result[name + '_score'] = values
        result[name + '_alert'] = values > thresholds[name]
    result['either_alert'] = result.if_alert | result.ae_alert
    result['both_alert'] = result.if_alert & result.ae_alert
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(forest, output / 'if.joblib')
    manifest = {'format': FORMAT, 'source_type': 'public', 'production_eligible': False,
                'schema_version': 'public_clinical_sensor_v1', 'training_basis': basis,
                'feature_columns': selected, 'dropped_constant_columns': [c for c in features if c not in selected],
                'transform': 'log1p_then_train_only_standard_scaler', 'scaler_mean': scale.mean_.tolist(),
                'scaler_scale': scale.scale_.tolist(), 'autoencoder_layers': layers,
                'thresholds_95_calibration_only': thresholds, 'seed': seed,
                'sklearn_version': sklearn.__version__, 'if_sha256': sha256(output / 'if.joblib'),
                'warnings': [str(w.message) for w in caught], 'splits': {}}
    for name, frame in [('train', train), ('calibration', calibration), ('test', test)]:
        manifest['splits'][name] = {'rows': len(frame), 'subject_ids': sorted(frame.subject_id.unique().tolist())}
        if 'day' in frame:
            manifest['splits'][name].update(start=str(frame.day.min()), end=str(frame.day.max()))
        frame.to_csv(output / (name + '.csv'), index=False)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
    result.to_csv(output / 'scores.csv', index=False)
    return result, manifest


def event_overlap(scores, labels):
    pass
    if scores.duplicated(['subject_id', 'day']).any():
        raise ValueError('Duplicate score day')
    events = labels.drop_duplicates(['patient_id', 'day', 'type'])
    merged = events.merge(scores, left_on=['patient_id', 'day'], right_on=['subject_id', 'day'],
                          how='left', validate='many_to_one', indicator=True)
    report = {}
    for name, group in merged.groupby('type'):
        observed = group.loc[group['_merge'].eq('both')]
        report[name] = {'all_recorded_subject_event_days': len(group), 'scored_holdout_event_days': len(observed),
                       'unscored_event_days': len(group) - len(observed)}
        for model in ['if', 'ae', 'either', 'both']:
            report[name][model + '_overlap_fraction'] = float(observed[model + '_alert'].mean()) if len(observed) else None
    return {'by_event_type': report, 'precision': None, 'specificity': None, 'roc_auc': None,
            'reason': 'No explicit negative event labels. Same-day overlap is retrospective, not prediction.'}
