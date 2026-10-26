
import argparse
from datetime import timedelta
import json
from pathlib import Path
import platform
import time

import numpy as np
import pandas as pd

from build_baseline import build_baseline
from entity_mapper import convert_rows
from ha_anomaly_models import score_frame
from ha_model_lifecycle import Lifecycle, SCHEMA, atomic_json, combine
from infer_ha_baseline import infer_dataframe
from make_ha_features import build_features

BASE = Path(__file__).resolve().parents[1]
HOUSE = 'synthetic-month-acceptance'


def scenario(days, offset=0, anomalies=False):
    rng = np.random.default_rng(319 + offset)
    origin = pd.Timestamp('2026-01-01') + pd.Timedelta(days=offset)
    rows = []

    def emit(at, entity, state, attributes=None, snapshot=False):
        stamp = at.isoformat() + '+09:00'
        rows.append({'recorded_at': stamp, 'event_time': stamp, 'record_type': 'state_snapshot' if snapshot else 'state_changed_event',
                     'entity_id': entity, 'domain': entity.split('.')[0], 'state': state,
                     'friendly_name': entity, 'last_changed': stamp, 'last_updated': stamp,
                     'attributes_json': json.dumps(attributes or {})})

    for entity, state in [('binary_sensor.test_fridge_door', 'off'), ('lock.test_door_lock', 'locked'),
                           ('sensor.test_microwave_operation_state', 'idle'), ('sensor.test_washer_operation_state', 'idle'),
                           ('sensor.test_dryer_operation_state', 'idle'), ('sensor.test_dishwasher_operation_state', 'idle'),
                           ('switch.test_air_purifier_power', 'off'), ('climate.test_air_conditioner', 'off')]:
        emit(origin, entity, state, snapshot=True)
    for day in range(days):
        start = origin + pd.Timedelta(days=day)
        for hour in (7, 12, 19):
            at = start + pd.Timedelta(hours=hour, minutes=int(rng.integers(35, 48)))
            emit(at, 'binary_sensor.test_fridge_door', 'on')
            emit(at + pd.Timedelta(minutes=1), 'binary_sensor.test_fridge_door', 'off')
        for hour in (8, 18):
            at = start + pd.Timedelta(hours=hour, minutes=40)
            emit(at, 'lock.test_door_lock', 'unlocked')
            emit(at + pd.Timedelta(minutes=1), 'lock.test_door_lock', 'locked')
        for hour in rng.choice([7, 12, 18, 19], size=2, replace=False):
            at = start + pd.Timedelta(hours=int(hour), minutes=40)
            for minute, action in [(0, 'running'), (3, 'done'), (5, 'idle')]:
                emit(at + pd.Timedelta(minutes=minute), 'sensor.test_microwave_operation_state', action)
        for device, hour in [('washer', 10), ('dryer', 14), ('dishwasher', 20)]:
            if device != 'dishwasher' and day % 2:
                continue
            at = start + pd.Timedelta(hours=hour, minutes=10)
            emit(at, f'sensor.test_{device}_operation_state', 'running')
            emit(at + pd.Timedelta(minutes=65), f'sensor.test_{device}_operation_state', 'done')
            emit(at + pd.Timedelta(minutes=70), f'sensor.test_{device}_operation_state', 'idle')
        emit(start + pd.Timedelta(hours=9, minutes=40), 'switch.test_air_purifier_power', 'on')
        emit(start + pd.Timedelta(hours=20, minutes=40), 'switch.test_air_purifier_power', 'off')
        emit(start + pd.Timedelta(hours=13, minutes=40), 'climate.test_air_conditioner', 'cool',
             {'temperature': int(rng.integers(23, 27)), 'fan_mode': 'auto'})
        emit(start + pd.Timedelta(hours=17, minutes=40), 'climate.test_air_conditioner', 'off',
             {'temperature': 24, 'fan_mode': 'auto'})
        if anomalies and day % 2:
            at = start + pd.Timedelta(hours=2, minutes=40)
            for repeat in range(8):
                for second, action in [(0, 'running'), (20, 'done'), (40, 'idle')]:
                    emit(at + pd.Timedelta(minutes=repeat, seconds=second), 'sensor.test_microwave_operation_state', action)
    return pd.DataFrame(rows).sort_values('recorded_at', kind='stable').reset_index(drop=True), origin


def features_from_raw(raw, origin, days):
    standard = pd.DataFrame([item for row in raw.to_dict('records') for item in convert_rows(row)
                             if item['action'] != 'skip'])
    features = build_features(standard, origin.to_pydatetime(),
                              (origin + pd.Timedelta(days=days) - pd.Timedelta(hours=1)).to_pydatetime(), step_minutes=60)
    features['source_type'], features['household_id'], features['schema_version'] = 'synthetic', HOUSE, SCHEMA
    features['history_complete'] = (pd.to_datetime(features['window_end']) >= origin + pd.Timedelta(hours=2)).astype(int)
    return standard, features


def synthetic_baseline():

    raw, origin = scenario(14, offset=-14)
    _, features = features_from_raw(raw, origin, 14)
    features = features.drop(columns=['source_type', 'household_id', 'schema_version', 'history_complete'])
    baseline = build_baseline(features)
    baseline['source_type'] = 'synthetic'
    baseline['description'] = 'Synthetic acceptance fixture only; not a household or clinical baseline'
    return baseline


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--phase', choices=['train', 'verify', 'refresh'], required=True)
    args = p.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lifecycle = Lifecycle(root / 'synthetic_models', 'synthetic', HOUSE, policy='hybrid',
                          retrain_days=7 if args.phase == 'refresh' else 0)
    began = time.monotonic()
    baseline_path = root / 'synthetic_baseline.json'
    if args.phase == 'train':
        if (root / 'train_report.json').exists():
            raise ValueError('Test already completed; choose a new isolated directory')
        baseline = synthetic_baseline()
        atomic_json(baseline_path, baseline)
        raw, origin = scenario(30)
        raw.to_csv(root / 'month_raw_ha.csv', index=False)
        standard, features = features_from_raw(raw, origin, 30)
        standard.to_csv(root / 'month_standard.csv', index=False)
        features.to_csv(root / 'month_features.csv', index=False)
        rules = pd.DataFrame(infer_dataframe(features, baseline))
        rules.to_csv(root / 'month_baseline.csv', index=False)
        counts = []
        for day in range(1, 31):
            part = features.loc[pd.to_datetime(features['window_end']).dt.date == (origin + pd.Timedelta(days=day-1)).date()]
            lifecycle.ingest(part, rules.loc[rules['window_end'].isin(part['window_end'])])
            status = lifecycle.maybe_train(now=origin + pd.Timedelta(days=day))
            counts.append({'day': day, **status})
            print(json.dumps(counts[-1]), flush=True)
            if day < 30:
                assert status['status'] == 'collecting', status
        assert status['status'] == 'active', status
        report = {'phase': 'train', 'passed': True, 'source_type': 'synthetic', 'raw_rows': len(raw),
                  'feature_rows': len(features), 'feature_step_minutes': 60, 'days': 30,
                  'day29': counts[28]['status'], 'day30': counts[29]['status'],
                  'architecture': platform.machine(), 'seconds': time.monotonic()-began,
                  'limitations': ['Hourly feature endpoints accelerate a month; live endpoints remain one minute.',
                                  'Generated history is not real household training data or proof of real accuracy.']}
        atomic_json(root / 'train_report.json', report)
    elif args.phase == 'verify':
        assert (root / 'train_report.json').exists()
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        active = lifecycle.active_dir()
        assert active is not None
        raw, origin = scenario(4, offset=32, anomalies=True)
        raw.to_csv(root / 'future_raw_ha.csv', index=False)
        _, features = features_from_raw(raw, origin, 4)
        rules = pd.DataFrame(infer_dataframe(features, baseline))
        models = lifecycle.score(features)
        result = combine(rules, models, 'hybrid', features)
        result.to_csv(root / 'future_scores.csv', index=False)
        assert models.loc[features['history_complete'].eq(1), 'model_status'].eq('shadow').all()
        assert not score_frame(features.assign(source_type='local'), active)['model_status'].eq('shadow').any()
        original = (active / 'manifest.json').read_bytes()
        try:
            (active / 'manifest.json').write_bytes(b'{broken')
            broken = lifecycle.score(features)
            assert broken['model_status'].eq('invalid_model').all()
            fallback = combine(rules, broken, 'hybrid', features)
            shadow_rules = combine(rules, broken, 'shadow', features)
            assert fallback['level'].equals(shadow_rules['level'])
        finally:
            (active / 'manifest.json').write_bytes(original)
        invalid = features.assign(history_complete=0)
        assert lifecycle.score(invalid)['model_status'].eq('insufficient_history').all()
        independent_normal = pd.to_datetime(features['window_end']).dt.hour.ge(6) & features['history_complete'].eq(1)
        injected = pd.to_datetime(features['window_end']).dt.hour.eq(3) & pd.to_datetime(features['window_end']).dt.day.isin([3, 5])
        alert = models['ae_level'].isin(['attention', 'risk']) | models['if_level'].isin(['attention', 'risk'])
        report = {'phase': 'verify', 'passed': True, 'restart_load': True, 'corruption_fallback': True,
                  'source_isolation': True, 'incomplete_history_blocked': True, 'source_type': 'synthetic',
                  'rows': len(features), 'model_alerts': int(alert.sum()),
                  'future_daytime_alert_fraction': float(alert[independent_normal].mean()),
                  'injected_windows': int(injected.sum()), 'injected_detected': int(alert[injected].sum()),
                  'architecture': platform.machine(), 'seconds': time.monotonic()-began}
        atomic_json(root / 'verify_report.json', report)
    else:
        from unittest.mock import patch
        assert (root / 'verify_report.json').exists()
        if (root / 'refresh_report.json').exists():
            raise ValueError('Refresh test already completed; use a new isolated directory')
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        old = lifecycle.active_dir()
        raw, origin = scenario(45)
        _, features = features_from_raw(raw, origin, 45)
        rules = pd.DataFrame(infer_dataframe(features, baseline))
        lifecycle.ingest(features, rules)
        status = lifecycle.maybe_train('2026-02-16T00:00:00Z')
        assert status['status'] == 'active', status
        refreshed = lifecycle.active_dir()
        assert refreshed != old
        original = (lifecycle.root / 'active.json').read_bytes()
        raw, origin = scenario(54)
        _, features = features_from_raw(raw, origin, 54)
        lifecycle.ingest(features, pd.DataFrame(infer_dataframe(features, baseline)))
        with patch('ha_model_lifecycle.train_models', side_effect=RuntimeError('acceptance failure injection')):
            failed = lifecycle.maybe_train('2026-02-25T00:00:00Z')
        assert failed['status'] == 'training_failed', failed
        assert (lifecycle.root / 'active.json').read_bytes() == original
        rolled = lifecycle.rollback('Synthetic submission acceptance rollback; no household data')
        assert lifecycle.active_dir() == old
        assert lifecycle.score(features.tail(1))['model_status'].eq('shadow').all()
        report = {'phase': 'refresh', 'passed': True, 'source_type': 'synthetic',
                  'actual_retraining_completed': True, 'failed_candidate_retained_active': True,
                  'rollback_loaded_previous': True, 'refreshed_model_id': status['model_id'],
                  'rollback_model_id': rolled['model_id'], 'seconds': time.monotonic()-began}
        atomic_json(root / 'refresh_report.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
