from pathlib import Path
import sys
import subprocess
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_baseline_models import elapsed_minutes, require_reproduction, validate_alignment, variants


class ModelComparisonTests(unittest.TestCase):
    def fixture(self, count=2, rule='normal', if_level='normal', ae_level='normal', status='shadow'):
        stamp = '2026-04-01 12:05:00'
        features = pd.DataFrame([{'window_end': stamp, 'fridge_door_open_count_10m': count}])
        rules = pd.DataFrame([{'window_end': stamp, 'level': rule,
                               'risk_score': 70 if rule == 'risk' else 0,
                               'primary_pattern': 'fridge_repeated_check', 'reasons': ''}])
        models = pd.DataFrame([{'window_end': stamp, 'model_status': status, 'model_source': 'synthetic',
                               'if_level': if_level, 'ae_level': ae_level}])
        return rules, models, features

    def test_ae_contribution_is_not_misattributed_to_if(self):
        rules, models, features = self.fixture(ae_level='risk')
        before = models.copy(deep=True)
        result = variants(rules, models, features)
        self.assertEqual([result[name].iloc[0]['level'] for name in result],
                         ['normal', 'normal', 'attention', 'attention'])
        pd.testing.assert_frame_equal(models, before)

    def test_if_contribution_is_not_misattributed_to_ae(self):
        result = variants(*self.fixture(if_level='risk'))
        self.assertEqual([result[name].iloc[0]['level'] for name in result],
                         ['normal', 'attention', 'normal', 'attention'])

    def test_learned_risk_requires_both_models(self):
        result = variants(*self.fixture(if_level='risk', ae_level='risk'))
        self.assertEqual([result[name].iloc[0]['level'] for name in result],
                         ['normal', 'attention', 'attention', 'risk'])

    def test_every_method_uses_the_same_repetition_gate(self):
        result = variants(*self.fixture(count=1, if_level='risk', ae_level='risk'))
        self.assertTrue(all(frame.iloc[0]['level'] == 'normal' for frame in result.values()))

    def test_baseline_risk_is_never_lowered_by_ablation(self):
        result = variants(*self.fixture(rule='risk'))
        self.assertTrue(all(frame.iloc[0]['level'] == 'risk' for frame in result.values()))

    def test_unavailable_model_does_not_promote_alert(self):
        result = variants(*self.fixture(if_level='risk', ae_level='risk', status='invalid_model'))
        self.assertTrue(all(frame.iloc[0]['level'] == 'normal' for frame in result.values()))

    def test_missing_model_window_is_rejected(self):
        rules, models, features = self.fixture()
        models.loc[0, 'window_end'] = '2026-04-01 12:06:00'
        with self.assertRaisesRegex(ValueError, 'keys/order differ'):
            variants(rules, models, features)

    def test_empty_model_timeline_is_rejected(self):
        rules, models, features = self.fixture()
        with self.assertRaisesRegex(ValueError, 'empty timeline'):
            variants(rules, models.iloc[:0], features)

    def test_missing_timestamp_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing window_end'):
            validate_alignment(features=pd.DataFrame([{'level': 'normal'}]))

    def test_duplicate_timestamp_is_rejected(self):
        frame = self.fixture()[0]
        with self.assertRaisesRegex(ValueError, 'duplicate window_end'):
            validate_alignment(rules=pd.concat([frame, frame], ignore_index=True))

    def test_reverse_order_is_rejected(self):
        frame = pd.DataFrame({'window_end': ['2026-04-01 12:06:00', '2026-04-01 12:05:00']})
        with self.assertRaisesRegex(ValueError, 'must be increasing'):
            validate_alignment(features=frame)

    def test_invalid_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid window_end'):
            validate_alignment(features=pd.DataFrame({'window_end': ['not-a-time']}))

    def test_missing_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing window_end timestamp'):
            validate_alignment(features=pd.DataFrame({'window_end': [None]}))

    def test_equivalent_but_different_join_keys_are_rejected(self):
        rules, models, features = self.fixture()
        models.loc[0, 'window_end'] = '2026-04-01T12:05:00Z'
        with self.assertRaisesRegex(ValueError, 'keys/order differ'):
            variants(rules, models, features)

    def test_unknown_model_level_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown if_level'):
            variants(*self.fixture(if_level='typo'))

    def test_elapsed_minutes_preserve_gaps_and_nonzero_index(self):
        frame = pd.DataFrame({'window_end': ['2026-04-01 12:00:00', '2026-04-01 12:05:00',
                                              '2026-04-01 12:06:00']}, index=[10, 11, 12])
        self.assertEqual(elapsed_minutes(frame), [0, 5, 6])

    def test_matching_frozen_levels_are_accepted(self):
        frame = self.fixture()[0]
        require_reproduction(frame, frame, 'level', 'unit fixture')

    def test_mismatched_frozen_levels_are_rejected(self):
        frame = self.fixture()[0]
        saved = frame.assign(level='risk')
        with self.assertRaisesRegex(ValueError, 'differ from frozen'):
            require_reproduction(frame, saved, 'level', 'unit fixture')

    def test_frozen_validation_remains_active_under_optimized_python(self):
        report = str(Path(__file__).resolve().parents[1])
        code = (
            f'import sys; sys.path.insert(0, {report!r}); '
            'import pandas as pd; from compare_baseline_models import require_reproduction; '
            "frame = pd.DataFrame([{'window_end': '2026-04-01 12:00:00', 'level': 'normal'}]); "
            "require_reproduction(frame, frame.assign(level='risk'), 'level', 'optimized fixture')"
        )
        result = subprocess.run([sys.executable, '-O', '-c', code], capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ValueError: optimized fixture: replayed levels differ', result.stderr)


if __name__ == '__main__':
    unittest.main()
