
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from queue import Queue
import threading
import time
from types import SimpleNamespace

import paho.mqtt.client as mqtt

from ha_decision_delivery import SCHEMA, TOPIC, dispatch
from ha_model_lifecycle import atomic_json
from publish_repetitive_mqtt import connect_client, publish_payload
from validate_repetitive_mqtt_payload import payload_validator


def run(host, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    ready, messages = threading.Event(), Queue()
    subscriber = mqtt.Client()
    subscriber.on_connect = lambda client, userdata, flags, rc: client.subscribe(TOPIC, qos=1) if rc == 0 else None
    subscriber.on_subscribe = lambda client, userdata, mid, granted: ready.set()
    subscriber.on_message = lambda client, userdata, message: messages.put(
        {'payload': json.loads(message.payload), 'retained': message.retain, 'qos': message.qos})
    sender = None
    subscriber.connect(host, 1883, 30)
    subscriber.loop_start()
    transport = SimpleNamespace(host=host, port=1883, username='', password='', topic=TOPIC,
                                qos=1, retain=False, dry_run=False)
    try:
        assert ready.wait(10), 'Subscriber did not acknowledge the subscription'
        sender = connect_client(transport)
        now = datetime.now(timezone.utc)
        row = {'window_end': now.isoformat(), 'level': 'attention', 'risk_score': 35,
               'history_complete': 1, 'primary_pattern': 'fridge_repeated_check',
               'model_id': 'synthetic-local-mqtt-acceptance', 'model_status': 'shadow',
               'decision_policy': 'rules_plus_validated_if_ae', 'reasons': 'ISOLATED TEST, NOT A PATIENT EVENT'}
        state = output / 'delivery_state.json'
        send = lambda payload: publish_payload(sender, transport, payload)
        checks = []
        checks.append(dispatch(row, state, send, now=now))
        checks.append(dispatch(row, state, send, now=now))
        checks.append(dispatch({**row, 'level': 'risk', 'risk_score': 70}, state, send, now=now))
        checks.append(dispatch({**row, 'level': 'unknown'}, state, send, now=now))
        checks.append(dispatch({**row, 'history_complete': 0}, state, send, now=now))
        checks.append(dispatch(row, state, send, now=now + timedelta(minutes=5)))
        checks.append(dispatch({**row, 'level': 'normal', 'risk_score': 0}, state, send, now=now))
        received = [messages.get(timeout=10) for _ in range(3)]
        time.sleep(.5)
        assert messages.empty(), 'Unexpected duplicate/action message'
        validator = payload_validator(SCHEMA)
        for item in received:
            validator.validate(item['payload'])
            assert not item['retained'] and item['qos'] == 1
        assert [item['payload']['risk_level'] for item in received] == ['caution', 'danger', 'normal']
        assert len({item['payload']['event_id'] for item in received}) == 3
        report = {'passed': True, 'real_local_broker': True, 'qos': 1, 'retain': False,
                  'received_messages': received, 'transitions': checks, 'pi_connected': False,
                  'central_executed': False, 'appliance_controlled': False, 'clinical_validation': False}
        atomic_json(output / 'report.json', report)
        return report
    finally:
        if sender is not None:
            sender.disconnect()
            sender.loop_stop()
        subscriber.disconnect()
        subscriber.loop_stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.host, args.output_dir), indent=2), flush=True)
