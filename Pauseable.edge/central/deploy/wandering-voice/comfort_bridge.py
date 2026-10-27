#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DISCOVERY_PREFIX = "homeassistant"
WATER_TOPIC = "pauseable/virtual/water_purifier"
TIIUN_TOPIC = "pauseable/virtual/tiiun"

ORIGIN = {
    "name": "Pauseable wandering comfort bridge",
    "sw_version": "1.0.0",
    "support_url": "https://github.com/SamDong03/2026ESWContest_smart_Pauseable",
}

WATER_DEVICE = {
    "identifiers": ["pauseable_virtual_water_purifier"],
    "name": "Pauseable Virtual Water Purifier",
    "manufacturer": "Pauseable",
    "model": "Water purifier simulator",
}

TIIUN_DEVICE = {
    "identifiers": ["pauseable_virtual_tiiun"],
    "name": "Pauseable Virtual LG tiiun",
    "manufacturer": "Pauseable",
    "model": "LG ThinQ tiiun simulator",
}


def read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_ha_config(path):
    config = read_json(path)
    ha_url = str(config.get("ha_url", "")).rstrip("/")
    ha_token = str(config.get("ha_token", ""))
    if not ha_url or not ha_token:
        raise ValueError("HA 설정에 ha_url과 ha_token이 필요합니다.")
    return {"ha_url": ha_url, "ha_token": ha_token}


def _validate_entity(value, name, domains):
    entity_id = str(value or "").strip()
    if not entity_id:
        raise ValueError(f"{name} 설정이 필요합니다.")
    domain = entity_id.split(".", 1)[0]
    if domain not in domains:
        expected = "/".join(sorted(domains))
        raise ValueError(f"{name}은 {expected} 엔티티여야 합니다.")
    return entity_id


def load_comfort_config(path):
    config = read_json(path)
    for output_name in ("water_purifier", "tiiun"):
        output = config.get(output_name)
        if not isinstance(output, dict):
            raise ValueError(f"{output_name} 설정이 필요합니다.")
        backend = str(output.get("backend", "virtual")).lower()
        if backend not in {"virtual", "home_assistant"}:
            raise ValueError(
                f"{output_name}.backend는 virtual 또는 home_assistant여야 합니다."
            )
        if not output.get("enabled", True):
            continue
        if output_name == "water_purifier":
            if backend == "virtual":
                seconds = int(output.get("virtual", {}).get("dispense_seconds", 3))
                amount = int(output.get("virtual", {}).get("amount_ml", 150))
                if not 1 <= seconds <= 60 or not 1 <= amount <= 1000:
                    raise ValueError("가상 정수기 시간 또는 물의 양 설정이 잘못되었습니다.")
            else:
                actual = output.get("home_assistant", {})
                if str(actual.get("power_entity_id", "")).strip():
                    _validate_entity(
                        actual.get("power_entity_id"),
                        "water_purifier.home_assistant.power_entity_id",
                        {"switch"},
                    )
                _validate_entity(
                    actual.get("action_entity_id"),
                    "water_purifier.home_assistant.action_entity_id",
                    {"button", "switch"},
                )
        elif backend == "virtual":
            brightness = int(output.get("virtual", {}).get("brightness", 80))
            if not 1 <= brightness <= 255:
                raise ValueError("가상 틔운 brightness는 1~255여야 합니다.")
        else:
            actual = output.get("home_assistant", {})
            if str(actual.get("power_entity_id", "")).strip():
                _validate_entity(
                    actual.get("power_entity_id"),
                    "tiiun.home_assistant.power_entity_id",
                    {"switch"},
                )
            _validate_entity(
                actual.get("light_entity_id"),
                "tiiun.home_assistant.light_entity_id",
                {"light", "switch"},
            )
            brightness = int(actual.get("brightness_pct", 30))
            if not 1 <= brightness <= 100:
                raise ValueError("실제 틔운 brightness_pct는 1~100이어야 합니다.")
    return config


class HomeAssistantClient:
    def __init__(self, base_url, token, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            headers=self.headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                text = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            status = error.code
            text = error.read().decode("utf-8", errors="replace")
        except URLError as error:
            raise RuntimeError(f"Home Assistant 연결 실패: {error.reason}") from None

        if not 200 <= status < 300:
            raise RuntimeError(f"Home Assistant 호출 실패: {path} HTTP {status}")
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def call_service(self, domain, service, data):
        return self.request("POST", f"/api/services/{domain}/{service}", data)

    def get_state(self, entity_id):
        return self.request("GET", f"/api/states/{quote(entity_id, safe='.')}")

    def publish_mqtt(self, topic, payload, retain=False):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return self.call_service(
            "mqtt",
            "publish",
            {"topic": topic, "payload": str(payload), "qos": 1, "retain": retain},
        )


def _component(device, availability_topic, platform, object_id, payload):
    common = {
        "device": device,
        "origin": ORIGIN,
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }
    return (
        f"{DISCOVERY_PREFIX}/{platform}/{object_id}/config",
        {**common, **payload},
    )


def water_discovery_messages():
    availability = f"{WATER_TOPIC}/availability"
    return [
        _component(
            WATER_DEVICE,
            availability,
            "switch",
            "pauseable_virtual_water_purifier_power",
            {
                "name": "Power",
                "unique_id": "pauseable_virtual_water_purifier_power",
                "default_entity_id": "switch.pauseable_virtual_water_purifier_power",
                "state_topic": f"{WATER_TOPIC}/power/state",
                "command_topic": f"{WATER_TOPIC}/power/command",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:water-pump",
            },
        ),
        _component(
            WATER_DEVICE,
            availability,
            "button",
            "pauseable_virtual_water_purifier_dispense",
            {
                "name": "Dispense Cool Water",
                "unique_id": "pauseable_virtual_water_purifier_dispense",
                "default_entity_id": "button.pauseable_virtual_water_purifier_dispense",
                "command_topic": f"{WATER_TOPIC}/dispense/command",
                "payload_press": "PRESS",
                "icon": "mdi:cup-water",
            },
        ),
        _component(
            WATER_DEVICE,
            availability,
            "sensor",
            "pauseable_virtual_water_purifier_status",
            {
                "name": "Current Status",
                "unique_id": "pauseable_virtual_water_purifier_status",
                "default_entity_id": "sensor.pauseable_virtual_water_purifier_status",
                "state_topic": f"{WATER_TOPIC}/status/state",
                "icon": "mdi:water-check",
            },
        ),
        _component(
            WATER_DEVICE,
            availability,
            "sensor",
            "pauseable_virtual_water_purifier_amount",
            {
                "name": "Dispensed Amount",
                "unique_id": "pauseable_virtual_water_purifier_amount",
                "default_entity_id": "sensor.pauseable_virtual_water_purifier_amount",
                "state_topic": f"{WATER_TOPIC}/amount/state",
                "unit_of_measurement": "mL",
                "icon": "mdi:cup",
            },
        ),
        _component(
            WATER_DEVICE,
            availability,
            "event",
            "pauseable_virtual_water_purifier_notification",
            {
                "name": "Notification",
                "unique_id": "pauseable_virtual_water_purifier_notification",
                "default_entity_id": "event.pauseable_virtual_water_purifier_notification",
                "state_topic": f"{WATER_TOPIC}/notification/event",
                "event_types": ["cool_water_ready"],
                "icon": "mdi:bell-check",
            },
        ),
    ]


def tiiun_discovery_messages():
    availability = f"{TIIUN_TOPIC}/availability"
    return [
        _component(
            TIIUN_DEVICE,
            availability,
            "switch",
            "pauseable_virtual_tiiun_power",
            {
                "name": "Power",
                "unique_id": "pauseable_virtual_tiiun_power",
                "default_entity_id": "switch.pauseable_virtual_tiiun_power",
                "state_topic": f"{TIIUN_TOPIC}/power/state",
                "command_topic": f"{TIIUN_TOPIC}/power/command",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:sprout",
            },
        ),
        _component(
            TIIUN_DEVICE,
            availability,
            "light",
            "pauseable_virtual_tiiun_grow_light",
            {
                "name": "Grow Light",
                "unique_id": "pauseable_virtual_tiiun_grow_light",
                "default_entity_id": "light.pauseable_virtual_tiiun_grow_light",
                "state_topic": f"{TIIUN_TOPIC}/light/state",
                "command_topic": f"{TIIUN_TOPIC}/light/command",
                "brightness_state_topic": f"{TIIUN_TOPIC}/light/brightness/state",
                "brightness_command_topic": f"{TIIUN_TOPIC}/light/brightness/command",
                "brightness_scale": 255,
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:lightbulb-on-outline",
            },
        ),
        _component(
            TIIUN_DEVICE,
            availability,
            "sensor",
            "pauseable_virtual_tiiun_status",
            {
                "name": "Care Status",
                "unique_id": "pauseable_virtual_tiiun_status",
                "default_entity_id": "sensor.pauseable_virtual_tiiun_status",
                "state_topic": f"{TIIUN_TOPIC}/status/state",
                "icon": "mdi:flower",
            },
        ),
        _component(
            TIIUN_DEVICE,
            availability,
            "event",
            "pauseable_virtual_tiiun_notification",
            {
                "name": "Notification",
                "unique_id": "pauseable_virtual_tiiun_notification",
                "default_entity_id": "event.pauseable_virtual_tiiun_notification",
                "state_topic": f"{TIIUN_TOPIC}/notification/event",
                "event_types": ["plant_care_requested"],
                "icon": "mdi:flower-tulip-outline",
            },
        ),
    ]


def publish_discovery(client, config):
    initial = []
    water = config["water_purifier"]
    if water.get("enabled", True) and water.get("backend", "virtual") == "virtual":
        for topic, payload in water_discovery_messages():
            client.publish_mqtt(topic, payload, retain=True)
        initial.extend(
            [
                (f"{WATER_TOPIC}/availability", "online"),
                (f"{WATER_TOPIC}/power/state", "ON"),
                (f"{WATER_TOPIC}/status/state", "ready"),
                (f"{WATER_TOPIC}/amount/state", "0"),
            ]
        )

    tiiun = config["tiiun"]
    if tiiun.get("enabled", True) and tiiun.get("backend", "virtual") == "virtual":
        for topic, payload in tiiun_discovery_messages():
            client.publish_mqtt(topic, payload, retain=True)
        initial.extend(
            [
                (f"{TIIUN_TOPIC}/availability", "online"),
                (f"{TIIUN_TOPIC}/power/state", "OFF"),
                (f"{TIIUN_TOPIC}/light/state", "OFF"),
                (f"{TIIUN_TOPIC}/light/brightness/state", "0"),
                (f"{TIIUN_TOPIC}/status/state", "idle"),
            ]
        )

    for topic, payload in initial:
        client.publish_mqtt(topic, payload, retain=True)


def run_virtual_water(client, config, event_id, sleep=time.sleep):
    seconds = int(config.get("dispense_seconds", 3))
    amount = int(config.get("amount_ml", 150))
    client.publish_mqtt(f"{WATER_TOPIC}/power/state", "ON", retain=True)
    client.publish_mqtt(f"{WATER_TOPIC}/status/state", "dispensing_cool_water", retain=True)
    client.publish_mqtt(f"{WATER_TOPIC}/amount/state", "0", retain=True)
    sleep(seconds)
    client.publish_mqtt(f"{WATER_TOPIC}/amount/state", str(amount), retain=True)
    client.publish_mqtt(f"{WATER_TOPIC}/status/state", "cool_water_ready", retain=True)
    client.publish_mqtt(
        f"{WATER_TOPIC}/notification/event",
        {"event_type": "cool_water_ready", "event_id": event_id, "amount_ml": amount},
        retain=False,
    )


def _turn_on_entity(client, entity_id, *, brightness_pct=None):
    entity_id = str(entity_id).strip()
    domain = entity_id.split(".", 1)[0]
    data = {"entity_id": entity_id}
    if domain == "light" and brightness_pct is not None:
        data["brightness_pct"] = int(brightness_pct)
    client.call_service(domain, "turn_on", data)


def run_actual_water(client, config):
    power_id = str(config.get("power_entity_id", "")).strip()
    if power_id:
        _turn_on_entity(client, power_id)
    action_id = _validate_entity(
        config.get("action_entity_id"),
        "water_purifier.home_assistant.action_entity_id",
        {"button", "switch"},
    )
    domain = action_id.split(".", 1)[0]
    service = "press" if domain == "button" else "turn_on"
    client.call_service(domain, service, {"entity_id": action_id})


def run_virtual_tiiun(client, config, event_id):
    brightness = int(config.get("brightness", 80))
    client.publish_mqtt(f"{TIIUN_TOPIC}/power/state", "ON", retain=True)
    client.publish_mqtt(f"{TIIUN_TOPIC}/light/state", "ON", retain=True)
    client.publish_mqtt(
        f"{TIIUN_TOPIC}/light/brightness/state", str(brightness), retain=True
    )
    client.publish_mqtt(f"{TIIUN_TOPIC}/status/state", "plant_care_focus", retain=True)
    client.publish_mqtt(
        f"{TIIUN_TOPIC}/notification/event",
        {"event_type": "plant_care_requested", "event_id": event_id},
        retain=False,
    )


def run_actual_tiiun(client, config):
    power_id = str(config.get("power_entity_id", "")).strip()
    if power_id:
        _turn_on_entity(client, power_id)
    light_id = _validate_entity(
        config.get("light_entity_id"),
        "tiiun.home_assistant.light_entity_id",
        {"light", "switch"},
    )
    _turn_on_entity(
        client,
        light_id,
        brightness_pct=int(config.get("brightness_pct", 30)),
    )


def run_output(client, config, output_name, event_id, sleep=time.sleep):
    output = config[output_name]
    if not output.get("enabled", True):
        print(f"COMFORT_OUTPUT_DISABLED output={output_name}")
        return "disabled"
    backend = output.get("backend", "virtual")
    if output_name == "water_purifier":
        if backend == "virtual":
            run_virtual_water(client, output.get("virtual", {}), event_id, sleep=sleep)
        else:
            run_actual_water(client, output["home_assistant"])
    elif output_name == "tiiun":
        if backend == "virtual":
            run_virtual_tiiun(client, output.get("virtual", {}), event_id)
        else:
            run_actual_tiiun(client, output["home_assistant"])
    else:
        raise ValueError(f"지원하지 않는 출력입니다: {output_name}")
    return backend


def build_client(ha_config):
    return HomeAssistantClient(ha_config["ha_url"], ha_config["ha_token"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ha-config", required=True)
    parser.add_argument("--comfort-config", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--output", choices=("water_purifier", "tiiun"), required=True)
    run_parser.add_argument("--event-id", required=True)
    args = parser.parse_args()

    ha_config = load_ha_config(Path(args.ha_config))
    comfort_config = load_comfort_config(Path(args.comfort_config))
    client = build_client(ha_config)

    if args.command == "discover":
        publish_discovery(client, comfort_config)
        print("COMFORT_VIRTUAL_DISCOVERY_COMPLETE")
        return

    backend = run_output(client, comfort_config, args.output, args.event_id)
    print(
        f"COMFORT_OUTPUT_COMPLETE output={args.output} backend={backend} "
        f"event_id={args.event_id}"
    )


if __name__ == "__main__":
    main()
