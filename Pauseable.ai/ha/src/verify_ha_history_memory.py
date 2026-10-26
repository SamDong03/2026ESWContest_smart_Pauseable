
import argparse
import gc
import json
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd

from ha_model_lifecycle import Lifecycle, SCHEMA, atomic_json
from make_ha_features import FEATURE_COLUMNS


def run(output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    house = 'synthetic-45day-minute-memory'
    life = Lifecycle(output / 'models', 'synthetic', house, policy='hybrid')
    times = pd.date_range('2026-01-01', periods=45 * 24 * 60, freq='min')
    frame = pd.DataFrame({name: np.zeros(len(times)) for name in FEATURE_COLUMNS if name != 'window_end'})
    frame['window_end'] = times.astype(str)
    frame['hour'] = times.hour
    frame['is_night'] = (times.hour < 6).astype(int)
    for name, angle in [('hour', times.hour * 2 * np.pi / 24), ('weekday', times.dayofweek * 2 * np.pi / 7)]:
        frame[name + '_sin'], frame[name + '_cos'] = np.sin(angle), np.cos(angle)
    noon = (times.hour == 12).astype(int)
    for suffix, count in [('10m', 4), ('30m', 6), ('1h', 6)]:
        frame['fridge_door_open_count_' + suffix] = noon * count
        frame['fridge_door_toggle_count_' + suffix] = noon * count * 2
    frame['source_type'], frame['household_id'], frame['schema_version'] = 'synthetic', house, SCHEMA
    frame['history_complete'] = 1
    rules = frame[['window_end']].assign(level='normal')
    life.ingest(frame, rules)
    del frame, rules
    gc.collect()
    for day in range(45):
        start = times[day * 1440]
        end = times[(day + 1) * 1440 - 1]
        utc = lambda stamp: stamp.tz_localize('Asia/Seoul').tz_convert('UTC').isoformat()
        life.feedback.apply({'contract_version': '1.0', 'feedback_id': f'synthetic-memory-day-{day}',
                             'source_type': 'synthetic', 'household_id': house,
                             'patient_id': 'byunwoojin', 'device_id': 'pi5-home-01',
                             'review_kind': 'behavior_label', 'label': 'normal',
                             'reviewer_id': 'synthetic-fixture-reviewer',
                             'reviewed_at': utc(end + pd.Timedelta(minutes=1)),
                             'period': {'start': utc(start), 'end': utc(end)},
                             'reason': 'Generated feature fixture, not patient or human-reviewed evidence'})
    history = life.feedback.history()
    assert len(history) == len(times)
    del history
    gc.collect()
    training = life.maybe_train(now='2026-02-16T00:00:00Z')
    assert training['status'] == 'active', training
    routine = life.routine_policy('2026-02-15 00:00:00')
    assert len(routine.profile['profiles']) == 7
    active = life.active_dir()
    trained_rows = len(pd.read_csv(active.parent / 'training.csv', usecols=['window_end']))
    assert trained_rows == 6000
    report = {'passed': True, 'synthetic_only': True, 'days': 45, 'minute_rows': len(times),
              'explicit_fixture_review_days': 45, 'actual_if_ae_training': True,
              'training_rows': trained_rows, 'routine_profiles': len(routine.profile['profiles']),
              'peak_process_rss_mib': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
              'seconds': round(time.monotonic() - started, 2),
              'caller_must_enforce_memory_limit': True, 'pi_arm64_tested': False,
              'clinical_validation': False, 'production_eligible': False}
    atomic_json(output / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2), flush=True)
