from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report_data import DEVICES, hourly_event_counts, scenario_counts, standardized_matrix


def event(entity, at, kind='state_changed_event'):
    return {'entity_id': entity, 'event_time': at, 'record_type': kind}


class ReportDataTests(unittest.TestCase):
    def test_dishwasher_is_not_washer(self):
        result = hourly_event_counts([
            event('sensor.test_dishwasher_operation_state', '2026-01-06T20:10:00+09:00'),
            event('sensor.test_washer_operation_state', '2026-01-06T20:20:00+09:00'),
        ], ['2026-01-06 21:00:00'])
        self.assertEqual(result[DEVICES.index('dishwasher')], [1])
        self.assertEqual(result[DEVICES.index('washer')], [1])

    def test_event_is_counted_at_the_following_feature_endpoint(self):
        result = hourly_event_counts([event('binary_sensor.test_fridge_door', '2026-01-06T06:10:00+09:00')],
                                     ['2026-01-06 06:00:00', '2026-01-06 07:00:00'])
        self.assertEqual(result[0], [0, 1])

    def test_window_is_open_on_left_and_closed_on_right(self):
        result = hourly_event_counts([
            event('binary_sensor.test_fridge_door', '2026-01-06T05:00:00+09:00'),
            event('binary_sensor.test_fridge_door', '2026-01-06T06:00:00+09:00'),
        ], ['2026-01-06 06:00:00'])
        self.assertEqual(result[0], [1])

    def test_utc_and_korean_time_refer_to_the_same_bin(self):
        result = hourly_event_counts([event('binary_sensor.test_fridge_door', '2026-01-05T21:10:00Z')],
                                     ['2026-01-06 07:00:00'])
        self.assertEqual(result[0], [1])

    def test_snapshot_is_not_a_state_change(self):
        result = hourly_event_counts([event('binary_sensor.test_fridge_door', '2026-01-06 06:30:00', 'state_snapshot')],
                                     ['2026-01-06 07:00:00'])
        self.assertEqual(sum(map(sum, result)), 0)

    def test_bad_time_grid_is_rejected(self):
        with self.assertRaises(ValueError):
            hourly_event_counts([], ['2026-01-06 06:00:00', '2026-01-06 08:00:00'])

    def test_stored_training_scaler_is_applied_without_refitting(self):
        self.assertEqual(standardized_matrix([{'a': 7, 'b': 1}], ['a', 'b'], [3, 3], [2, 1]), [[2, -2]])

    def test_nonfinite_or_bad_scaler_is_rejected(self):
        for value, scale in [('nan', [1]), (1, [0])]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                standardized_matrix([{'a': value}], ['a'], [0], scale)

    def test_scenario_outcomes_include_normal_and_unavailable(self):
        got = scenario_counts([{'family': 'sensor_fault', 'guarded_max_level': 'unavailable'},
                               {'family': 'benign_context', 'guarded_max_level': 'normal'}])
        self.assertEqual(got['total'], 2)
        self.assertEqual(got['levels'], {'normal': 1, 'attention': 0, 'risk': 0, 'unavailable': 1})

    def test_unknown_decision_is_not_silently_normal(self):
        with self.assertRaises(ValueError):
            scenario_counts([{'family': 'sensor_fault', 'guarded_max_level': 'invalid'}])


if __name__ == '__main__':
    unittest.main()
