
import argparse
import json
import os
from pathlib import Path
import signal
import time
from types import SimpleNamespace

from ha_behavior_feedback import queue_review
from publish_repetitive_mqtt import connect_client, mqtt_code_value

TOPIC = 'pauseable/ai/repetitive/feedback'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lifecycle-dir', required=True)
    parser.add_argument('--allow-insecure-test-broker', action='store_true')
    args = parser.parse_args()
    if not args.allow_insecure_test_broker and (not os.getenv('MQTT_USER') or not os.getenv('MQTT_PASSWORD')):
        parser.error('Use authenticated broker credentials/ACLs; anonymous feedback is allowed only in an isolated test')
    root = Path(args.lifecycle_dir).resolve()
    transport = SimpleNamespace(host=os.getenv('MQTT_HOST', '127.0.0.1'), port=int(os.getenv('MQTT_PORT', '1883')),
                                username=os.getenv('MQTT_USER', ''), password=os.getenv('MQTT_PASSWORD', ''))
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    client = connect_client(transport)
    def message(client, userdata, received):
        try:
            if received.topic != TOPIC or received.retain or len(received.payload) > 16384:
                raise ValueError('Feedback must be non-retained, bounded and on the feedback topic')
            result = queue_review(root, json.loads(received.payload))
            print(json.dumps(result), flush=True)
        except Exception as error:
            print(json.dumps({'status': 'rejected', 'reason': type(error).__name__}), flush=True)
    client.on_message = message
    original_connect = client.on_connect
    def subscribe(client, userdata, flags, reason_code, properties=None):
        original_connect(client, userdata, flags, reason_code, properties)
        if mqtt_code_value(reason_code) == 0:
            client.subscribe(TOPIC, qos=1)
    client.on_connect = subscribe
    client.on_subscribe = lambda client, userdata, mid, granted: print(
        json.dumps({'status': 'feedback_subscription_ready', 'granted_qos': list(granted)}), flush=True)
    client.subscribe(TOPIC, qos=1)
    try:
        while not stopped:
            time.sleep(.25)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == '__main__':
    main()
