import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import itertools
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import test_anomaly_upgrade
from test_anomaly_upgrade import test_directory
import test_full_lifecycle

from audit_ha_events import audit_events
from collect_ha_events_ws import append_event_row, run_session, selected_entity
from collect_ha_states import state_to_row
from ha_anomaly_models import validate_model_numbers
from ha_coverage import usable_windows, observation_report
from ha_model_lifecycle import Lifecycle, atomic_json, combine
from ha_runtime_health import load_baseline, validate_cycle, check_runtime_identity, read_status, validate_selection, selection_identity
from make_ha_features import build_features
from entity_mapper import convert_rows
from run_ha_full_service import run_analysis
import run_ha_full_service

BASE = Path(__file__).resolve().parents[1]
ENTITY = 'binary_sensor.test_fridge_door'


def door_event(time, old, new):
    stamp = '2026-01-01T' + time + '+09:00'
    return {'time_fired': stamp, 'data': {'entity_id': ENTITY,
        'old_state': {'entity_id': ENTITY, 'state': old},
        'new_state': {'entity_id': ENTITY, 'state': new, 'last_updated': stamp,
                      'last_changed': stamp, 'attributes': {}}}}


class EventReliabilityTests(unittest.TestCase):
    def recorded(self, tmp):
        path = Path(tmp) / 'events.csv'
        for event in [door_event('12:00:00','off','on'), door_event('12:00:02','on','off')]:
            append_event_row(path, event, [], True, False, [ENTITY])
        return pd.read_csv(path)

    def test_two_second_pair_survives_collector_mapper_features(self):
        with test_directory() as tmp:
            raw = self.recorded(tmp)
            normal = pd.DataFrame([x for row in raw.to_dict('records') for x in convert_rows(row)])
            features = build_features(normal)
            self.assertEqual(features.iloc[-1]['fridge_door_open_count_10m'], 1)
            report = audit_events(raw, ENTITY, 1)
            self.assertEqual(report['open_duration_seconds'], [2])
            self.assertEqual(report['count_check'], 'matched')
            self.assertFalse(report['physical_event_delivery_verified'])

    def test_missing_open_is_not_reconstructed_from_close(self):
        with test_directory() as tmp:
            raw = self.recorded(tmp).iloc[1:]
            report = audit_events(raw, ENTITY, 1)
            self.assertEqual(report['count_check'], 'mismatch')
            self.assertEqual(report['completed_pairs'], 0)
            self.assertEqual(report['unmatched_close_events'], 1)

    def test_audit_ignores_snapshots_and_exact_duplicates(self):
        with test_directory() as tmp:
            raw = self.recorded(tmp)
            repeated = pd.concat([raw, raw.iloc[:1], raw.iloc[:1].assign(record_type='state_snapshot')])
            report = audit_events(repeated, ENTITY)
            self.assertEqual(report['open_events'], 1)
            self.assertEqual(report['duplicate_rows_ignored'], 1)
            self.assertEqual(report['snapshots_not_counted'], 1)
            self.assertEqual(report['count_check'], 'not_measured')

    def test_disconnection_breaks_open_close_pair(self):
        with test_directory() as tmp:
            raw = self.recorded(tmp)
            outage = raw.iloc[:1].assign(event_time='2026-01-01T12:00:01+09:00', state='unavailable')
            report = audit_events(pd.concat([raw, outage]), ENTITY)
            self.assertEqual(report['completed_pairs'], 0)
            self.assertEqual(report['open_interrupted_by_unavailable'], 1)

    def test_exact_selection_overrides_keyword_but_exclusion_wins(self):
        self.assertTrue(selected_entity(ENTITY, ['unrelated'], True, [ENTITY]))
        self.assertFalse(selected_entity(ENTITY, [], True, [ENTITY], [ENTITY]))
        with self.assertRaises(ValueError):
            validate_selection([ENTITY], [ENTITY])

    def test_snapshot_cannot_overwrite_interleaved_live_event(self):
        with test_directory() as tmp:
            args = SimpleNamespace(timeout=10, entity_id=[ENTITY], exclude_entity_id=[], behavior_only=True,
                                   include_attribute_only=False, write_initial_snapshot=True, max_events=1,
                                   status_every_seconds=60)
            def snapshot(ws, command_id, handler):
                handler(door_event('12:00:00','off','on'))
                return [{'entity_id': ENTITY, 'state':'off', 'attributes':{}}]
            with patch('collect_ha_events_ws.SimpleWebSocket'), patch('collect_ha_events_ws.authenticate',
                       return_value={'ha_version':'fixture'}), patch('collect_ha_events_ws.subscribe_state_changed'), \
                    patch('collect_ha_events_ws.get_states', side_effect=snapshot):
                path = Path(tmp) / 'events.csv'
                count = run_session(args, path, 'fixture', 'http://example.test', [], None, 0)
            raw = pd.read_csv(path)
            self.assertEqual(count, 1)
            self.assertEqual(raw['state'].tolist(), ['on'])


class RuntimeContractTests(unittest.TestCase):
    def supervisor_fixture(self, stale=False, publish=False, delivery_code=0):
        with test_directory() as tmp:
            root = Path(tmp)
            baseline = root/'baseline.json'
            baseline.write_text(json.dumps({'features':{'x':{'p95':1}}}))
            atomic_json(root/'runtime_identity.json', selection_identity('fixture', baseline))
            now = datetime.now(timezone.utc)
            end = pd.Timestamp(now).floor('min')
            old_end = end - pd.Timedelta(minutes=1)
            atomic_json(root/'cursor.json', {'end':old_end.isoformat()})
            raw = pd.DataFrame([state_to_row({'entity_id':ENTITY,'state':'off'}, 'state_snapshot',
                                             (end-pd.Timedelta(hours=3)).isoformat())])
            raw.to_csv(root/'live_events.csv', index=False)
            atomic_json(root/'live_events.coverage.json', {'confirmed_at':now.isoformat(),
                        'intervals':[[(end-pd.Timedelta(hours=3)).isoformat(),now.isoformat()]]})
            def analyze(command, *unused, **options):
                if any(str(part).endswith('ha_decision_delivery.py') for part in command):
                    self.assertTrue((root/'current_decision.json').exists())
                    return delivery_code
                run_id = command[command.index('--run-id')+1]
                output = BASE/'outputs'
                atomic_json(output/'ha_live_full_data_quality.json', {'run_id':'old' if stale else run_id,
                            'detection_completed':True, 'feature_rows':1, 'status':'ok'})
                pd.DataFrame({'window_end':[str(end.tz_localize(None))], 'level':['normal'], 'risk_score':[0],
                              'model_status':['not_trained'], 'history_complete':[1], 'run_id':[run_id]}).to_csv(
                                  output/'ha_live_full_result.csv', index=False)
                return 0
            child = Mock()
            child.poll.return_value = None
            fake_modules = {'resource':SimpleNamespace(RLIMIT_AS=1,setrlimit=Mock()),
                            'fcntl':SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=Mock())}
            argv = ['service','--state-dir',str(root),'--household-id','fixture','--baseline',str(baseline),
                    '--cycle-seconds','10','--max-cycles','1']
            if publish:
                argv.append('--publish-mqtt')
            with patch.dict(sys.modules,fake_modules), patch.object(sys,'argv',argv), \
                 patch('run_ha_full_service.signal.signal'), \
                 patch('run_ha_full_service.time.monotonic',side_effect=itertools.count(100,20)), \
                 patch('run_ha_full_service.time.sleep'), \
                 patch('run_ha_full_service.subprocess.Popen',return_value=child), \
                 patch('run_ha_full_service.run_analysis',side_effect=analyze):
                run_ha_full_service.main()
            cursor = json.loads((root/'cursor.json').read_text())['end']
            status = json.loads((root/'service_status.json').read_text())
            self.assertEqual(pd.Timestamp(cursor), old_end if stale else end)
            self.assertEqual(status['status'], 'invalid_artifacts' if stale else 'ok')
            self.assertEqual((root/'decisions.sqlite3').exists(), not stale)
            if publish:
                self.assertEqual(status['mqtt_delivery_exit_code'], delivery_code)
                self.assertEqual(status['mqtt_delivery'], 'checked' if delivery_code == 0 else 'failed_pending_retry')
                if delivery_code:
                    self.assertIn('mqtt_delivery_failed', read_status(root, 1024**3)['issues'])
            child.terminate.assert_called_once()

    def test_supervisor_commits_only_validated_cycle(self):
        self.supervisor_fixture()

    def test_supervisor_does_not_advance_on_stale_cycle(self):
        self.supervisor_fixture(stale=True)

    def test_supervisor_runs_optional_delivery_without_a_second_collector(self):
        self.supervisor_fixture(publish=True)

    def test_delivery_failure_is_visible_without_losing_collected_cycle(self):
        self.supervisor_fixture(publish=True, delivery_code=1)

    def test_missing_baseline_fails_pipeline_not_feature_only_success(self):
        with test_directory() as tmp:
            events = Path(tmp) / 'events.csv'
            pd.DataFrame(columns=['event_time','device_type','signal_type','action']).to_csv(events, index=False)
            run = subprocess.run([sys.executable, str(BASE/'src/run_ha_pipeline.py'), '--input', str(events),
                                  '--baseline', str(Path(tmp)/'missing.json'), '--prefix', 'missing_baseline_test'],
                                  capture_output=True, text=True, timeout=30)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('Baseline file is missing', run.stderr)

    def test_baseline_shape_rejected(self):
        with test_directory() as tmp:
            path = Path(tmp) / 'bad.json'
            for content in ({}, {'features':{}}, []):
                path.write_text(json.dumps(content))
                with self.assertRaises(ValueError):
                    load_baseline(path)

    def test_stale_artifacts_cannot_report_success(self):
        with test_directory() as tmp:
            atomic_json(Path(tmp)/'cycle_data_quality.json', {'run_id':'old', 'detection_completed':True})
            with self.assertRaisesRegex(ValueError, 'stale'):
                validate_cycle(tmp, 'cycle', 'new')

    def test_result_count_and_run_id_are_checked(self):
        with test_directory() as tmp:
            atomic_json(Path(tmp)/'cycle_data_quality.json', {'run_id':'new', 'detection_completed':True, 'feature_rows':1})
            frame = pd.DataFrame({'window_end':['2026-01-01'], 'level':['unknown'], 'risk_score':[0],
                                  'model_status':['not_trained'], 'history_complete':[0], 'run_id':['old']})
            frame.to_csv(Path(tmp)/'cycle_result.csv', index=False)
            with self.assertRaises(ValueError):
                validate_cycle(tmp, 'cycle', 'new')
            frame['run_id'] = 'new'
            frame.to_csv(Path(tmp)/'cycle_result.csv', index=False)
            self.assertEqual(len(validate_cycle(tmp, 'cycle', 'new')[1]), 1)

    def test_selection_change_and_legacy_state_require_new_directory(self):
        with test_directory() as tmp:
            check_runtime_identity(tmp, {'entity':'a'})
            check_runtime_identity(tmp, {'entity':'a'})
            with self.assertRaisesRegex(ValueError, 'changed'):
                check_runtime_identity(tmp, {'entity':'b'})
        with test_directory() as tmp:
            (Path(tmp)/'cursor.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Legacy'):
                check_runtime_identity(tmp, {'entity':'a'})

    def test_health_distinguishes_missing_live_evidence_from_healthy_process(self):
        with test_directory() as tmp:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            atomic_json(Path(tmp)/'service_status.json', {'utc':now.isoformat(), 'status':'ok'})
            report = read_status(tmp, 100*1024**2, now)
            self.assertIn('websocket_unconfirmed', report['issues'])
            self.assertIn('low_disk', report['issues'])
            self.assertFalse(report['physical_event_delivery_verified'])

    def test_analysis_stop_reaps_child_process(self):
        with test_directory() as tmp:
            pulse = Mock()
            result = run_analysis([sys.executable, '-c', 'import time; time.sleep(20)'],
                                   Path(tmp)/'child.log', pulse, lambda: True)
            self.assertEqual(result, 130)
            pulse.assert_called()


class CoverageReliabilityTests(unittest.TestCase):
    def test_missing_required_entity_blocks_complete_history(self):
        raw = pd.DataFrame({'entity_id':['binary_sensor.fridge_door'], 'state':['off'], 'recorded_at':['2026-01-01 00:00']})
        spans = [['2026-01-01 00:00','2026-01-01 04:00']]
        required = ['binary_sensor.fridge_door','binary_sensor.fridge2_door']
        self.assertEqual(usable_windows(['2026-01-01 03:00'], raw, spans, required), [0])
        self.assertEqual(observation_report(raw, required)['missing_required_entities'], [required[1]])

    def test_late_first_required_state_is_not_full_history(self):
        raw = pd.DataFrame({'entity_id':[ENTITY], 'state':['off'], 'recorded_at':['2026-01-01 02:30']})
        self.assertEqual(usable_windows(['2026-01-01 03:00'], raw,
            [['2026-01-01 00:00','2026-01-01 04:00']], [ENTITY]), [0])

    def test_latest_availability_uses_time_not_csv_order(self):
        raw = pd.DataFrame({'entity_id':[ENTITY,ENTITY], 'state':['off','unavailable'],
                            'recorded_at':['2026-01-01 02:00','2026-01-01 00:00']})
        self.assertEqual(observation_report(raw)['unavailable_entities'], [])
        self.assertEqual(usable_windows(['2026-01-01 05:00'], raw,
            [['2026-01-01 00:00','2026-01-01 06:00']], [ENTITY]), [1])


class ModelReliabilityTests(unittest.TestCase):
    def manifest(self):
        return {'feature_columns':['x'], 'scaler':{'mean':[0], 'scale':[1]},
                'thresholds':{'ae':{'attention':1,'risk':2},'if':{'attention':.5,'risk':.7}},
                'ae_layers':[{'weight':[[1]],'bias':[0]}]}

    def test_invalid_thresholds_are_not_silent_normal(self):
        for attention, risk in [(float('nan'),2), (3,2), (1,float('inf')), (-1,2)]:
            manifest = self.manifest()
            manifest['thresholds']['ae'] = {'attention':attention, 'risk':risk}
            with self.assertRaises(ValueError):
                validate_model_numbers(manifest)

    def test_scaler_and_layer_shapes_checked(self):
        for key, value in [('scale',[0]), ('scale',[1,2]), ('mean',[float('nan')])]:
            manifest = self.manifest()
            manifest['scaler'][key] = value
            with self.assertRaises(ValueError):
                validate_model_numbers(manifest)
        manifest = self.manifest()
        manifest['ae_layers'][0]['weight'] = [[1,1]]
        with self.assertRaises(ValueError):
            validate_model_numbers(manifest)

    def test_nonconverged_candidate_is_not_activated(self):
        with test_directory() as tmp:
            lifecycle = Lifecycle(tmp, 'synthetic', 'test')
            fixture = test_full_lifecycle.FullCycleTests()
            frame = fixture.frame()
            lifecycle.ingest(frame, fixture.rules(frame))
            with patch('ha_model_lifecycle.train_models', return_value=(
                {'model_id':'fixture', 'optimizer_converged':False, 'training_warnings':['not converged']},
                {'normal_holdout_alert_fraction':{'or':0.0}})):
                report = lifecycle.maybe_train('2026-02-01')
            self.assertEqual(report['reason'], 'training_warnings')
            self.assertFalse((Path(tmp)/'active.json').exists())

    def test_promotion_preserves_existing_reason_and_score(self):
        rules = pd.DataFrame({'window_end':['a'], 'level':['attention'], 'risk_score':[80], 'reasons':['door rule']})
        models = pd.DataFrame({'window_end':['a'], 'model_status':['shadow'], 'ae_level':['risk'], 'if_level':['risk']})
        features = rules[['window_end']].assign(fridge_door_open_count_1h=2)
        result = combine(rules, models, 'hybrid', features).iloc[0]
        self.assertEqual(result['risk_score'], 80)
        self.assertIn('door rule', result['reasons'])


if __name__ == '__main__':
    unittest.main()
