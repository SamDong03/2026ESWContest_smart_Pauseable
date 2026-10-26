import json
from pathlib import Path
import sys
import sqlite3
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from test_anomaly_upgrade import test_directory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from baseline_update import update_baseline, feature_columns
from collect_ha_events_ws import event_to_row, get_states
from entity_mapper import convert_rows
from ha_coverage import complete_windows, usable_windows
from ha_model_lifecycle import Lifecycle, SCHEMA, combine, store_frame, load_frame
from infer_ha_baseline import infer_dataframe
from make_ha_features import build_features


class FullCycleTests(unittest.TestCase):
    def test_compressed_and_legacy_history_round_trip(self):
        with test_directory() as tmp:
            path = Path(tmp) / 'history.sqlite3'
            legacy = {'window_end': '2026-01-01 00:00:00', 'x': 1.25, 'label': 'legacy'}
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE observations (window_end TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('INSERT INTO observations VALUES (?, ?)', (legacy['window_end'], json.dumps(legacy)))
            current = pd.DataFrame([{'window_end': '2026-01-01 00:01:00', 'x': 2.5, 'label': 'compressed'}])
            store_frame(path, current)
            result = load_frame(path)
            self.assertEqual(result['x'].tolist(), [1.25, 2.5])
            self.assertEqual(result['label'].tolist(), ['legacy', 'compressed'])
            store_frame(path, current.assign(x=3.5))
            self.assertEqual(load_frame(path)['x'].tolist(), [1.25, 3.5])
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT DISTINCT typeof(payload) FROM observations ORDER BY 1').fetchall(),
                                 [('blob',), ('text',)])

    def frame(self, days=30):
        return pd.DataFrame({'window_end': pd.date_range('2026-01-01', periods=24*days, freq='h').astype(str),
                             'source_type': 'synthetic', 'household_id': 'test', 'schema_version': SCHEMA,
                             'history_complete': 1, 'x': np.random.default_rng(42).normal(size=24*days)})

    def rules(self, frame):
        return frame[['window_end']].assign(level='normal', risk_score=0)

    def test_29_days_wait_and_future_rejected(self):
        with test_directory() as tmp:
            life = Lifecycle(tmp, 'synthetic', 'test')
            frame = self.frame(29)
            life.ingest(frame, self.rules(frame))
            self.assertEqual(life.maybe_train('2026-01-30')['status'], 'collecting')
            self.assertEqual(life.maybe_train('2026-01-01')['reason'], 'future_data')

    def test_sparse_month_not_eligible(self):
        with test_directory() as tmp:
            life = Lifecycle(tmp, 'synthetic', 'test')
            frame = self.frame().iloc[::24]
            life.ingest(frame, self.rules(frame))
            self.assertEqual(life.maybe_train('2026-02-01')['observed_days'], 0)

    def test_training_failure_keeps_baseline_and_backs_off(self):
        with test_directory() as tmp:
            life = Lifecycle(tmp, 'synthetic', 'test')
            frame = self.frame()
            life.ingest(frame, self.rules(frame))
            with patch('ha_model_lifecycle.train_models', side_effect=RuntimeError('fixture failure')):
                self.assertEqual(life.maybe_train('2026-02-01')['status'], 'training_failed')
            self.assertFalse((Path(tmp) / 'active.json').exists())
            self.assertEqual(life.maybe_train('2026-02-01')['status'], 'retry_deferred')
            self.assertTrue(life.score(frame)['model_status'].eq('not_trained').all())

    def test_rejected_gate_never_activates(self):
        with test_directory() as tmp:
            life = Lifecycle(tmp, 'synthetic', 'test')
            frame = self.frame()
            life.ingest(frame, self.rules(frame))
            with patch('ha_model_lifecycle.train_models', return_value=({'model_id':'fixture'},
                       {'normal_holdout_alert_fraction': {'or': .3}})):
                self.assertEqual(life.maybe_train('2026-02-01')['status'], 'rejected')
            self.assertFalse((Path(tmp) / 'active.json').exists())

    def test_cannot_open_synthetic_store_as_local(self):
        with test_directory() as tmp:
            Lifecycle(tmp, 'synthetic', 'test')
            with self.assertRaisesRegex(ValueError, 'different source'):
                Lifecycle(tmp, 'local', 'test')

    def test_hybrid_preserves_rules_and_uses_agreement(self):
        rules = pd.DataFrame({'window_end':['a','b','c'], 'level':['risk','normal','normal'], 'risk_score':[86,0,0]})
        models = pd.DataFrame({'window_end':['a','b','c'], 'model_status':['shadow']*3,
                               'ae_level':['normal','risk','risk'], 'if_level':['normal','normal','risk']})
        features = rules[['window_end']].assign(fridge_door_open_count_1h=2)
        result = combine(rules, models, 'hybrid', features)
        self.assertEqual(result['level'].tolist(), ['risk', 'attention', 'risk'])
        self.assertEqual(result['risk_score'].tolist(), [86,35,70])

    def test_empty_csv_text_columns_remain_assignable(self):
        rules = pd.DataFrame({'window_end':['a'], 'level':['normal'], 'risk_score':[0],
                              'primary_pattern':[float('nan')], 'reasons':[float('nan')]})
        models = pd.DataFrame({'window_end':['a'], 'model_status':['not_trained'],
                               'ae_level':['unavailable'], 'if_level':['unavailable']})
        result = combine(rules, models, 'hybrid')
        result.loc[0, 'reasons'] = 'incomplete coverage'
        self.assertEqual(result.loc[0, 'reasons'], 'incomplete coverage')

    def test_disconnected_time_not_complete(self):
        times = ['2026-01-01 03:00']
        self.assertEqual(complete_windows(times, []), [0])
        self.assertEqual(complete_windows(times, [['2026-01-01 00:00','2026-01-01 03:00']]), [1])
        self.assertEqual(complete_windows(times, [['2026-01-01 00:00','2026-01-01 02:00'],
                                                 ['2026-01-01 02:00:01','2026-01-01 03:00']]), [0])

    def test_persistent_unavailable_never_becomes_normal(self):
        raw = pd.DataFrame({'recorded_at':['2026-01-01 00:00'], 'state':['unavailable'], 'entity_id':['climate.ac']})
        self.assertEqual(usable_windows(['2026-01-01 03:00'], raw,
                          [['2026-01-01 00:00','2026-01-01 04:00']]), [0])

    def test_snapshot_command_dispatches_interleaved_events(self):
        ws = Mock()
        ws.recv_json.side_effect = [{'type':'event','event':{'fixture':1}},
                                    {'type':'result','id':2,'success':True,'result':[]}]
        handler = Mock()
        self.assertEqual(get_states(ws, 2, handler), [])
        handler.assert_called_once_with({'fixture':1})

    def test_climate_target_change_keeps_independent_streams(self):
        old = {'entity_id':'climate.air_conditioner','state':'cool','attributes':{'temperature':24,'fan_mode':'auto'}}
        new = {**old, 'attributes':{'temperature':25,'fan_mode':'auto'}}
        event = {'time_fired':'2026-01-01T01:00:00+09:00','data':{'old_state':old,'new_state':new}}
        row = event_to_row(event, False)
        self.assertIsNotNone(row)
        first = {**row, 'attributes_json':json.dumps(old['attributes']), 'event_time':'2026-01-01T00:59:00+09:00'}
        features = build_features(pd.DataFrame(convert_rows(first) + convert_rows(row))).iloc[-1]
        self.assertEqual(features['air_conditioner_temperature_change_count_30m'], 1)
        self.assertEqual(features['air_conditioner_mode_change_count_30m'], 0)

    def test_dishwasher_repeated_restart_has_rule(self):
        frame = pd.DataFrame([{'window_end':'2026-01-01 12:00', 'dishwasher_done_to_restart_count_2h':3,
                              'dishwasher_start_count_2h':4}])
        self.assertEqual(infer_dataframe(frame, {})[0]['level'], 'risk')

    def test_baseline_rejects_public_and_unreviewed(self):
        with test_directory() as tmp:
            frame = self.frame().assign(source_type='public')
            with self.assertRaises(ValueError):
                update_baseline(frame, {}, Path(tmp)/'history.csv', None, True, 30)
        self.assertNotIn('household_id', feature_columns(self.frame()))


if __name__ == '__main__':
    unittest.main()
