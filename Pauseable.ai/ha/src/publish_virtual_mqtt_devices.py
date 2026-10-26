import argparse
import json
import os
import threading
import time


DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "pauseable/virtual"
PUBLISH_RETRY_COUNT = 3
RECONNECT_WAIT_SECONDS = 0.8


DEVICE = {
    "identifiers": ["pauseable_virtual_home"],
    "name": "Pauseable Virtual Home",
    "manufacturer": "Pauseable",
    "model": "MQTT virtual demo devices",
}


DISCOVERY_MESSAGES = [
    (
        f"{DISCOVERY_PREFIX}/lock/pauseable_virtual_door_lock/config",
        {
            "name": "Pauseable Virtual Door Lock",
            "unique_id": "pauseable_virtual_door_lock",
            "state_topic": f"{BASE_TOPIC}/door_lock/state",
            "command_topic": f"{BASE_TOPIC}/door_lock/command",
            "payload_lock": "LOCK",
            "payload_unlock": "UNLOCK",
            "state_locked": "LOCK",
            "state_unlocked": "UNLOCK",
            "device": DEVICE,
        },
    ),
    (
        f"{DISCOVERY_PREFIX}/switch/pauseable_virtual_microwave_power/config",
        {
            "name": "Pauseable Virtual Microwave Power",
            "unique_id": "pauseable_virtual_microwave_power",
            "state_topic": f"{BASE_TOPIC}/microwave/power/state",
            "command_topic": f"{BASE_TOPIC}/microwave/power/command",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "device": DEVICE,
        },
    ),
    (
        f"{DISCOVERY_PREFIX}/sensor/pauseable_virtual_microwave_status/config",
        {
            "name": "Pauseable Virtual Microwave Status",
            "unique_id": "pauseable_virtual_microwave_status",
            "state_topic": f"{BASE_TOPIC}/microwave/status/state",
            "icon": "mdi:microwave",
            "device": DEVICE,
        },
    ),
    (
        f"{DISCOVERY_PREFIX}/switch/pauseable_virtual_air_conditioner_power/config",
        {
            "name": "Pauseable Virtual Air Conditioner Power",
            "unique_id": "pauseable_virtual_air_conditioner_power",
            "state_topic": f"{BASE_TOPIC}/air_conditioner/power/state",
            "command_topic": f"{BASE_TOPIC}/air_conditioner/power/command",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "device": DEVICE,
        },
    ),
    (
        f"{DISCOVERY_PREFIX}/select/pauseable_virtual_air_conditioner_mode/config",
        {
            "name": "Pauseable Virtual Air Conditioner Mode",
            "unique_id": "pauseable_virtual_air_conditioner_mode",
            "state_topic": f"{BASE_TOPIC}/air_conditioner/mode/state",
            "command_topic": f"{BASE_TOPIC}/air_conditioner/mode/command",
            "options": ["auto", "cool", "dry", "fan"],
            "icon": "mdi:air-conditioner",
            "device": DEVICE,
        },
    ),
    (
        f"{DISCOVERY_PREFIX}/number/pauseable_virtual_air_conditioner_temperature/config",
        {
            "name": "Pauseable Virtual Air Conditioner Temperature",
            "unique_id": "pauseable_virtual_air_conditioner_temperature",
            "state_topic": f"{BASE_TOPIC}/air_conditioner/temperature/state",
            "command_topic": f"{BASE_TOPIC}/air_conditioner/temperature/command",
            "min": 18,
            "max": 30,
            "step": 1,
            "mode": "slider",
            "unit_of_measurement": "C",
            "device": DEVICE,
        },
    ),
]


INITIAL_STATES = [
    (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
    (f"{BASE_TOPIC}/microwave/power/state", "OFF"),
    (f"{BASE_TOPIC}/microwave/status/state", "IDLE"),
    (f"{BASE_TOPIC}/air_conditioner/power/state", "OFF"),
    (f"{BASE_TOPIC}/air_conditioner/mode/state", "auto"),
    (f"{BASE_TOPIC}/air_conditioner/temperature/state", "24"),
]


SCENARIOS = {
    "discover": [],
    "normal": [
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
        (f"{BASE_TOPIC}/microwave/power/state", "ON"),
        (f"{BASE_TOPIC}/microwave/status/state", "COOKING"),
        (f"{BASE_TOPIC}/microwave/status/state", "DONE"),
        (f"{BASE_TOPIC}/microwave/power/state", "OFF"),
        (f"{BASE_TOPIC}/microwave/status/state", "IDLE"),
        (f"{BASE_TOPIC}/air_conditioner/power/state", "ON"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "cool"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "25"),
    ],
    "risk_door_lock": [
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
    ],
    "risk_microwave": [
        (f"{BASE_TOPIC}/microwave/power/state", "ON"),
        (f"{BASE_TOPIC}/microwave/status/state", "COOKING"),
        (f"{BASE_TOPIC}/microwave/status/state", "DONE"),
        (f"{BASE_TOPIC}/microwave/status/state", "IDLE"),
        (f"{BASE_TOPIC}/microwave/status/state", "COOKING"),
        (f"{BASE_TOPIC}/microwave/status/state", "DONE"),
        (f"{BASE_TOPIC}/microwave/status/state", "IDLE"),
        (f"{BASE_TOPIC}/microwave/status/state", "COOKING"),
        (f"{BASE_TOPIC}/microwave/status/state", "DONE"),
        (f"{BASE_TOPIC}/microwave/power/state", "OFF"),
    ],
    "risk_air_conditioner": [
        (f"{BASE_TOPIC}/air_conditioner/power/state", "ON"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "cool"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "24"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "dry"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "22"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "fan"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "26"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "cool"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "23"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "auto"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "25"),
    ],
    "demo_risk_combo": [
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "UNLOCK"),
        (f"{BASE_TOPIC}/door_lock/state", "LOCK"),
        (f"{BASE_TOPIC}/microwave/power/state", "ON"),
        (f"{BASE_TOPIC}/microwave/status/state", "COOKING"),
        (f"{BASE_TOPIC}/microwave/status/state", "DONE"),
        (f"{BASE_TOPIC}/microwave/status/state", "IDLE"),
        (f"{BASE_TOPIC}/microwave/status/state", "COOKING"),
        (f"{BASE_TOPIC}/air_conditioner/power/state", "ON"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "cool"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "24"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "dry"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "22"),
        (f"{BASE_TOPIC}/air_conditioner/mode/state", "fan"),
        (f"{BASE_TOPIC}/air_conditioner/temperature/state", "26"),
    ],
}


def env_or_default(name, default=None):
    value = os.getenv(name)
    if value is None or value == "":
        return default
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


def mqtt_code_value(code):
    value = getattr(code, "value", code)
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def publish(client, topic, payload, retain=False, dry_run=False):
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload, ensure_ascii=False)

    if dry_run:
        print(f"DRY-RUN {topic} <- {payload}")
        return

    last_error = None
    for attempt in range(1, PUBLISH_RETRY_COUNT + 1):
        if not wait_until_connected(client, timeout=2.0):
            reconnect(client)

        try:
            result = client.publish(topic, payload, retain=retain)
            result.wait_for_publish(timeout=5.0)
            if result.rc == 0:
                print(f"published {topic} <- {payload}")
                return
            last_error = RuntimeError(f"MQTT publish rc={result.rc}")
        except RuntimeError as exc:
            last_error = exc
            reconnect(client)

        if attempt < PUBLISH_RETRY_COUNT:
            print(f"publish retry {attempt}/{PUBLISH_RETRY_COUNT}: {topic}")
            time.sleep(RECONNECT_WAIT_SECONDS)

    raise RuntimeError(f"MQTT publish failed after retries: topic={topic}: {last_error}")


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
            f"host={args.host} port={args.port}. "
            "Check that the Mosquitto add-on is running and that the MQTT user is allowed."
        )
    return client


def publish_discovery(client, args):
    for topic, payload in DISCOVERY_MESSAGES:
        publish(client, topic, payload, retain=args.retain_discovery, dry_run=args.dry_run)


def publish_initial_states(client, args):
    for topic, payload in INITIAL_STATES:
        publish(client, topic, payload, retain=args.retain_state, dry_run=args.dry_run)


def publish_scenario(client, args):
    for topic, payload in SCENARIOS[args.scenario]:
        publish(client, topic, payload, retain=args.retain_state, dry_run=args.dry_run)
        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=env_or_default("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(env_or_default("MQTT_PORT", "1883")))
    parser.add_argument("--username", default=env_or_default("MQTT_USER"))
    parser.add_argument("--password", default=env_or_default("MQTT_PASSWORD"))
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS.keys()),
        default="discover",
        help="Discovery registers entities; other scenarios also publish state changes.",
    )
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--retain-discovery", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retain-state", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = None
    try:
        if not args.dry_run:
            client = connect_client(args)
        publish_discovery(client, args)
        publish_initial_states(client, args)
        publish_scenario(client, args)
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()

    print(f"scenario complete: {args.scenario}")


if __name__ == "__main__":
    main()
