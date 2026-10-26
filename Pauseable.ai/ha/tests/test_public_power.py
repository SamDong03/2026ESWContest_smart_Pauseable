from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fetch_public_power import fetch
from power_features import PowerConfig, build_power_features, detect_sessions, normalize_power, integral_at, sample_support
from prepare_public_power import prepare, read_power


@contextmanager
def test_directory():
    path = Path(__file__).resolve().parents[1] / 'outputs/test_runs' / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path


def config(**kwargs):
    return PowerConfig(**{'on_power_threshold': 100, 'min_on_seconds': 12,
                          'min_off_seconds': 12, 'max_power_w': 4000, **kwargs})


def frame(seconds, watts):
    return pd.DataFrame({'timestamp': pd.to_datetime(seconds, unit='s', utc=True), 'power_w': watts})


class PowerTests(unittest.TestCase):
    def test_confirmed_start_and_end_do_not_backdate(self):
        sessions = detect_sessions(np.arange(0, 49, 6), np.array([0, 200, 200, 200, 0, 0, 0, 0, 0]), config())
        item = sessions.iloc[0]
        self.assertEqual((item.start_time, item.start_detected_at), (6, 18))
        self.assertEqual((item.end_time, item.end_detected_at, item.duration_seconds), (24, 36, 18))

    def test_initial_on_is_not_a_start(self):
        rows = detect_sessions(np.arange(0, 61, 6), np.full(11, 200), config())
        self.assertTrue(rows.empty)

    def test_brief_off_is_not_a_second_cycle(self):
        rows = detect_sessions(np.arange(0, 55, 6), np.array([0, 200, 200, 200, 0, 200, 200, 0, 0, 0]), config())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0].status, 'complete')

    def test_short_spike_not_confirmed_while_off(self):
        rows = detect_sessions(np.arange(0, 61, 6), np.array([0, 200] + [0] * 9), config(min_on_seconds=18, min_off_seconds=30))
        self.assertTrue(rows.empty)

    def test_gap_censors_session_without_fake_completion(self):
        rows = detect_sessions(np.array([0, 6, 12, 18, 100, 106, 112]), np.array([0, 200, 200, 200, 200, 200, 0]), config())
        self.assertEqual(rows.iloc[0].status, 'censored_gap')
        self.assertTrue(pd.isna(rows.iloc[0].duration_seconds))

    def test_session_duration_is_bounded_without_fake_completion(self):
        rows = detect_sessions(np.arange(0, 121, 6), np.array([0] + [200] * 20), config(max_session_seconds=60))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0].status, 'censored_max_duration')
        self.assertTrue(pd.isna(rows.iloc[0].end_detected_at))

    def test_integral_support_does_not_use_future_arrival(self):
        query = np.array([5., 10., 20.])
        past = np.array([0.])
        future = np.array([0., 25.])
        expected = integral_at(query, past, sample_support(past, np.array([True]), config()), np.array([100.]))
        actual = integral_at(query, future, sample_support(future, np.array([True, True]), config()), np.array([100., 200.]))
        np.testing.assert_allclose(expected, [500, 600, 600])
        np.testing.assert_allclose(actual, expected)

    def test_less_than_one_step_yields_empty_features(self):
        features, _, quality = build_power_features(frame([1, 7, 13], [0, 0, 0]), config())
        self.assertTrue(features.empty)
        self.assertEqual(quality['usable_feature_rows'], 0)

    def test_invalid_power_and_duplicate_conflict_remain_missing(self):
        data, _, quality = normalize_power(frame([0, 6, 6, 12, 18, 24], [0, 100, 200, -1, 9999, 0]), config())
        self.assertEqual(quality['duplicate_rows'], 1)
        self.assertEqual(int(data.power_w.isna().sum()), 3)

    def test_energy_integrates_watts_to_wh(self):
        features, _, _ = build_power_features(frame(np.arange(0, 10801, 6), np.full(1801, 120)), config())
        valid = features.loc[features.history_complete.eq(1)]
        self.assertAlmostEqual(valid.iloc[-1].energy_wh_2h, 240)
        self.assertAlmostEqual(valid.iloc[-1].above_threshold_minutes_2h, 120)
        self.assertEqual(valid.iloc[-1].confirmed_starts_2h, 0)

    def test_long_gap_not_filled_as_observed(self):
        features, _, _ = build_power_features(frame([0, 6, 7200, 7206], [1000, 1000, 0, 0]), config())
        self.assertTrue(features.history_complete.eq(0).all())
        self.assertTrue(features.energy_wh_2h.isna().all())

    def test_features_causal_under_future_extension(self):
        seconds = np.arange(0, 18001, 6)
        watts = np.where((seconds % 900) < 300, 300, 0)
        full, _, _ = build_power_features(frame(seconds, watts), config())
        prefix, _, _ = build_power_features(frame(seconds[seconds <= 12000], watts[seconds <= 12000]), config())
        pd.testing.assert_frame_equal(prefix.reset_index(drop=True), full.iloc[:len(prefix)].reset_index(drop=True))

    def test_local_clock_and_dst_keep_unique_utc_windows(self):
        times = pd.date_range('2026-10-25T00:00:00Z', periods=2401, freq='6s')
        features, _, _ = build_power_features(pd.DataFrame({'timestamp': times, 'power_w': 120}), config())
        self.assertFalse(features.window_end.duplicated().any())

    def test_configuration_rejects_nan_and_impossible_durations(self):
        for item in [config(on_power_threshold=float('nan')), config(max_gap_seconds=1), config(max_session_seconds=6)]:
            with self.assertRaises(ValueError):
                item.validate()

    def test_refit_issues_are_missing_not_zero(self):
        with test_directory() as tmp:
            path = tmp / 'refit.csv'
            pd.DataFrame({'Unix': [100, 108, 116], 'Appliance5': [200, 300, 0], 'Issues': [0, 1, 0]}).to_csv(path, index=False)
            data, quality = read_power(path, 'refit', power_column='Appliance5')
            self.assertTrue(pd.isna(data.power_w.iloc[1]))
            self.assertEqual(quality['flagged_rows'], 1)

    def test_source_and_provenance_guard(self):
        with test_directory() as tmp:
            with self.assertRaisesRegex(ValueError, 'relabelled'):
                prepare(tmp / 'x', tmp / 'out', 'ukdale', config(), household_id='h', appliance='a',
                        citation='c', license_name='l', parameter_basis='p', source_type='local')

    def test_ukdale_rejects_mains_three_column(self):
        with test_directory() as tmp:
            path = tmp / 'mains.dat'
            path.write_text('100 200 230\n106 210 230\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_power(path, 'ukdale')

    def test_power_csv_rejects_naive_times(self):
        with test_directory() as tmp:
            path = tmp / 'p.csv'
            pd.DataFrame({'timestamp': ['2026-01-01 00:00', '2026-01-01 00:01'], 'power_w': [0, 100]}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, 'offset'):
                read_power(path, 'power_csv')

    def test_download_rejects_html_and_records_prefix(self):
        class Response:
            headers = {'Content-Type': 'text/plain'}
            url = 'https://example.test/power.dat'
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, n): return b'1 2\n3 4\n5 6\n'[:n]
        with test_directory() as tmp:
            with patch('fetch_public_power.urlopen', return_value=Response()):
                meta = fetch(Response.url, tmp / 'p.dat', max_bytes=6, citation='fixture', license_name='fixture', partial=True)
                self.assertTrue(meta['partial'])
                self.assertEqual((tmp / 'p.dat').read_bytes(), b'1 2\n')
            response = Response()
            response.headers = {'Content-Type': 'text/html'}
            with patch('fetch_public_power.urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    fetch(response.url, tmp / 'bad.dat', max_bytes=100, citation='fixture', license_name='fixture')


if __name__ == '__main__':
    unittest.main()
