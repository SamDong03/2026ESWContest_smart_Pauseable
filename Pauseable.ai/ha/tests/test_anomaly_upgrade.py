import json
from pathlib import Path
import sys
from contextlib import contextmanager
import uuid
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from entity_mapper import convert_row, detect_device
from ha_anomaly_models import numeric_features, score_frame
from ha_event_history import update_history
from infer_ha_autoencoder import prepare_features
from make_ha_features import build_features, parse_time, prepare_events
from train_ha_anomaly_models import chronological_split, train_models


@contextmanager
def test_directory():
    path = Path(__file__).resolve().parents[1] / 'outputs' / 'test_runs' / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path


def event(time, action, device='washer', record_type='state_changed_event', entity='sensor.washer_status'):
    return {'event_time': time, 'device_type': device, 'signal_type': 'operation', 'action': action,
            'entity_id': entity, 'record_type': record_type, 'recorded_at': time}


class InputTests(unittest.TestCase):
    def test_missing_features_are_not_zero(self):
        for function in (numeric_features, prepare_features):
            with self.assertRaisesRegex(ValueError, 'Missing|mismatch'):
                function(pd.DataFrame({'x': [1]}), ['x', 'y'])

    def test_nan_is_not_normal(self):
        with self.assertRaises(ValueError):
            numeric_features(pd.DataFrame({'x': [np.nan]}), ['x'])

    def test_utc_becomes_korean_night(self):
        value = parse_time('2026-09-01T18:05:00Z')
        self.assertEqual((value.day, value.hour), (2, 3))

    def test_dishwasher_does_not_match_washer(self):
        self.assertEqual(detect_device('sensor.dishwasher_current_status'), 'dishwasher')

    def test_night_window_uses_event_time_and_existing_night_hours(self):
        rows = [event('2026-09-01 20:59', 'running', device='microwave'),
                event('2026-09-01 21:00', 'done', device='microwave'),
                event('2026-09-01 21:01', 'running', device='microwave')]
        features = build_features(pd.DataFrame(rows))
        self.assertEqual(features.iloc[-1]['microwave_night_start_count_1h'], 1)
        self.assertEqual(features.iloc[-1]['is_night'], 1)

    def test_snapshot_not_counted_or_backdated(self):
        item = event('2026-09-01 10:00:00', 'running', record_type='state_snapshot')
        item['event_time'] = '2026-08-01 00:00:00'
        feature = build_features(pd.DataFrame([item])).iloc[-1]
        self.assertEqual(feature['washer_start_count_2h'], 0)
        self.assertTrue(feature['window_end'].startswith('2026-09-01'))

    def test_final_partial_minute_is_included_offline(self):
        features = build_features(pd.DataFrame([event('2026-09-01 10:00:45', 'running')]))
        self.assertEqual(features.iloc[-1]['washer_start_count_2h'], 1)

    def test_normalized_running_substates_not_repeated_start(self):
        rows = [event('2026-09-01 10:00', 'idle'), event('2026-09-01 10:01', 'running'), event('2026-09-01 10:02', 'running')]
        self.assertEqual(build_features(pd.DataFrame(rows)).iloc[-1]['washer_start_count_2h'], 1)

    def test_device_streams_not_cross_counted(self):
        rows = [event('2026-09-01 10:00', 'done', entity='sensor.washer_a'),
                event('2026-09-01 10:01', 'running', entity='sensor.washer_b')]
        self.assertEqual(build_features(pd.DataFrame(rows)).iloc[-1]['washer_done_to_restart_count_2h'], 0)

    def test_mapper_preserves_snapshot_provenance(self):
        row = convert_row({'event_time': '2026-09-01', 'recorded_at': '2026-09-02', 'record_type': 'state_snapshot',
                           'entity_id': 'sensor.washer_current_status', 'state': 'washing'})
        self.assertEqual(row['record_type'], 'state_snapshot')
        self.assertEqual(row['recorded_at'], '2026-09-02')

    def test_context_crosses_collection_boundary(self):
        with test_directory() as tmp:
            path = Path(tmp) / 'history.csv'
            update_history(pd.DataFrame([event('2026-09-01 10:08', 'done')]), path, '2026-09-01 10:00', '2026-09-01 10:10', 'local')
            joined, since = update_history(pd.DataFrame([event('2026-09-01 10:12', 'running')]), path, '2026-09-01 10:10:10', '2026-09-01 10:20', 'local')
            self.assertEqual(build_features(joined).iloc[-1]['washer_done_to_restart_count_2h'], 1)
            self.assertEqual(since.hour, 10)
            self.assertEqual(since.minute, 0)

    def test_collection_gap_resets_coverage(self):
        with test_directory() as tmp:
            path = Path(tmp) / 'history.csv'
            rows = pd.DataFrame([event('2026-09-01 10:00', 'done')])
            update_history(rows, path, '2026-09-01 10:00', '2026-09-01 10:10', 'local')
            _, since = update_history(rows, path, '2026-09-01 11:00', '2026-09-01 11:10', 'local')
            self.assertEqual(since.hour, 11)
            with self.assertRaises(ValueError):
                update_history(rows, path, '2026-09-01 11:10', '2026-09-01 11:20', 'synthetic')


class ModelTests(unittest.TestCase):
    def frame(self):
        rng = np.random.default_rng(77)
        return pd.DataFrame({'window_end': pd.date_range('2026-01-01', periods=960, freq='15min').astype(str),
                             'x': rng.normal(size=960), 'y': rng.normal(size=960)})

    def test_temporal_split_has_two_hour_purge(self):
        train, calibration, test = chronological_split(self.frame())
        for earlier, later in ((train, calibration), (calibration, test)):
            gap = pd.Timestamp(later.window_end.iloc[0]) - pd.Timestamp(earlier.window_end.iloc[-1])
            self.assertGreater(gap, pd.Timedelta(hours=2))

    def test_duplicate_and_short_history_rejected(self):
        frame = self.frame()
        frame.loc[1, 'window_end'] = frame.loc[0, 'window_end']
        with self.assertRaises(ValueError):
            chronological_split(frame)
        with self.assertRaises(ValueError):
            chronological_split(frame.head(10))

    def test_cold_start_does_not_claim_normal(self):
        with test_directory() as tmp:
            result = score_frame(self.frame().head(1), tmp)
            self.assertEqual(result.iloc[0].model_status, 'not_trained')
            self.assertEqual(result.iloc[0].if_level, 'unavailable')

    def test_train_export_and_shadow_contract(self):
        with test_directory() as tmp:
            frame = self.frame().assign(source_type='synthetic', household_id='test-house', history_complete=1)
            source = Path(tmp) / 'normal.csv'
            frame.to_csv(source, index=False)
            manifest, report = train_models(source, Path(tmp) / 'model', 'synthetic', 'test-house', 'generated normal-only test fixture')
            self.assertIsNone(report['recall'])
            self.assertLess(report['ae_export_max_abs_error'], 1e-8)
            result = score_frame(frame.iloc[-10:].reset_index(drop=True), Path(tmp) / 'model')
            self.assertTrue(result.model_status.eq('shadow').all())
            absent = score_frame(frame.drop(columns='household_id').head(1), Path(tmp) / 'model')
            self.assertEqual(absent.iloc[0].model_status, 'incompatible_source')
            other = score_frame(frame.head(1).assign(household_id='other'), Path(tmp) / 'model')
            self.assertEqual(other.iloc[0].model_status, 'incompatible_source')
            missing = score_frame(frame.drop(columns='x').head(1), Path(tmp) / 'model')
            self.assertEqual(missing.iloc[0].model_status, 'invalid_features')
            incomplete = score_frame(frame.head(1).assign(history_complete=0), Path(tmp) / 'model')
            self.assertEqual(incomplete.iloc[0].model_status, 'insufficient_history')
            wrong_source = score_frame(frame.head(1).assign(source_type='local'), Path(tmp) / 'model')
            self.assertEqual(wrong_source.iloc[0].model_status, 'incompatible_source')
            with self.assertRaises(ValueError):
                train_models(source, Path(tmp) / 'model', 'synthetic', 'test-house', 'test')

    def test_abnormal_or_mixed_households_not_used_for_training(self):
        with test_directory() as tmp:
            path = Path(tmp) / 'input.csv'
            frame = self.frame().assign(label='risk')
            frame.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                train_models(path, Path(tmp) / 'model', 'local', 'one', 'review')
            frame = self.frame().assign(household_id='other')
            frame.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                train_models(path, Path(tmp) / 'model', 'local', 'one', 'review')


if __name__ == '__main__':
    unittest.main()
