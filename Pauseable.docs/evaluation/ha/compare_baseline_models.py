
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Pauseable.ai/ha/src'))
from ha_model_lifecycle import combine
from infer_ha_baseline import infer_dataframe, MIN_MEANINGFUL_COUNTS
from verify_ha_month_cycle import scenario, features_from_raw

METHODS = ('baseline', 'baseline_if', 'baseline_ae', 'hybrid')
RANK = {'normal': 0, 'attention': 1, 'risk': 2, 'unavailable': -1}
MODEL_COLUMNS = ['window_end', 'model_status', 'model_source', 'if_level', 'ae_level',
                 'if_anomaly_score', 'ae_reconstruction_error']


def require(condition, message):
    pass
    if not condition:
        raise ValueError(message)


def validate_alignment(**frames):
    pass
    expected = None
    for name, frame in frames.items():
        require('window_end' in frame, f'{name}: missing window_end')
        require(not frame.empty, f'{name}: empty timeline')
        keys = frame['window_end'].reset_index(drop=True)
        try:
            times = pd.to_datetime(keys, format='ISO8601', utc=True, errors='raise')
        except (ValueError, TypeError) as error:
            raise ValueError(f'{name}: invalid window_end timestamp') from error
        require(not times.isna().any(), f'{name}: missing window_end timestamp')
        require(not times.duplicated().any(), f'{name}: duplicate window_end timestamp')
        require(times.is_monotonic_increasing, f'{name}: timestamps must be increasing')

        if expected is not None:
            require(keys.equals(expected), f'{name}: window_end keys/order differ from reference')
        expected = keys


def require_reproduction(actual, saved, column, context):
    validate_alignment(replayed=actual, frozen=saved)
    require(column in saved, f'{context}: missing frozen {column}')
    require(actual['level'].isin(RANK).all(), f'{context}: unknown replayed level')
    require(saved[column].isin(RANK).all(), f'{context}: unknown frozen level')
    require(actual['level'].tolist() == saved[column].tolist(),
            f'{context}: replayed levels differ from frozen {column}')


def elapsed_minutes(frame):
    validate_alignment(timeline=frame)
    times = pd.to_datetime(frame['window_end'], format='ISO8601', utc=True)
    return ((times - times.iloc[0]).dt.total_seconds() / 60).tolist()


def variants(rules, models, features):
    pass
    validate_alignment(rules=rules, models=models, features=features)
    require(rules['level'].isin(RANK).all(), 'rules: unknown level')
    for column in ('if_level', 'ae_level'):
        require(models[column].isin(RANK).all(), f'models: unknown {column}')
    outputs = {}
    for method in METHODS:
        active = models.copy()
        if method == 'baseline_if':
            active.loc[:, 'ae_level'] = 'normal'
        elif method == 'baseline_ae':
            active.loc[:, 'if_level'] = 'normal'
        outputs[method] = combine(rules, active, 'shadow' if method == 'baseline' else 'hybrid', features)
    return outputs


def summary(frame, origin=None):
    require(not frame.empty, 'Cannot summarize an empty comparison')
    require(frame['level'].isin(RANK).all(), 'Cannot summarize an unknown level')
    found = frame.loc[frame['level'].isin(['attention', 'risk'])]
    first = None if found.empty else pd.Timestamp(found.iloc[0]['window_end'])
    return {
        'levels': dict(Counter(frame['level'])),
        'alert_windows': len(found),
        'max_level': max(frame['level'], key=lambda level: RANK[level]),
        'first_alert_elapsed_minutes': None if first is None or origin is None else (first - origin).total_seconds() / 60,
    }


def obj(path):
    return json.loads(path.read_text(encoding='utf-8'))


def run(source, output):
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new empty output directory')
    output.mkdir(parents=True, exist_ok=True)
    hashes = {}

    def record(path):
        hashes[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()

    baseline_path = source / 'month/synthetic_baseline.json'
    baseline = obj(baseline_path)
    record(baseline_path)
    raw, origin = scenario(14, offset=-14)
    _, reference = features_from_raw(raw, origin, 14)
    feature = 'fridge_door_open_count_1h'
    require(len(reference) == baseline['window_count'] == 336, 'Baseline reference sample count differs')
    require(np.isclose(reference[feature].quantile(.95), baseline['features'][feature]['p95']),
            'Baseline reference p95 differs')
    counts = reference[feature].value_counts().sort_index()
    normal_path = source / 'month/month_features.csv'
    normal_features = pd.read_csv(normal_path)
    record(normal_path)
    validate_alignment(normal_features=normal_features)
    require(normal_features['history_complete'].isin([0, 1]).all(), 'Normal controls: invalid history mask')
    normal_features = normal_features.loc[normal_features['history_complete'].eq(1)]
    normal_rules = pd.DataFrame(infer_dataframe(normal_features, baseline))
    baseline_info = {
        'reference_days': 14, 'reference_samples': len(reference),
        'future_control_days': 30, 'future_complete_samples': len(normal_rules),
        'future_control_levels': dict(Counter(normal_rules['level'])),
        'feature': feature, 'reference_distribution': {str(int(k)): int(v) for k, v in counts.items()},
        'stats': baseline['features'][feature],
        'minimum_count_for_this_feature_score': MIN_MEANINGFUL_COUNTS[feature],
        'scope': 'The frequency floor is only one feature score gate, not a standalone final alert cutoff.',
        'clinical_validation': False,
        'sampling_limit': 'Hourly synthetic endpoints can miss short-window variation; this is not minute-resolution real-household calibration.',
    }
    fridge = {}
    for name in ('single_use', 'five_minute_rechecks'):
        folder = source / 'fridge'
        features_path, scores_path = folder / f'{name}_features.csv', folder / f'{name}_scores.csv'
        features, scores = pd.read_csv(features_path), pd.read_csv(scores_path)
        record(features_path)
        record(scores_path)
        require(features['history_complete'].isin([0, 1]).all(), f'fridge/{name}: invalid history mask')
        rules = pd.DataFrame(infer_dataframe(features, baseline))
        require_reproduction(rules, scores, 'rule_level', f'fridge/{name}/baseline')
        outputs = variants(rules, scores[MODEL_COLUMNS], features)
        require_reproduction(outputs['hybrid'], scores, 'level', f'fridge/{name}/hybrid')
        valid = features['history_complete'].eq(1)
        require(valid.any(), f'fridge/{name}: no complete observation windows')
        start = pd.Timestamp(features.loc[valid, 'window_end'].iloc[0])
        entry = {'samples': int(valid.sum()), 'methods': {},
                 'elapsed_minutes': elapsed_minutes(features.loc[valid])}
        for method, frame in outputs.items():
            current = frame.loc[valid].copy()
            entry['methods'][method] = summary(current, start)
            entry['methods'][method]['timeline'] = [RANK[level] for level in current['level']]
        fridge[name] = entry
    result_rows = []
    research = source / 'evidence'
    research_baseline = obj(research / 'synthetic_baseline.json')
    record(research / 'synthetic_baseline.json')
    original = pd.read_csv(research / 'scenario_results.csv')
    record(research / 'scenario_results.csv')
    for case in original.to_dict('records'):
        folder = research / 'cases' / f"{case['case']}_{case['intensity']}_{case['seed']}"
        features_path, scores_path = folder / 'features.csv', folder / 'scores.csv'
        features, scores = pd.read_csv(features_path), pd.read_csv(scores_path)
        record(features_path)
        record(scores_path)
        validate_alignment(features=features, scores=scores)
        require(features['history_complete'].isin([0, 1]).all(), f'{folder.name}: invalid history mask')
        if features['history_complete'].eq(1).all():
            rules = pd.DataFrame(infer_dataframe(features, research_baseline))
            require_reproduction(rules, scores, 'level', f'{folder.name}/baseline')
            outputs = variants(rules, scores[MODEL_COLUMNS], features)
            require_reproduction(outputs['hybrid'], scores, 'guarded_level', f'{folder.name}/hybrid')
        else:
            require(scores['guarded_level'].eq('unavailable').all(),
                    f'{folder.name}: incomplete observations must be frozen as unavailable')
            outputs = {method: pd.DataFrame({'level': ['unavailable'] * len(features)}) for method in METHODS}
        for method, frame in outputs.items():
            row = {'case': case['case'], 'family': case['family'], 'seed': case['seed'],
                   'intensity': case['intensity'], 'method': method, **summary(frame)}
            row.pop('levels')
            result_rows.append(row)
    cases = pd.DataFrame(result_rows)
    cases.to_csv(output / 'case_comparison.csv', index=False)
    families = {}
    for family, group in cases.groupby('family'):
        families[family] = {}
        for method, subset in group.groupby('method'):
            families[family][method] = {
                'cases': len(subset), 'alert_cases': int(subset['max_level'].isin(['attention', 'risk']).sum()),
                'levels': dict(Counter(subset['max_level'])),
            }
    result = {
        'source_type': 'synthetic', 'clinical_validation': False, 'production_eligible': False,
        'methods': list(METHODS), 'same_repetition_gate': True, 'routine_correction_applied': False,
        'ablation_semantics': 'All methods retain the same Baseline, repetition gate and observation mask. IF/AE ablations disable only the other model promotion signal; model-driven risk still requires both models risk. Baseline risk is preserved.',
        'no_retraining': True, 'frozen_hybrid_reproduced_for_all_cases': True,
        'baseline_construction': baseline_info, 'fridge': fridge, 'families': families,
        'source_sha256': hashes,
        'limitations': [
            'These are correlated synthetic cases, not independent people or clinical sensitivity/specificity.',
            'Reference, normal controls and future cases share simulation templates.',
            'Any early-warning difference is a single-fixture observation, not a general detection-time guarantee.',
            'Normal-context alarms can increase when learned models are added; intent remains unobserved.',
            'The 14-day Baseline fixture and 30-day IF/AE fixture are not the deployed household baseline.',
        ],
    }
    (output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'fridge_first_alerts': {k: v['first_alert_elapsed_minutes'] for k, v in fridge['five_minute_rechecks']['methods'].items()},
                      'families': families, 'normal_controls': baseline_info['future_control_levels']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.source_root.resolve(), args.output_dir.resolve())
