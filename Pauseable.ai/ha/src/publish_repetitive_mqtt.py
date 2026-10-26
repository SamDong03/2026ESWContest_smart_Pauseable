import argparse
import json
import os
import threading
import time
from pathlib import Path


DEFAULT_TOPIC = "pauseable/ai/repetitive/decision"
PUBLISH_RETRY_COUNT = 3
RECONNECT_WAIT_SECONDS = 0.8


def env_or_default(name, default=None):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def mqtt_code_value(code):
    value = getattr(code, "value", code)
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def wait_until_connected(client, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.is_connected():
            return True
        time.sleep(0.1)
    return client.is_connected()


def reconnect(client):
    try:
        client.reconnect()
    except Exception:
        pass
    time.sleep(RECONNECT_WAIT_SECONDS)


def connect_client(args):
    import paho.mqtt.client as mqtt

    client = mqtt.Client()
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    connected = threading.Event()
    status = {
        "connect_rc": None,
        "connect_reason": "",
        "disconnect_rc": None,
        "disconnect_reason": "",
    }

    def on_connect(client, userdata, flags, reason_code, properties=None):
        status["connect_rc"] = mqtt_code_value(reason_code)
        status["connect_reason"] = str(reason_code)
        if status["connect_rc"] == 0:
            connected.set()
            print(f"mqtt connected: {args.host}:{args.port}")
        else:
            print(f"mqtt connect rejected: rc={status['connect_rc']} reason={status['connect_reason']}")

    def on_disconnect(client, userdata, reason_code, properties=None):
        status["disconnect_rc"] = mqtt_code_value(reason_code)
        status["disconnect_reason"] = str(reason_code)
        connected.clear()
        if status["disconnect_rc"] not in (0, None):
            print(f"mqtt disconnected: rc={status['disconnect_rc']} reason={status['disconnect_reason']}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    if args.username:
        client.username_pw_set(args.username, args.password or "")

    result = client.connect(args.host, args.port, keepalive=60)
    if result != 0:
        raise RuntimeError(f"MQTT connect failed: host={args.host} port={args.port} rc={result}")

    client.loop_start()
    if not connected.wait(timeout=8.0):
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass
        if status["connect_rc"] is not None:
            raise RuntimeError(
                "MQTT broker rejected the login: "
                f"host={args.host} port={args.port} "
                f"rc={status['connect_rc']} reason={status['connect_reason']}"
            )
        raise RuntimeError(
            "MQTT connection timed out after TCP connect: "
            f"host={args.host} port={args.port}"
        )
    return client


def load_payloads(path):
    payloads = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}: {exc}") from exc

            event_id = str(payload.get("event_id", "")).strip()
            if not event_id:
                raise ValueError(f"missing event_id at line {line_number}")
            payloads.append(payload)
    return payloads


def publish_payload(client, args, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    event_id = payload.get("event_id", "")

    if args.dry_run:
        print(f"DRY-RUN {args.topic} <- {body}")
        return

    last_error = None
    for attempt in range(1, PUBLISH_RETRY_COUNT + 1):
        if not wait_until_connected(client, timeout=2.0):
            reconnect(client)

        try:
            result = client.publish(args.topic, body, qos=args.qos, retain=args.retain)
            result.wait_for_publish(timeout=5.0)
            if result.rc == 0 and result.is_published():
                print(f"published topic={args.topic} event_id={event_id} qos={args.qos} retain={args.retain}")
                return
            last_error = RuntimeError(f"MQTT publish not confirmed: rc={result.rc}")
        except RuntimeError as exc:
            last_error = exc
            reconnect(client)

        if attempt < PUBLISH_RETRY_COUNT:
            print(f"publish retry {attempt}/{PUBLISH_RETRY_COUNT}: event_id={event_id}")
            time.sleep(RECONNECT_WAIT_SECONDS)

    raise RuntimeError(f"MQTT publish failed after retries: event_id={event_id}: {last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSONL payload file generated by export_repetitive_mqtt_payload.py")
    parser.add_argument("--topic", default=env_or_default("MQTT_REPETITIVE_TOPIC", DEFAULT_TOPIC))
    parser.add_argument("--host", default=env_or_default("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(env_or_default("MQTT_PORT", "1883")))
    parser.add_argument("--username", default=env_or_default("MQTT_USER"))
    parser.add_argument("--password", default=env_or_default("MQTT_PASSWORD"))
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1)
    parser.add_argument("--retain", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payloads = load_payloads(args.input)
    print(f"payloads: {len(payloads)}")
    if not payloads:
        return

    client = None
    try:
        if not args.dry_run:
            client = connect_client(args)
        for payload in payloads:
            publish_payload(client, args, payload)
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()

    print("publish complete")


if __name__ == "__main__":
    main()
