
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pandas as pd

from ha_behavior_feedback import canonical
from ha_alert_delivery import load_state
from ha_decision_delivery import dispatch
from ha_model_lifecycle import Lifecycle, SCHEMA, atomic_json
from make_ha_features import FEATURE_COLUMNS
from publish_repetitive_mqtt import connect_client, publish_payload
from receive_ha_behavior_feedback import TOPIC


def wait_for(condition, timeout=15):
    began = time.monotonic()
    while time.monotonic() - began < timeout:
        if condition():
            return
        time.sleep(.1)
    raise TimeoutError('MQTT feedback acceptance condition was not reached')


def run(host, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    house = 'synthetic-mqtt-review'
    life = Lifecycle(output / 'models', 'synthetic', house)
    stamp = pd.Timestamp.now(tz='UTC').floor('min') - pd.Timedelta(minutes=1)
    row = {name: 0 for name in FEATURE_COLUMNS}
    row.update(window_end=str(stamp.tz_convert('Asia/Seoul').tz_localize(None)), source_type='synthetic',
               household_id=house, schema_version=SCHEMA, history_complete=1,
               fridge_door_open_count_1h=2, fridge_door_open_count_30m=2)
    frame = pd.DataFrame([row])
    life.ingest(frame, frame[['window_end']].assign(level='normal', risk_score=0))
    decision = {**row, 'level': 'risk', 'risk_score': 70, 'primary_pattern': 'fridge_repeated_check',
                'behavior_review_revision': life.feedback.revision()}
    delivery_path = output / 'delivery_state.json'
    def failed_sender(payload):
        raise RuntimeError('Simulated lost broker ACK before behavior reviews')
    try:
        dispatch(decision, delivery_path, failed_sender, event_callback=life.feedback.register_event,
                 review_store=life.feedback)
    except RuntimeError:
        pass
    event = load_state(delivery_path)['pending']['payload']
    env = {**os.environ, 'MQTT_HOST': host, 'MQTT_PORT': '1883', 'MQTT_USER': '', 'MQTT_PASSWORD': ''}
    transport = SimpleNamespace(host=host, port=1883, username='', password='', topic=TOPIC, qos=1, retain=False, dry_run=False)
    client = None
    with (output / 'receiver.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).with_name('receive_ha_behavior_feedback.py')),
                                    '--lifecycle-dir', str(life.root), '--allow-insecure-test-broker'],
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_for(lambda: 'feedback_subscription_ready' in (output / 'receiver.log').read_text())
            client = connect_client(transport)
            publish_payload(client, transport, {'event_id': event['event_id'], 'action': 'confirmed_safe'})
            message = {'contract_version': '1.0', 'feedback_id': 'mqtt-normal-review', 'event_id': event['event_id'],
                       'source_type': 'synthetic', 'household_id': house, 'patient_id': 'byunwoojin',
                       'device_id': 'pi5-home-01', 'review_kind': 'behavior_label', 'label': 'normal',
                       'reviewer_id': 'isolated-synthetic-test', 'reviewed_at': datetime.now(timezone.utc).isoformat()}
            publish_payload(client, transport, message)
            publish_payload(client, transport, message)
            inbox = life.root / 'feedback_inbox'
            wait_for(lambda: len(list(inbox.glob('*.json'))) == 2)
            assert life.feedback.labels().empty, 'Queue acknowledgement was mistaken for an applied label'
            first = life.feedback.drain_inbox()
            assert first == {'applied': 1, 'duplicate': 1, 'rejected': 0}, first
            assert life.feedback.reviewed_frame(life.feedback.history()).iloc[0]['review_status'] == 'reviewed_normal'
            correction = {**message, 'feedback_id': 'mqtt-corrected-review', 'label': 'repetitive',
                          'reviewed_at': datetime.now(timezone.utc).isoformat()}
            publish_payload(client, transport, correction)
            wait_for(lambda: len(list(inbox.glob('*.json'))) == 1)
            second = life.feedback.drain_inbox()
            assert second['applied'] == 1
            assert life.feedback.reviewed_frame(life.feedback.history()).iloc[0]['review_status'] == 'excluded'
            latest = {**decision, 'behavior_review_revision': life.feedback.revision()}
            sent = []
            decision_transport = SimpleNamespace(**{**vars(transport), 'topic': 'pauseable/ai/repetitive/decision'})
            def send_latest(payload):
                publish_payload(client, decision_transport, payload)
                sent.append(payload['event_id'])
            delivered = dispatch(latest, delivery_path, send_latest, event_callback=life.feedback.register_event,
                                 review_store=life.feedback)
            assert delivered['status'] == 'published' and len(sent) == 1
            assert event['event_id'] not in sent
            assert load_state(delivery_path)['discard_reason'] == 'review_context_changed'
            report = {'passed': True, 'real_local_broker': True, 'source_type': 'synthetic',
                      'explicit_review_round_trip': True, 'safety_ack_not_used_as_normal_label': True,
                      'duplicate_review_idempotent': True, 'correction_excludes_training_window': True,
                      'queued_is_not_applied': True, 'pi_connected': False, 'flutter_connected': False,
                      'old_pending_event_not_replayed_after_review': True,
                      'fresh_decision_broker_acknowledged': True,
                      'clinical_validation': False, 'first_drain': first, 'correction_drain': second}
            atomic_json(output / 'report.json', report)
            return report
        finally:
            if client is not None:
                client.disconnect()
                client.loop_stop()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.host, args.output_dir), indent=2), flush=True)
