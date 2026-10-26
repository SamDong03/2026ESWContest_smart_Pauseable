import unittest

import pandas as pd

import test_anomaly_upgrade
from verify_ha_month_cycle import synthetic_baseline


class PublicationTests(unittest.TestCase):
    def test_baseline_is_synthetic_and_precedes_month(self):
        baseline = synthetic_baseline()
        self.assertEqual(baseline['source_type'], 'synthetic')
        self.assertLess(pd.Timestamp(baseline['observed_end']), pd.Timestamp('2026-01-01'))
        self.assertFalse({'source_type', 'household_id', 'schema_version', 'history_complete'}
                         & set(baseline['features']))


if __name__ == '__main__':
    unittest.main()
