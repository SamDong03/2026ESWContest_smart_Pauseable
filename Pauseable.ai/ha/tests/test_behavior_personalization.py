from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from jsonschema import ValidationError

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from ha_behavior_feedback import FeedbackStore, queue_review
from ha_alert_delivery import load_state
from ha_decision_delivery import build_payload, dispatch
from ha_model_lifecycle import Lifecycle, SCHEMA, atomic_json, combine
from ha_personal_routine import PersonalRoutine, fit_routine
from ha_repetition_policy import observed_patterns
from make_ha_features import FEATURE_COLUMNS
import receive_ha_behavior_feedback


def feature(at, **changes):
    row = {name: 0 for name in FEATURE_COLUMNS}
    row.update(window_end=str(pd.Timestamp(at)), source_type='local', household_id='home', schema_version=SCHEMA,
               history_complete=1, hour=pd.Timestamp(at).hour)
    row.update(changes)
    return row


FRIDGE = dict(fridge_door_open_count_10m=4, fridge_door_open_count_30m=6, fridge_door_open_count_1h=6,
              fridge_door_toggle_count_10m=8, fridge_door_toggle_count_30m=12, fridge_door_toggle_count_1h=12)


def rules(frame, level='risk', pattern='fridge_repeated_check'):
    return frame[['window_end']].assign(level=level, risk_score=70 if level == 'risk' else 0,
                                      primary_pattern=pattern, reasons='Fixture rule, not a clinical label')


def models(frame, ae='normal', forest='normal'):
    return frame[['window_end']].assign(model_status='shadow', model_source='local', model_id='fixture',
                                      ae_level=ae, if_level=forest)


def review(start, end=None, identity='review-1', label='normal', at=None, **changes):
    start = pd.Timestamp(start)
    end = pd.Timestamp(end or start)
    def utc(stamp):
        return stamp.tz_localize('Asia/Seoul').tz_convert('UTC').isoformat()
    message = {'contract_version': '1.0', 'feedback_id': identity, 'source_type': 'local', 'household_id': 'home',
               'patient_id': 'byunwoojin', 'device_id': 'pi5-home-01', 'review_kind': 'behavior_label',
               'label': label, 'reviewer_id': 'guardian-test', 'reviewed_at': utc(pd.Timestamp(at) if at else end + pd.Timedelta(minutes=1)),
               'period': {'start': utc(start), 'end': utc(end)}}
    message.update(changes)
    return message


class RepetitionGuardTests(unittest.TestCase):
    def test_single_use_cannot_become_repetitive_even_with_both_models_risk(self):
        for changes, pattern in [
                (dict(fridge_door_open_count_1h=1, fridge_door_toggle_count_1h=2), 'fridge_repeated_check'),
                (dict(washer_start_count_2h=1, washer_operation_change_count_30m=8, washer_operation_change_count_1h=8), 'washer_repeated_operation'),
                (dict(microwave_start_count_1h=1, microwave_operation_change_count_30m=5), 'microwave_repeated_use'),
                (dict(air_purifier_power_toggle_count_30m=2), 'air_purifier_repeated_control')]:
            with self.subTest(pattern=pattern):
                frame = pd.DataFrame([feature('2026-01-01 12:00', **changes)])
                result = combine(rules(frame, pattern=pattern), models(frame, 'risk', 'risk'), 'hybrid', frame).iloc[0]
                self.assertEqual(result['level'], 'normal')
                self.assertTrue(result['model_only_anomaly_held'])
                self.assertEqual(result['raw_rule_level'], 'risk')

    def test_no_features_does_not_allow_model_only_behavior_claim(self):
        frame = pd.DataFrame([feature('2026-01-01 12:00')])
        self.assertEqual(combine(rules(frame, 'normal'), models(frame, 'risk', 'risk'), 'hybrid').iloc[0]['level'], 'normal')

    def test_repetition_uses_physical_pattern_and_model_agreement(self):
        frame = pd.DataFrame([feature('2026-01-01 12:00', fridge_door_open_count_1h=2)])
        for ae, forest, expected in [('risk', 'normal', 'attention'), ('risk', 'risk', 'risk')]:
            result = combine(rules(frame, 'normal'), models(frame, ae, forest), 'hybrid', frame).iloc[0]
            self.assertEqual(result['level'], expected)
            self.assertEqual(result['primary_pattern'], 'fridge_repeated_check')

    def test_an_unrelated_repeat_does_not_validate_a_single_microwave_use(self):
        frame = pd.DataFrame([feature('2026-01-01 12:00', fridge_door_open_count_1h=2, microwave_start_count_1h=1)])
        result = combine(rules(frame, pattern='microwave_repeated_use'), models(frame), 'shadow', frame).iloc[0]
        self.assertEqual(result['level'], 'normal')

    def test_done_then_restart_is_real_repeat_evidence(self):
        self.assertIn('washer_repeated_operation', observed_patterns(feature('2026-01-01', washer_done_to_restart_count_2h=1)))


class DeliveryReviewEpochTests(unittest.TestCase):
    now = datetime(2026, 1, 6, 3, 30, tzinfo=timezone.utc)

    def row(self, revision=0, level='risk'):
        return {**feature('2026-01-06 12:30', **FRIDGE), 'level': level, 'risk_score': 70,
                'primary_pattern': 'fridge_repeated_check', 'behavior_review_revision': revision}

    def pending(self, path, store):
        with self.assertRaises(RuntimeError):
            dispatch(self.row(), path, Mock(side_effect=RuntimeError('ACK lost')), now=self.now, review_store=store)
        return load_state(path)['pending']['payload']['event_id']

    def test_unchanged_review_retries_original_event(self):
        with tempfile.TemporaryDirectory() as root:
            path, store = Path(root) / 'delivery.json', Mock()
            store.revision.return_value = 0
            old = self.pending(path, store)
            sent = []
            self.assertEqual(dispatch(self.row(), path, sent.append, now=self.now, review_store=store)['status'], 'retried')
            self.assertEqual(sent[0]['event_id'], old)

    def test_changed_review_replaces_pending_alert_not_replays_it(self):
        with tempfile.TemporaryDirectory() as root:
            path, store = Path(root) / 'delivery.json', Mock()
            store.revision.return_value = 0
            old = self.pending(path, store)
            store.revision.return_value = 1
            sent = []
            result = dispatch(self.row(1), path, sent.append, now=self.now, review_store=store)
            self.assertEqual(result['status'], 'published')
            self.assertNotEqual(sent[0]['event_id'], old)
            self.assertEqual(load_state(path)['last_discarded_event_id'], old)
            self.assertEqual(load_state(path)['discard_reason'], 'review_context_changed')

    def test_changed_review_normal_sends_clear_not_old_alert(self):
        with tempfile.TemporaryDirectory() as root:
            path, store = Path(root) / 'delivery.json', Mock()
            store.revision.return_value = 0
            old = self.pending(path, store)
            store.revision.return_value = 1
            sent = []
            dispatch(self.row(1, 'normal'), path, sent.append, now=self.now, review_store=store)
            self.assertNotEqual(sent[0]['event_id'], old)
            self.assertEqual(sent[0]['behavior'], 'normal')

    def test_changed_review_unknown_preserves_possible_open_episode(self):
        with tempfile.TemporaryDirectory() as root:
            path, store = Path(root) / 'delivery.json', Mock()
            store.revision.return_value = 0
            self.pending(path, store)
            store.revision.return_value = 1
            sent = []
            dispatch(self.row(1, 'unknown'), path, sent.append, now=self.now, review_store=store)
            self.assertEqual(sent, [])
            self.assertTrue(load_state(path)['active'])
            dispatch(self.row(1, 'normal'), path, sent.append, now=self.now, review_store=store)
            self.assertEqual(sent[0]['behavior'], 'normal')

    def test_revision_changed_after_builder_cannot_reach_sender(self):
        with tempfile.TemporaryDirectory() as root:
            path, store, sender = Path(root) / 'delivery.json', Mock(), Mock()
            store.revision.return_value = 0
            def changed(*args):
                store.revision.return_value = 1
            with self.assertRaisesRegex(ValueError, 'review changed before delivery'):
                dispatch(self.row(), path, sender, now=self.now, review_store=store, event_callback=changed)
            sender.assert_not_called()
            self.assertEqual(load_state(path)['pending']['delivery_epoch'], 0)

    def test_old_inference_revision_is_held_without_state_change(self):
        with tempfile.TemporaryDirectory() as root:
            path, store, sender = Path(root) / 'delivery.json', Mock(), Mock()
            store.revision.return_value = 1
            self.assertEqual(dispatch(self.row(), path, sender, now=self.now, review_store=store)['status'],
                             'behavior_review_changed_held')
            sender.assert_not_called()
            self.assertFalse(path.exists())


class FeedbackTests(unittest.TestCase):
    def fixture(self, root, complete=1):
        life = Lifecycle(root, 'local', 'home')
        frame = pd.DataFrame([feature('2026-01-06 12:30', **FRIDGE, history_complete=complete)])
        life.ingest(frame, rules(frame))
        return life, frame

    def test_explicit_normal_can_admit_rule_alert_but_an_ack_cannot(self):
        with tempfile.TemporaryDirectory() as root:
            life, frame = self.fixture(root)
            with self.assertRaises(ValidationError):
                life.feedback.apply({'action': 'confirmed_safe', 'event_id': 'evt'})
            self.assertEqual(life.feedback.revision(), 0)
            life.feedback.apply(review('2026-01-06 12:30'))
            life.ingest(frame, rules(frame))
            self.assertEqual(life.feedback.history().iloc[0]['review_status'], 'reviewed_normal')

    def test_local_review_status_column_cannot_spoof_a_human_review(self):
        with tempfile.TemporaryDirectory() as root:
            life = Lifecycle(root, 'local', 'home')
            frame = pd.DataFrame([feature('2026-01-06 12:30', **FRIDGE, review_status='reviewed_normal')])
            life.ingest(frame, rules(frame))
            self.assertEqual(life.feedback.history().iloc[0]['review_status'], 'excluded')

    def test_duplicate_conflict_and_later_correction(self):
        with tempfile.TemporaryDirectory() as root:
            life, frame = self.fixture(root)
            message = review('2026-01-06 12:30')
            self.assertEqual(life.feedback.apply(message)['status'], 'applied')
            self.assertEqual(life.feedback.apply(message)['status'], 'duplicate')
            with self.assertRaisesRegex(ValueError, 'Conflicting feedback_id'):
                life.feedback.apply({**message, 'label': 'repetitive'})
            correction = review('2026-01-06 12:30', identity='review-2', label='repetitive', at='2026-01-06 13:00')
            life.feedback.apply(correction)
            late = review('2026-01-06 12:30', identity='review-late', at='2026-01-06 12:45')
            self.assertEqual(life.feedback.apply(late)['applied_rows'], 0)
            life.ingest(frame, rules(frame, 'normal'))
            self.assertEqual(life.feedback.history().iloc[0]['review_status'], 'excluded')

    def test_unsafe_review_inputs_are_rejected_without_labels(self):
        with tempfile.TemporaryDirectory() as root:
            life, _ = self.fixture(root, complete=0)
            with self.assertRaisesRegex(ValueError, 'cannot be certified normal'):
                life.feedback.apply(review('2026-01-06 12:30'))
            for message in [review('2026-01-06 12:30', household_id='other'),
                            review('2026-01-06 12:30', source_type='synthetic'),
                            review('2026-01-06 12:30', at='2026-01-06 12:00'),
                            review('2026-01-06', '2026-01-08')]:
                with self.assertRaises(ValueError):
                    life.feedback.apply(message)
            with self.assertRaisesRegex(ValueError, 'future'):
                life.feedback.apply(review('2026-01-06 12:30'), now='2026-01-06T00:00:00Z')
            self.assertTrue(life.feedback.labels().empty)

    def test_event_context_is_registered_before_send_and_can_be_reviewed(self):
        with tempfile.TemporaryDirectory() as root:
            life, frame = self.fixture(root)
            row = {**frame.iloc[0].to_dict(), **rules(frame).iloc[0].to_dict()}
            now = pd.Timestamp('2026-01-06T03:30:00Z').to_pydatetime()
            sent = []
            dispatch(row, Path(root)/'delivery.json', sent.append, now=now, event_callback=life.feedback.register_event)
            message = review('2026-01-06 12:30', event_id=sent[0]['event_id'])
            del message['period']
            self.assertEqual(life.feedback.apply(message)['applied_rows'], 1)
            with self.assertRaisesRegex(ValueError, 'Unknown event_id'):
                life.feedback.apply({**message, 'feedback_id': 'unknown', 'event_id': 'not-registered'})

    def test_inbox_separates_applied_and_invalid_documents(self):
        with tempfile.TemporaryDirectory() as root:
            life, _ = self.fixture(root)
            self.assertEqual(queue_review(root, review('2026-01-06 12:30'))['status'], 'queued_not_yet_applied')
            (Path(root)/'feedback_inbox/bad.json').write_text('{broken')
            counts = life.feedback.drain_inbox()
            self.assertEqual(counts, {'applied': 1, 'duplicate': 0, 'rejected': 1})
            self.assertTrue((Path(root)/'feedback_inbox/rejected').is_dir())
            self.assertTrue((Path(root)/'feedback_inbox_audit.jsonl').exists())

    def test_changed_label_invalidates_models_from_that_cohort(self):
        with tempfile.TemporaryDirectory() as root:
            life, _ = self.fixture(root)
            life.feedback.apply(review('2026-01-06 12:30', label='repetitive'))
            manifest = {'splits': {'train': {'start': '2026-01-01 00:00:00'}, 'test': {'end': '2026-01-30 23:00:00'}}}
            self.assertTrue(life.feedback.invalidates({'feedback_revision': 0}, manifest))
            self.assertFalse(life.feedback.invalidates({'feedback_revision': 1}, manifest))

    def test_unknown_review_does_not_become_normal_training_data(self):
        with tempfile.TemporaryDirectory() as root:
            life, frame = self.fixture(root)
            life.feedback.apply(review('2026-01-06 12:30', label='uncertain'))
            life.ingest(frame, rules(frame, 'normal'))
            self.assertEqual(life.feedback.history().iloc[0]['review_status'], 'quarantined')

    def test_event_review_is_rejected_if_the_feature_snapshot_changed(self):
        with tempfile.TemporaryDirectory() as root:
            life, frame = self.fixture(root)
            payload = build_payload({**frame.iloc[0].to_dict(), 'level': 'risk', 'risk_score': 70}, 'byunwoojin', 'pi5-home-01')
            life.feedback.register_event(payload, frame.iloc[0]['window_end'])
            changed = frame.assign(fridge_door_open_count_1h=9)
            life.ingest(changed, rules(changed))
            message = review('2026-01-06 12:30', event_id=payload['event_id'])
            del message['period']
            with self.assertRaisesRegex(ValueError, 'observations changed'):
                life.feedback.apply(message)

    def test_feedback_receiver_requires_credentials_unless_explicit_test_mode(self):
        with patch.object(sys, 'argv', ['receive', '--lifecycle-dir', 'unused']), \
                patch.dict(os.environ, {'MQTT_USER': '', 'MQTT_PASSWORD': ''}):
            with self.assertRaises(SystemExit) as error:
                receive_ha_behavior_feedback.main()
        self.assertEqual(error.exception.code, 2)


class RoutineTests(unittest.TestCase):
    def fixture(self, root):
        life = Lifecycle(root, 'local', 'home')
        rows = [feature(f'2026-01-{day:02d} {clock}', **FRIDGE) for day in (6, 13, 20) for clock in ('12:30', '13:00')]
        frame = pd.DataFrame(rows)
        life.ingest(frame, rules(frame))
        for day in (6, 13, 20):
            life.feedback.apply(review(f'2026-01-{day:02d} 12:30', f'2026-01-{day:02d} 13:00', identity=f'review-{day}'))
        return life

    def decision(self, life, row, ae='normal', forest='normal', policy='hybrid'):
        frame = pd.DataFrame([row])
        routine = life.routine_policy(row['window_end'])
        return combine(rules(frame), models(frame, ae, forest), policy, frame, routine).iloc[0]

    def test_reviewed_weekday_routine_and_both_models_can_lower_rule_alert(self):
        with tempfile.TemporaryDirectory() as root:
            life = self.fixture(root)
            result = self.decision(life, feature('2026-01-27 12:30', **FRIDGE))
            self.assertEqual(result['level'], 'normal')
            self.assertEqual(result['pre_personal_level'], 'risk')
            self.assertEqual(result['personalization_status'], 'reviewed_routine_confirmed_by_models')
            self.assertTrue((Path(root)/'routine_profile.json').exists())

    def test_novel_counts_other_weekday_other_clock_and_stale_context_are_not_cleared(self):
        with tempfile.TemporaryDirectory() as root:
            life = self.fixture(root)
            cases = [feature('2026-01-27 12:30', **{**FRIDGE, 'fridge_door_open_count_1h': 9}),
                     feature('2026-01-28 12:30', **FRIDGE), feature('2026-01-27 20:30', **FRIDGE),
                     feature('2026-02-10 12:30', **FRIDGE),
                     feature('2026-01-27 12:30', **FRIDGE, air_purifier_mode_change_count_30m=2)]
            for row in cases:
                with self.subTest(row=row):
                    self.assertEqual(self.decision(life, row)['level'], 'risk')

    def test_unavailable_or_abnormal_models_and_shadow_mode_cannot_lower_rules(self):
        with tempfile.TemporaryDirectory() as root:
            life = self.fixture(root)
            row = feature('2026-01-27 12:30', **FRIDGE)
            for ae, forest in [('risk', 'normal'), ('unavailable', 'normal'), ('normal', 'risk')]:
                self.assertEqual(self.decision(life, row, ae, forest)['level'], 'risk')
            self.assertEqual(self.decision(life, row, policy='shadow')['level'], 'risk')

    def test_protected_rules_cannot_be_waived_by_a_routine(self):
        with tempfile.TemporaryDirectory() as root:
            life = self.fixture(root)
            for extra in ({'door_lock_unlock_count_1h': 2}, {'microwave_start_count_1h': 2},
                          {'washer_done_to_restart_count_2h': 2}, {'fridge_door_open_count_10m': 12}):
                result = self.decision(life, feature('2026-01-27 12:30', **{**FRIDGE, **extra}))
                self.assertEqual(result['level'], 'risk')
                self.assertEqual(result['personalization_status'], 'protected_rule_preserved')

    def test_one_day_of_overlapping_windows_cannot_establish_a_routine(self):
        with tempfile.TemporaryDirectory() as root:
            life = Lifecycle(root, 'local', 'home')
            frame = pd.DataFrame([feature(at, **FRIDGE) for at in pd.date_range('2026-01-06 12:00', periods=180, freq='min')])
            life.ingest(frame, rules(frame))
            life.feedback.apply(review('2026-01-06 12:00', '2026-01-06 14:59'))
            self.assertFalse(life.routine_policy('2026-01-13 12:30').profile['profiles'])

    def test_profile_is_causal_and_review_changes_require_rebuilding(self):
        with tempfile.TemporaryDirectory() as root:
            life = self.fixture(root)
            profile = life.routine_policy('2026-01-27 12:30')
            frame = pd.DataFrame([feature('2026-01-20 12:30', **FRIDGE)])
            result = combine(rules(frame), models(frame), 'hybrid', frame, profile).iloc[0]
            self.assertEqual(result['level'], 'risk')
            self.assertEqual(result['personalization_status'], 'profile_not_causal')
            life.feedback.apply(review('2026-01-20 12:30', identity='corrected', label='uncertain', at='2026-01-21 12:00'))
            future = pd.DataFrame([feature('2026-01-27 12:30', **FRIDGE)])
            changed = combine(rules(future), models(future), 'hybrid', future, profile).iloc[0]
            self.assertEqual(changed['personalization_status'], 'feedback_changed_retry_next_cycle')
            self.assertEqual(changed['level'], 'risk')

    def test_all_percentile_bounds_are_checked_not_only_the_last_feature(self):
        with tempfile.TemporaryDirectory() as root:
            life = self.fixture(root)
            routine = life.routine_policy('2026-01-27 12:30')
            for profile in routine.profile['profiles'].values():
                profile['limits']['fridge_door_open_count_10m'] = 0
            frame = pd.DataFrame([feature('2026-01-27 12:30', **FRIDGE)])
            result = combine(rules(frame), models(frame), 'hybrid', frame, routine).iloc[0]
            self.assertEqual(result['level'], 'risk')

    def test_mixing_individually_normal_feature_maxima_is_not_a_known_joint_routine(self):
        with tempfile.TemporaryDirectory() as root:
            life = Lifecycle(root, 'local', 'home')
            rows = []
            for day in (6, 13, 20):
                rows.append(feature(f'2026-01-{day:02d} 12:30', **FRIDGE))
                rows.append(feature(f'2026-01-{day:02d} 13:00', **{**FRIDGE, 'fridge_door_open_count_1h': 4},
                                    washer_operation_change_count_1h=2))
            frame = pd.DataFrame(rows)
            life.ingest(frame, rules(frame))
            for day in (6, 13, 20):
                life.feedback.apply(review(f'2026-01-{day:02d} 12:30', f'2026-01-{day:02d} 13:00', identity=f'r-{day}'))
            row = feature('2026-01-27 12:30', **FRIDGE, washer_operation_change_count_1h=2)
            self.assertEqual(self.decision(life, row)['level'], 'risk')


if __name__ == '__main__':
    unittest.main()
