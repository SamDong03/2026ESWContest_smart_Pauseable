
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from entity_mapper import convert_rows
from ha_model_lifecycle import Lifecycle, SCHEMA, atomic_json, combine
from infer_ha_baseline import infer_dataframe
from make_ha_features import build_features
from verify_ha_month_cycle import scenario, synthetic_baseline

HOUSE = 'synthetic-reviewed-routine-acceptance'


def run(output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    raw, origin = scenario(42)
    added = []
    for day in range(42):
        for minute in (2, 4, 6, 8, 32, 34, 36, 38):
            for second, state in ((0, 'on'), (2, 'off')):
                at = origin + pd.Timedelta(days=day, hours=12, minutes=minute, seconds=second)
                stamp = at.isoformat() + '+09:00'
                added.append({'recorded_at': stamp, 'event_time': stamp, 'record_type': 'state_changed_event',
                              'entity_id': 'binary_sensor.test_fridge_door', 'state': state})
    raw = pd.concat([raw, pd.DataFrame(added)], ignore_index=True).sort_values('recorded_at', kind='stable')
    raw.to_csv(output / 'generated_raw_events.csv', index=False)
    standard = pd.DataFrame([item for row in raw.to_dict('records') for item in convert_rows(row) if item['action'] != 'skip'])
    features = build_features(standard, origin.to_pydatetime(),
                              (origin + pd.Timedelta(days=42, minutes=-30)).to_pydatetime(), step_minutes=30)
    features['source_type'], features['household_id'], features['schema_version'] = 'synthetic', HOUSE, SCHEMA
    times = pd.to_datetime(features['window_end'])
    features['history_complete'] = (times >= origin + pd.Timedelta(hours=2)).astype(int)
    baseline = synthetic_baseline()
    atomic_json(output / 'common_synthetic_baseline.json', baseline)
    all_rules = pd.DataFrame(infer_dataframe(features, baseline))
    training = features.loc[times < origin + pd.Timedelta(days=30)].copy()
    future = features.loc[times >= origin + pd.Timedelta(days=30)].copy()
    life = Lifecycle(output / 'models', 'synthetic', HOUSE, policy='hybrid', retrain_days=7)
    life.ingest(training, all_rules.loc[all_rules['window_end'].isin(training['window_end'])])
    for day in range(30):
        start = origin + pd.Timedelta(days=day, hours=2 if day == 0 else 0)
        end = origin + pd.Timedelta(days=day, hours=23, minutes=30)
        message = {'contract_version': '1.0', 'feedback_id': f'synthetic-day-{day}', 'source_type': 'synthetic',
                   'household_id': HOUSE, 'patient_id': 'byunwoojin', 'device_id': 'pi5-home-01',
                   'review_kind': 'behavior_label', 'label': 'normal', 'reviewer_id': 'synthetic-fixture-reviewer',
                   'reviewed_at': (end + pd.Timedelta(minutes=1)).tz_localize('Asia/Seoul').tz_convert('UTC').isoformat(),
                   'period': {'start': start.tz_localize('Asia/Seoul').tz_convert('UTC').isoformat(),
                              'end': end.tz_localize('Asia/Seoul').tz_convert('UTC').isoformat()},
                   'reason': 'Generated normal routine by construction, not real human/patient evidence'}
        life.feedback.apply(message)
    status = life.maybe_train(now=(origin + pd.Timedelta(days=30, hours=1)).tz_localize('Asia/Seoul').tz_convert('UTC'))
    assert status['status'] == 'active', status
    future_rules = all_rules.loc[all_rules['window_end'].isin(future['window_end'])].copy()
    scores = life.score(future)
    routine = life.routine_policy(future['window_end'].min())
    before = combine(future_rules, scores, 'hybrid', future)
    after = combine(future_rules, scores, 'hybrid', future, routine)
    before.to_csv(output / 'before_personalization.csv', index=False)
    after.to_csv(output / 'after_personalization.csv', index=False)
    training.to_csv(output / 'training_features_before_review_overlay.csv', index=False)
    changed = after['personalization_status'].eq('reviewed_routine_confirmed_by_models')
    assert changed.any(), 'No held-out reviewed routine was recognized with real IF/AE scores'
    assert after.loc[changed, 'level'].eq('normal').all()
    assert after.loc[changed, ['if_level', 'ae_level']].eq('normal').all().all()
    assert after.loc[after['protected_rule'].ne(''), 'level'].eq(before.loc[after['protected_rule'].ne(''), 'level']).all()

    novel = future.loc[pd.to_datetime(future['window_end']).dt.hour.eq(13)].tail(1).copy()
    for suffix in ('10m', '30m', '1h'):
        novel['fridge_door_open_count_' + suffix], novel['fridge_door_toggle_count_' + suffix] = 20, 40
    novel_rules = pd.DataFrame(infer_dataframe(novel, baseline))
    novel_result = combine(novel_rules, life.score(novel), 'hybrid', novel, routine)
    assert novel_result.iloc[0]['level'] == 'risk'
    novel_result.to_csv(output / 'novel_dense_repeat.csv', index=False)
    target = origin + pd.Timedelta(days=14, hours=12, minutes=30)
    correction = {'contract_version': '1.0', 'feedback_id': 'synthetic-review-correction', 'source_type': 'synthetic',
                  'household_id': HOUSE, 'patient_id': 'byunwoojin', 'device_id': 'pi5-home-01',
                  'review_kind': 'behavior_label', 'label': 'repetitive', 'reviewer_id': 'synthetic-fixture-reviewer',
                  'reviewed_at': (origin + pd.Timedelta(days=42)).tz_localize('Asia/Seoul').tz_convert('UTC').isoformat(),
                  'period': {'start': target.tz_localize('Asia/Seoul').tz_convert('UTC').isoformat(),
                                                 'end': target.tz_localize('Asia/Seoul').tz_convert('UTC').isoformat()}}
    life.feedback.apply(correction)
    assert life.score(future.tail(1))['model_status'].eq('invalid_model').all()
    assert life.feedback.reviewed_frame(training).loc[training['window_end'].eq(str(target)), 'review_status'].eq('excluded').all()
    refreshed = life.maybe_train(now=correction['reviewed_at'])
    assert refreshed['status'] == 'active', refreshed
    active = life.active_dir()
    retrained_rows = pd.read_csv(active.parent / 'training.csv')
    assert not retrained_rows['window_end'].eq(str(target)).any()
    assert life.score(future.tail(1))['model_status'].eq('shadow').all()
    report = {'passed': True, 'source_type': 'synthetic', 'actual_if_ae_training': True,
              'reviewed_days': 30, 'future_windows': len(future), 'routine_profiles': len(routine.profile['profiles']),
              'advisory_windows_cleared': int(changed.sum()), 'novel_dense_repeat_preserved': True,
              'corrected_training_label_invalidated_model': True, 'clinical_validation': False,
              'actual_retraining_after_review_correction': True,
              'corrected_window_excluded_from_retraining': True,
              'production_eligible': False,
              'limitations': ['Constructed normal routine labels are not real guardian observations.',
                              'This is a deterministic integration test, not clinical false-positive performance.']}
    atomic_json(output / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2), flush=True)
