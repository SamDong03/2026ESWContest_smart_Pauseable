from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from ha_alert_delivery import alert_score, deliver_transition, load_state, model_version
from ha_anomaly_models import sha256
from ha_decision_delivery import SCHEMA, build_payload, dispatch
from ha_model_lifecycle import Lifecycle, atomic_json
import test_full_lifecycle
from validate_repetitive_mqtt_payload import payload_validator


class DeliveryTests(unittest.TestCase):
    now = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)

    def payload(self, identity='one'):
        return {'event_id': identity, 'occurred_at': self.now.isoformat()}

    def deliver(self, path, level, sender, **options):
        return deliver_transition(path, level, lambda: self.payload('alert'),
                                  lambda: self.payload('clear'), sender, now=self.now, **options)

    def test_escalation_and_unknown_do_not_rearm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            sent = []
            self.assertEqual(self.deliver(path, 'attention', sent.append)['status'], 'published')
            self.assertEqual(self.deliver(path, 'risk', sent.append)['status'], 'published')
            self.assertEqual(self.deliver(path, 'unknown', sent.append)['status'], 'unknown_held')
            self.assertEqual(self.deliver(path, 'attention', sent.append)['status'], 'suppressed')
            self.assertEqual(self.deliver(path, 'risk', sent.append)['status'], 'suppressed')
            self.assertEqual(len(sent), 2)
            self.deliver(path, 'normal', sent.append)
            self.assertFalse(load_state(path)['active'])
            self.assertEqual(self.deliver(path, 'attention', sent.append)['status'], 'published')

    def test_publish_failure_restart_reuses_event_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            with self.assertRaises(RuntimeError):
                self.deliver(path, 'risk', Mock(side_effect=RuntimeError('no ACK')))
            self.assertFalse(load_state(path)['active'])
            saved = load_state(path)['pending']['payload']
            sender = Mock()

            deliver_transition(path, 'risk', Mock(side_effect=AssertionError('new ID')),
                               Mock(), sender, now=self.now)
            sender.assert_called_once_with(saved)
            self.assertTrue(load_state(path)['active'])
            self.assertNotIn('pending', load_state(path))

    def test_expired_retry_is_not_restamped_or_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            with self.assertRaises(RuntimeError):
                self.deliver(path, 'risk', Mock(side_effect=RuntimeError()))
            sender = Mock()
            deliver_transition(path, 'unknown', Mock(), Mock(), sender, now=self.now + timedelta(minutes=5))
            sender.assert_not_called()
            self.assertEqual(load_state(path)['last_discarded_event_id'], 'alert')

    def test_normal_reconciles_uncertain_delivery_without_replaying_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            with self.assertRaises(RuntimeError):
                self.deliver(path, 'risk', Mock(side_effect=RuntimeError()))
            sender = Mock()
            self.deliver(path, 'normal', sender)
            sender.assert_called_once_with(self.payload('clear'))

    def test_dry_run_never_commits_live_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            self.deliver(path, 'risk', Mock(), dry_run=True)
            self.assertFalse(path.exists())

    def test_corrupt_state_does_not_silently_rearm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            for bad in ('{broken', '[]', '{"active":"false"}'):
                path.write_text(bad)
                with self.assertRaises((ValueError, TypeError)):
                    self.deliver(path, 'risk', Mock())

    def test_invalid_score_cannot_default_to_alert(self):
        for value in (float('nan'), float('inf'), -1, 101, 3.5):
            with self.assertRaises(ValueError):
                alert_score({'level': 'risk', 'risk_score': value})
        with self.assertRaises(ValueError):
            alert_score({'risk_score': 35})
        self.assertEqual(model_version({'model_id': 'actual'}, SimpleNamespace(model_version='old')), 'actual')

    def row(self):
        return {'window_end': self.now.isoformat(), 'level': 'risk', 'risk_score': 70,
                'history_complete': 1, 'primary_pattern': 'fridge_repeated_check', 'model_id': 'current'}

    def test_current_decision_schema_and_no_historical_action(self):
        row = self.row()
        payload = build_payload(row, 'byunwoojin', 'pi5-home-01')
        payload_validator(SCHEMA).validate(payload)
        self.assertEqual(payload['model_version'], 'current')
        with tempfile.TemporaryDirectory() as tmp:
            sender = Mock()
            path = Path(tmp) / 'state.json'
            self.assertEqual(dispatch(row, path, sender, now=self.now + timedelta(minutes=5))['status'], 'stale_or_future')
            self.assertEqual(dispatch(row, path, sender, now=self.now - timedelta(seconds=1))['status'], 'stale_or_future')
            self.assertEqual(dispatch({**row, 'history_complete': 0}, path, sender, now=self.now)['status'], 'incomplete_observation_held')
            sender.assert_not_called()

    def test_date_time_format_is_actually_checked(self):
        payload = build_payload(self.row(), 'byunwoojin', 'pi5-home-01')
        payload['occurred_at'] = 'not-a-dateZ'
        self.assertTrue(list(payload_validator(SCHEMA).iter_errors(payload)))

    def test_bundled_contract_matches_repository_contract(self):
        for parent in (BASE, *BASE.parents):
            canonical = parent / 'Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json'
            if canonical.exists():
                self.assertEqual(json.loads(SCHEMA.read_text(encoding='utf-8')),
                                 json.loads(canonical.read_text(encoding='utf-8')))
                return
        self.skipTest('Repository contract not mounted; semantic equality is checked when packaging')


class RetrainingTests(unittest.TestCase):
    def candidate(self, training_path, model_dir, source, household, *args, **kwargs):
        model_dir.mkdir(parents=True)
        (model_dir / 'isolation_forest.joblib').write_bytes(b'fixture-not-for-inference')
        manifest = {'model_id': model_dir.parent.name, 'forest_sha256': sha256(model_dir / 'isolation_forest.joblib'),
                    'training_warnings': [], 'optimizer_converged': True}
        atomic_json(model_dir / 'manifest.json', manifest)
        return manifest, {'normal_holdout_alert_fraction': {'or': 0.01}}

    def setup_life(self, root):
        life = Lifecycle(root, 'synthetic', 'test', retrain_days=7)
        fixture = test_full_lifecycle.FullCycleTests()
        frame = fixture.frame(30)
        life.ingest(frame, fixture.rules(frame))
        with patch('ha_model_lifecycle.train_models', side_effect=self.candidate), \
             patch('ha_model_lifecycle.score_frame', return_value=pd.DataFrame({'model_status': ['shadow']})):
            self.assertEqual(life.maybe_train('2026-01-31')['status'], 'active')
        return life, fixture

    def test_cadence_and_new_data_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            life, fixture = self.setup_life(tmp)
            with patch('ha_model_lifecycle.train_models') as train:
                self.assertEqual(life.maybe_train('2026-02-01')['retraining'], 'not_due')
                self.assertEqual(life.maybe_train('2026-02-08')['retraining'], 'waiting_for_new_data')
                train.assert_not_called()

    def test_candidate_failure_and_gate_rejection_retain_active(self):
        for mode in ('exception', 'gate'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                life, fixture = self.setup_life(tmp)
                original = (Path(tmp) / 'active.json').read_bytes()
                frame = fixture.frame(40)
                life.ingest(frame, fixture.rules(frame))
                failure = Mock(side_effect=RuntimeError('failure')) if mode == 'exception' else Mock(
                    return_value=({'model_id': 'bad'}, {'normal_holdout_alert_fraction': {'or': .5}}))
                with patch('ha_model_lifecycle.train_models', failure), \
                     patch('ha_model_lifecycle.score_frame', return_value=pd.DataFrame({'model_status': ['shadow']})):
                    status = life.maybe_train('2026-02-11')
                self.assertIn(status['status'], ('training_failed', 'rejected'))
                self.assertEqual((Path(tmp) / 'active.json').read_bytes(), original)
                self.assertIsNotNone(life.active_dir())
                self.assertEqual(life.maybe_train('2026-02-11')['status'], 'retry_deferred')

    def test_successful_refresh_and_explicit_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            life, fixture = self.setup_life(tmp)
            old = life.active_dir()
            frame = fixture.frame(40)
            life.ingest(frame, fixture.rules(frame))
            with patch('ha_model_lifecycle.train_models', side_effect=self.candidate), \
                 patch('ha_model_lifecycle.score_frame', return_value=pd.DataFrame({'model_status': ['shadow']})):
                self.assertEqual(life.maybe_train('2026-02-11')['status'], 'active')
            self.assertNotEqual(life.active_dir(), old)
            with self.assertRaises(ValueError):
                life.rollback('')
            self.assertEqual(life.rollback('manual review')['status'], 'rolled_back')
            self.assertEqual(life.active_dir(), old)


if __name__ == '__main__':
    unittest.main()
