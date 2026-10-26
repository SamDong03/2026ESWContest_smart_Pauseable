
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import pandas as pd

from ha_alert_delivery import alert_score, deliver_transition, model_version
from ha_model_lifecycle import atomic_json
from publish_repetitive_mqtt import connect_client, publish_payload
from validate_repetitive_mqtt_payload import default_schema_path, payload_validator
from ha_behavior_feedback import FeedbackStore

BASE = Path(__file__).resolve().parents[1]
SCHEMA = default_schema_path()
TOPIC = 'pauseable/ai/repetitive/decision'


def current_time(row):
    stamp = pd.Timestamp(row['window_end'])
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(os.getenv('HA_TIMEZONE', 'Asia/Seoul'), ambiguous='raise', nonexistent='raise')
    return stamp.tz_convert('UTC').to_pydatetime()


def build_payload(row, patient_id, device_id):
    level = row['level']
    if level not in {'normal', 'attention', 'risk'}:
        raise ValueError('Unknown inference cannot create an action message')
    stamp = current_time(row)
    pattern = re.sub(r'[^a-z0-9_]+', '_', str(row.get('primary_pattern') or 'learned_behavior_anomaly').lower()).strip('_')[:64]
    payload = {
        'contract_version': '1.0', 'event_id': 'ha-' + uuid.uuid4().hex,
        'occurred_at': stamp.isoformat().replace('+00:00', 'Z'),
        'patient_id': patient_id, 'device_id': device_id, 'source': 'repetitive-ai',
        'behavior': 'normal' if level == 'normal' else 'repetitive',
        'risk_level': {'normal': 'normal', 'attention': 'caution', 'risk': 'danger'}[level],
        'risk_score': 0 if level == 'normal' else alert_score(row),
        'model_version': model_version(row, SimpleNamespace()), 'inference_status': 'ok',
        'evidence': {
            'pattern_code': pattern or 'learned_behavior_anomaly',
            'reason_text': str(row.get('reasons') or '')[:500],
            'decision_policy': str(row.get('decision_policy') or 'rules_with_shadow_models')[:64],
            'model_status': str(row.get('model_status') or 'not_trained')[:64],
        },
    }
    payload_validator(SCHEMA).validate(payload)
    return payload


def dispatch(row, state_path, send, patient_id='byunwoojin', device_id='pi5-home-01', now=None, dry_run=False, event_callback=None, review_store=None):
    now = now or datetime.now(timezone.utc)
    age = (now - current_time(row)).total_seconds()
    if not 0 <= age < 300:
        return {'status': 'stale_or_future', 'age_seconds': age}
    if row.get('history_complete') != 1:
        return {'status': 'incomplete_observation_held'}
    revision = None if review_store is None else review_store.revision()
    if review_store is not None and row.get('behavior_review_revision') != revision:
        return {'status': 'behavior_review_changed_held'}
    level = str(row.get('level', 'unknown'))
    def builder():
        payload = build_payload(row, patient_id, device_id)
        if event_callback is not None and not dry_run:
            event_callback(payload, row['window_end'])
        return payload
    def guarded_send(payload):
        if review_store is not None and review_store.revision() != revision:
            raise ValueError('Behavior review changed before delivery; recompute next cycle')
        send(payload)
    return deliver_transition(state_path, level, builder, builder, guarded_send,
                              pattern=str(row.get('primary_pattern') or ''), now=now, dry_run=dry_run,
                              delivery_epoch=revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--state-file', required=True)
    parser.add_argument('--status-file', required=True)
    parser.add_argument('--patient-id', default='byunwoojin')
    parser.add_argument('--device-id', default='pi5-home-01')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--lifecycle-dir')
    args = parser.parse_args()
    client = None
    transport = SimpleNamespace(host=os.getenv('MQTT_HOST', '127.0.0.1'),
                                port=int(os.getenv('MQTT_PORT', '1883')),
                                username=os.getenv('MQTT_USER', ''), password=os.getenv('MQTT_PASSWORD', ''),
                                topic=TOPIC, qos=1, retain=False, dry_run=args.dry_run)
    def send(payload):
        nonlocal client
        payload_validator(SCHEMA).validate(payload)
        if not args.dry_run and client is None:
            client = connect_client(transport)
        publish_payload(client, transport, payload)
    try:
        row = json.loads(Path(args.input).read_text(encoding='utf-8'))
        callback = None
        store = None
        if args.lifecycle_dir:
            identity = json.loads((Path(args.lifecycle_dir) / 'identity.json').read_text(encoding='utf-8'))
            store = FeedbackStore(args.lifecycle_dir, identity['source_type'], identity['household_id'])
            if row.get('behavior_review_revision') != store.revision():
                result = {'status': 'behavior_review_changed_held'}
                atomic_json(args.status_file, result)
                print(json.dumps(result), flush=True)
                return
            callback = store.register_event
        result = dispatch(row, Path(args.state_file), send, args.patient_id, args.device_id, dry_run=args.dry_run,
                          event_callback=callback, review_store=store)
        atomic_json(args.status_file, result)
        print(json.dumps(result), flush=True)
    finally:
        if client is not None:
            client.disconnect()
            client.loop_stop()


if __name__ == '__main__':
    main()
