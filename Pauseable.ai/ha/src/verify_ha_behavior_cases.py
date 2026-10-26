
import argparse
import json
from pathlib import Path

import pandas as pd

from entity_mapper import convert_rows
from ha_model_lifecycle import Lifecycle, atomic_json, combine, SCHEMA
from infer_ha_baseline import infer_dataframe
from make_ha_features import build_features
from verify_ha_month_cycle import HOUSE


def run(month_dir, output_dir):
    root, output = Path(month_dir), Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    baseline = json.loads((root / 'synthetic_baseline.json').read_text())
    life = Lifecycle(root / 'synthetic_models', 'synthetic', HOUSE, policy='hybrid')
    cases = []
    for name, minutes in [('single_use', [0]), ('five_minute_rechecks', list(range(0, 60, 5)))]:
        origin = pd.Timestamp('2026-04-01 10:00:00')
        rows = []
        for at, state, snapshot in [(origin, 'off', True)] + [
                (origin + pd.Timedelta(hours=2, minutes=minute, seconds=second), state, False)
                for minute in minutes for second, state in [(0, 'on'), (2, 'off')]]:
            stamp = at.isoformat() + '+09:00'
            rows.append({'recorded_at': stamp, 'event_time': stamp, 'entity_id': 'binary_sensor.test_fridge_door',
                         'state': state, 'record_type': 'state_snapshot' if snapshot else 'state_changed_event'})
        raw = pd.DataFrame(rows)
        standard = pd.DataFrame([item for row in rows for item in convert_rows(row) if item['action'] != 'skip'])
        features = build_features(standard, origin.to_pydatetime(), (origin + pd.Timedelta(hours=3)).to_pydatetime())
        features['source_type'], features['household_id'], features['schema_version'] = 'synthetic', HOUSE, SCHEMA
        features['history_complete'] = (pd.to_datetime(features['window_end']) >= origin + pd.Timedelta(hours=2)).astype(int)
        rules = pd.DataFrame(infer_dataframe(features, baseline))
        result = combine(rules, life.score(features), 'hybrid', features)
        raw.to_csv(output / f'{name}_raw.csv', index=False)
        features.to_csv(output / f'{name}_features.csv', index=False)
        result.to_csv(output / f'{name}_scores.csv', index=False)
        peaks = features[['fridge_door_open_count_10m', 'fridge_door_open_count_30m', 'fridge_door_open_count_1h']].max().to_dict()
        def first_alert(column):
            found = result.loc[result[column].isin(['attention', 'risk']), ['window_end', column]]
            return None if found.empty else found.iloc[0].to_dict()
        cases.append({'case': name, 'physical_open_close_pairs': len(minutes), 'open_duration_seconds': 2,
                      'peak_counts': {key: int(value) for key, value in peaks.items()},
                      'baseline_first_alert': first_alert('rule_level'), 'hybrid_first_alert': first_alert('level')})
    assert cases[1]['baseline_first_alert'] is not None
    assert cases[1]['peak_counts']['fridge_door_open_count_1h'] == 12
    assert cases[0]['hybrid_first_alert'] is None, 'A single normal use must not become repetitive behavior'
    report = {'passed': True, 'source_type': 'synthetic', 'cases': cases,
              'intent_inferred': False, 'clinical_validation': False,
              'limitations': ['A repeated event is not proof of forgetting or dementia.',
                              'A cooking routine can produce exactly the same observations.',
                              'Trained scores use the synthetic fixture, not a personalized patient model.']}
    atomic_json(output / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.month_dir, args.output_dir), indent=2), flush=True)
