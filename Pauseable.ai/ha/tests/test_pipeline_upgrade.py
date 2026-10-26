import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
import uuid

import pandas as pd

from test_anomaly_upgrade import event, test_directory
import test_anomaly_upgrade
from collect_ha_events_ws import SimpleWebSocket, WebSocketError
from build_baseline import build_baseline
from make_ha_features import build_features, parse_time
from train_ha_anomaly_models import train_models

BASE = Path(__file__).resolve().parents[1]


class CollectorTests(unittest.TestCase):
    def test_ping_stream_respects_deadline(self):
        ws = SimpleWebSocket('ws://example', 10)
        ws.deadline = 2
        ws.recv_frame = Mock(return_value=(9, b''))
        ws.send_frame = Mock()
        with patch('collect_ha_events_ws.time.monotonic', side_effect=[0, 1, 2]):
            with self.assertRaises(socket.timeout):
                ws.recv_json()
        self.assertEqual(ws.send_frame.call_count, 2)

    def test_partial_frame_requires_reconnect(self):
        ws = SimpleWebSocket('ws://example', 10)
        ws.sock = Mock()
        ws.sock.recv.side_effect = [b'\x81\x03', socket.timeout()]
        with self.assertRaises(WebSocketError):
            ws.recv_frame()

    def test_idle_read_uses_remaining_duration(self):
        ws = SimpleWebSocket('ws://example', 10)
        ws.deadline = 5
        ws.sock = Mock()
        ws.sock.recv.return_value = b'x'
        with patch('collect_ha_events_ws.time.monotonic', return_value=4):
            self.assertEqual(ws._read_exact(1), b'x')
        ws.sock.settimeout.assert_called_with(1)


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, rows, source='synthetic', extra=()):
        directory = BASE / 'outputs' / 'test_runs' / uuid.uuid4().hex
        directory.mkdir(parents=True)
        path = directory / 'events.csv'
        rows.to_csv(path, index=False)

        baseline = directory / 'synthetic_baseline.json'
        normal = build_features(pd.DataFrame([event('2025-12-01 10:00', 'idle')]))
        baseline.write_text(json.dumps(build_baseline(normal)), encoding='utf-8')
        prefix = 'test_' + directory.name
        result = subprocess.run([sys.executable, str(BASE / 'src/run_ha_pipeline.py'), '--input', str(path),
                                 '--baseline', str(baseline),
                                 '--prefix', prefix, '--data-source', source, *extra],
                                cwd=BASE, capture_output=True, text=True, timeout=60)
        (directory / 'pipeline.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (pd.read_csv(BASE / 'outputs' / f'{prefix}_result.csv'),
                json.loads((BASE / 'outputs' / f'{prefix}_data_quality.json').read_text()))

    def test_empty_input_produces_no_normal_result(self):
        rows = pd.DataFrame(columns=event('2026-09-01', 'idle').keys())
        result, quality = self.run_pipeline(rows)
        self.assertTrue(result.empty)
        self.assertEqual(quality['status'], 'no_usable_data')

    def test_virtual_events_excluded_from_local_history(self):
        rows = pd.DataFrame([event('2026-09-01 10:00', 'running', entity='sensor.pauseable_virtual_washer')])
        result, quality = self.run_pipeline(rows, 'local')
        self.assertTrue(result.empty)
        self.assertEqual(quality['current_usable_rows'], 0)

    def test_rule_alert_remains_independent_of_models(self):
        rows = [event('2026-09-01 10:00', 'idle', device='microwave')]
        for minute, action in enumerate(['running', 'done', 'idle', 'running', 'done', 'idle', 'running'], 1):
            rows.append(event(f'2026-09-01 10:0{minute}', action, device='microwave'))
        result, _ = self.run_pipeline(pd.DataFrame(rows))
        self.assertTrue(result['level'].equals(result['rule_level']))
        self.assertTrue(result['risk_score'].equals(result['rule_score']))
        self.assertTrue(result['model_status'].eq('not_trained').all())
        self.assertTrue(result['level'].isin(['risk', 'attention']).any())

    def test_short_window_preserves_empty_schema(self):
        result = build_features(pd.DataFrame([event('2026-09-01 10:00:10', 'idle')]),
                                parse_time('2026-09-01 10:01'), parse_time('2026-09-01 10:00'))
        self.assertTrue(result.empty)
        self.assertIn('window_end', result)

    def test_local_training_cannot_bypass_review(self):
        with test_directory() as path:
            source = path / 'features.csv'
            test_anomaly_upgrade.ModelTests().frame().to_csv(source, index=False)
            with self.assertRaisesRegex(ValueError, 'provenance'):
                train_models(source, path / 'model', 'local', 'house', 'assumed normal')
            with self.assertRaisesRegex(ValueError, '120-minute'):
                train_models(source, path / 'model', 'local', 'house', 'reviewed', gap_minutes=0)


if __name__ == '__main__':
    unittest.main()
