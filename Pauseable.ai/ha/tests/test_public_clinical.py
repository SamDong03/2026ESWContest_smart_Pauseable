from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
import uuid
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ha_anomaly_models import score_frame
from ha_model_lifecycle import Lifecycle
from public_clinical_data import (checked_archive, tihm_day_features, temporal_split,
                                  casas_session, participant_split, miratar_sensor_days,
                                  read_miratar, TIHM_FEATURES, CASAS_FEATURES)
from public_clinical_models import fit_score, event_overlap
from run_public_clinical_benchmark import cohort_metrics


@contextmanager
def test_directory():
    root = Path(__file__).resolve().parents[1] / 'outputs/test_runs' / uuid.uuid4().hex
    root.mkdir(parents=True)
    yield root


def days(n=90):
    return pd.DataFrame({'dataset': 'tihm', 'source_type': 'public', 'subject_id': 'p1',
                         'day': pd.date_range('2020-01-01', periods=n, freq='D'),
                         'events_kitchen': np.arange(n) % 17 + 1})


def cohort():
    rows = []
    for diagnosis in range(1, 11):
        for i in range(30):
            rows.append({'dataset': 'casas', 'source_type': 'public', 'subject_id': f'{diagnosis}_{i}',
                         'diagnosis': diagnosis, **{c: i % 7 + 1 for c in CASAS_FEATURES}})
    return pd.DataFrame(rows)


class ClinicalTests(unittest.TestCase):
    def test_zip_traversal_rejected(self):
        with test_directory() as root:
            path = Path(root) / 'bad.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('../outside.csv', 'x')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                checked_archive(path)

    def test_tihm_unknown_not_negative_and_no_fake_days(self):
        activity = pd.DataFrame({'patient_id': ['p1'] * 3, 'location_name': ['Kitchen'] * 3,
                                 'date': ['2020-01-01 03:00', '2020-01-01 13:00', '2020-01-03 14:00']})
        labels = pd.DataFrame({'patient_id': ['p1'], 'date': ['2020-01-03 16:00'], 'type': ['Agitation']})
        data, _ = tihm_day_features(activity, labels)
        self.assertEqual(len(data), 2)
        self.assertEqual(list(data.label_status), ['unknown', 'event_recorded'])
        self.assertFalse(data.coverage_verified.any())
        self.assertEqual(data.night_event_fraction.iloc[0], .5)
        self.assertNotIn('label_status', TIHM_FEATURES)

    def test_tihm_rejects_bad_timestamp(self):
        with self.assertRaises(ValueError):
            tihm_day_features(pd.DataFrame({'patient_id': ['p'], 'location_name': ['Kitchen'], 'date': ['bad']}),
                              pd.DataFrame(columns=['patient_id', 'date', 'type']))

    def test_temporal_gap_boundary_and_event_exclusion(self):
        data = days()
        labels = pd.DataFrame({'patient_id': ['p1'], 'day': [pd.Timestamp('2020-01-20')]})
        a, b, c = temporal_split(data, labels)
        self.assertGreater((b.day.min() - a.day.max()).days, 1)
        self.assertGreater((c.day.min() - b.day.max()).days, 1)
        self.assertFalse(a.day.between('2020-01-19', '2020-01-21').any())
        self.assertNotIn(data.day.min(), list(a.day))
        self.assertNotIn(data.day.max(), list(c.day))

    def test_temporal_rejects_mixed_and_duplicate_subjects(self):
        data = days()
        with self.assertRaises(ValueError):
            temporal_split(pd.concat([data, data.iloc[:1]]))
        data.loc[0, 'subject_id'] = 'other'
        with self.assertRaises(ValueError):
            temporal_split(data)

    def test_participant_disjoint_and_reference_only(self):
        a, b, c = participant_split(cohort())
        self.assertTrue(a.diagnosis.isin([4, 5]).all())
        self.assertTrue(b.diagnosis.isin([4, 5]).all())
        self.assertTrue(c.diagnosis.isin([1, 2, 4, 5]).all())
        self.assertFalse(set(a.subject_id) & set(c.subject_id))
        self.assertFalse(set(b.subject_id) & set(c.subject_id))
        self.assertEqual(set(a.subject_id), set(participant_split(cohort().sample(frac=1, random_state=7))[0].subject_id))

    def test_casas_no_testing_not_zero_features(self):
        with self.assertRaisesRegex(ValueError, 'No testing'):
            casas_session('No testing\n')

    def test_casas_no_invented_dates_and_ignores_power_units(self):
        text = '\n'.join(f'12:{i:02d}:00.0 M001 ON' for i in range(21)) + '\n12:21:00 P001 9999'
        values, quality = casas_session(text)
        self.assertEqual(values['motion_on_count'], 21)
        self.assertEqual(values['session_minutes'], 20)
        self.assertEqual(quality['ignored_non_MDI_rows'], 1)
        self.assertNotIn('window_end', values)

    def test_casas_rejects_clock_reset(self):
        text = '\n'.join(f'12:{i:02d}:00 M001 ON' for i in range(21)) + '\n11:00:00 M001 OFF'
        with self.assertRaisesRegex(ValueError, 'Clock reset'):
            casas_session(text)

    def test_miratar_missing_days_not_filled_and_duplicate_minutes_retained(self):
        frame = pd.DataFrame({'time': ['2020-01-01 12:00', '2020-01-01 12:00', '2020-01-03 14:00'], 'count': [0, 1, 1]})
        data = miratar_sensor_days(frame, 'kitchen')
        self.assertEqual(len(data), 2)
        self.assertEqual(data.sensor_kitchen_record_count.iloc[0], 2)
        self.assertEqual(data.sensor_kitchen_recorded_minutes.iloc[0], 1)
        self.assertEqual(data.sensor_kitchen_one_fraction.iloc[0], .5)
        frame['count'] = frame['count'].astype(float)
        frame.loc[0, 'count'] = 29.5
        with self.assertRaises(ValueError):
            miratar_sensor_days(frame, 'kitchen')

    def test_positive_only_evaluation_does_not_fabricate_specificity(self):
        scored = days(2)
        for model in ['if', 'ae', 'either', 'both']:
            scored[model + '_alert'] = [True, False]
        labels = pd.DataFrame({'patient_id': ['p1', 'p1'], 'day': [scored.day.iloc[0], pd.Timestamp('2020-03-01')], 'type': 'Agitation'})
        report = event_overlap(scored, labels)
        self.assertIsNone(report['specificity'])
        self.assertIsNone(report['roc_auc'])
        self.assertEqual(report['by_event_type']['Agitation']['scored_holdout_event_days'], 1)
        self.assertEqual(report['by_event_type']['Agitation']['unscored_event_days'], 1)

    def test_miratar_records_missing_time_exclusion(self):
        with test_directory() as root:
            path = root / 'miratar_fixture.zip'
            with zipfile.ZipFile(path, 'w') as z:
                for kind, sensor in [('Door', 'FRONT_DOOR'), ('Motion', 'BATHROOM'), ('Motion', 'BEDROOM'),
                                     ('Motion', 'KITCHEN'), ('Motion', 'LIVING_ROOM')]:
                    text = 'time,count\n2020-01-01 12:00,1\n2020-01-02 12:00,0\n'
                    if sensor == 'KITCHEN':
                        text += ',1\n'
                    z.writestr(f'Database of sensors in smart homes/{kind}_Sensor/{sensor}_M01.csv', text)
            features, quality = read_miratar(path)
            self.assertEqual(len(features), 2)
            self.assertEqual(sum(x['excluded_missing_time_or_value'] for x in quality['csv_inventory']), 1)
            self.assertFalse(features.coverage_verified.any())

    def test_cognitive_labels_not_combined_or_other_medical_used_as_negative(self):
        scores = pd.DataFrame({'diagnosis': [1, 2, 4, 6]})
        for model in ['if', 'ae', 'either', 'both']:
            scores[model + '_alert'] = [True, False, False, True]
        scores['if_score'], scores['ae_score'] = [2, 0, 1, 3], [2, 0, 1, 3]
        report = cohort_metrics(scores)
        self.assertEqual(report['dementia']['positive_subjects'], 1)
        self.assertEqual(report['mci']['positive_subjects'], 1)
        self.assertEqual(report['dementia']['heldout_reference_subjects'], 1)
        self.assertEqual(report['dementia']['if']['roc_auc'], 1.0)
        self.assertEqual(report['mci']['if']['roc_auc'], 0.0)

    def test_fit_rejects_label_leakage_and_identity_overlap(self):
        a, b, c = temporal_split(days())
        with test_directory() as root:
            with self.assertRaisesRegex(ValueError, 'sensor features'):
                fit_score(a, b, c, ['diagnosis'], root, basis='fixture')
            with self.assertRaisesRegex(ValueError, 'overlap'):
                fit_score(a, b, a, ['events_kitchen'], root, basis='fixture')

    def test_train_only_scaler_threshold_and_live_bundle_rejection(self):
        a, b, c = temporal_split(days())
        with test_directory() as root:
            first = Path(root) / 'first'
            _, m1 = fit_score(a, b, c, ['events_kitchen'], first, basis='fixture')
            changed = c.copy()
            changed['events_kitchen'] *= 1000
            _, m2 = fit_score(a, b, changed, ['events_kitchen'], Path(root) / 'second', basis='fixture')
            self.assertEqual(m1['scaler_mean'], m2['scaler_mean'])
            self.assertEqual(m1['thresholds_95_calibration_only'], m2['thresholds_95_calibration_only'])
            self.assertFalse(m1['production_eligible'])
            self.assertAlmostEqual(m1['scaler_mean'][0], np.log1p(a.events_kitchen).mean())
            scored = score_frame(pd.DataFrame({'window_end': ['2020-01-01']}), first)
            self.assertFalse(scored.model_status.eq('shadow').any())
            with self.assertRaises(ValueError):
                Lifecycle(Path(root) / 'live', 'public', 'p1')


if __name__ == '__main__':
    unittest.main()
