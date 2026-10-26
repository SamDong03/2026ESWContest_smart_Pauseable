import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zlib

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ha_model_lifecycle import load_frame, store_frame
from ha_observation_reader import read_observations


class ObservationReaderTests(unittest.TestCase):
    def test_chunk_boundary_mixed_legacy_and_compressed_rows(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'history.sqlite3'
            times = pd.date_range('2026-01-01', periods=1025, freq='min').astype(str)
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE observations (window_end TEXT PRIMARY KEY, payload TEXT)')
                for index, stamp in enumerate(times):
                    body = json.dumps({'window_end': stamp, 'value': index, 'optional': None})
                    db.execute('INSERT INTO observations VALUES (?, ?)',
                               (stamp, body if index % 2 else zlib.compress(body.encode())))
            frame = read_observations(path)
            self.assertEqual(len(frame), 1025)
            self.assertEqual(frame['value'].tolist(), list(range(1025)))
            self.assertTrue(frame['optional'].isna().all())
            self.assertEqual(len(read_observations(path, limit=1)), 1)
            subset = read_observations(path, ['window_end>=?', 'window_end<=?'], [times[510], times[514]])
            self.assertEqual(subset['value'].tolist(), list(range(510, 515)))

    def test_chunked_store_upsert_and_retention(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'history.sqlite3'
            frame = pd.DataFrame({'window_end': pd.date_range('2026-01-01', periods=1025, freq='min').astype(str),
                                  'value': range(1025)})
            store_frame(path, frame)
            pd.testing.assert_frame_equal(load_frame(path), frame)
            update = frame.tail(1).assign(value=2048)
            store_frame(path, update)
            self.assertEqual(load_frame(path).iloc[-1]['value'], 2048)
            store_frame(path, pd.DataFrame([{'window_end': '2026-03-01 00:00:00', 'value': 9}]))
            self.assertEqual(load_frame(path)['value'].tolist(), [9])


if __name__ == '__main__':
    unittest.main()
