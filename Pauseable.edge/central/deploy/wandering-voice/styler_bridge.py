#!/usr/bin/env python3


import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "pauseable/virtual/styler"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/availability"

DEVICE = {
    "identifiers": ["pauseable_virtual_styler"],
    "name": "Pauseable Virtual Styler",
    "manufacturer": "Pauseable",
    "model": "LG ThinQ Styler simulator",
}

ORIGIN = {
    "name": "Pauseable wandering Styler bridge",
    "sw_version": "1.0.0",
    "support_url": "https://github.com/RACOS-Team/Pauseable",
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


def load_styler_config(path):
    config = read_json(path)
    backend = str(config.get("backend", "virtual")).lower()
    if backend not in {"virtual", "thinq"}:
        raise ValueError("backend는 virtual 또는 thinq여야 합니다.")

    if backend == "virtual":
        seconds = int(config.get("virtual", {}).get("cycle_seconds", 15))
        if not 1 <= seconds <= 3600:
            raise ValueError("virtual.cycle_seconds는 1~3600초여야 합니다.")
    else:
        thinq = config.get("thinq", {})
        required = ("operation_entity_id", "operation_option", "start_entity_id")
        missing = [key for key in required if not str(thinq.get(key, "")).strip()]
        if missing:
            raise ValueError("ThinQ 필수 설정 누락: " + ", ".join(missing))
        if not thinq.get("status_entity_id") and not thinq.get(
            "completion_event_entity_id"
        ):
            raise ValueError(
                "ThinQ 완료 확인용 status_entity_id 또는 "
                "completion_event_entity_id가 필요합니다."
            )
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


def discovery_messages():
    common = {
        "device": DEVICE,
        "origin": ORIGIN,
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
    }

    def component(platform, object_id, payload):
        return (
            f"{DISCOVERY_PREFIX}/{platform}/{object_id}/config",
            {**common, **payload},
        )

    return [
        component(
            "switch",
            "pauseable_virtual_styler_power",
            {
                "name": "Power",
                "unique_id": "pauseable_virtual_styler_power",
                "default_entity_id": "switch.pauseable_virtual_styler_power",
                "state_topic": f"{BASE_TOPIC}/power/state",
                "command_topic": f"{BASE_TOPIC}/power/command",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:power",
            },
        ),
        component(
            "select",
            "pauseable_virtual_styler_operation",
            {
                "name": "Operation",
                "unique_id": "pauseable_virtual_styler_operation",
                "default_entity_id": "select.pauseable_virtual_styler_operation",
                "state_topic": f"{BASE_TOPIC}/operation/state",
                "command_topic": f"{BASE_TOPIC}/operation/command",
                "options": ["ready", "warm"],
                "icon": "mdi:hanger",
            },
        ),
        component(
            "button",
            "pauseable_virtual_styler_start_pause",
            {
                "name": "Start Pause",
                "unique_id": "pauseable_virtual_styler_start_pause",
                "default_entity_id": "button.pauseable_virtual_styler_start_pause",
                "command_topic": f"{BASE_TOPIC}/start_pause/command",
                "payload_press": "PRESS",
                "icon": "mdi:play-pause",
            },
        ),
        component(
            "binary_sensor",
            "pauseable_virtual_styler_remote_start",
            {
                "name": "Remote Start",
                "unique_id": "pauseable_virtual_styler_remote_start",
                "default_entity_id": "binary_sensor.pauseable_virtual_styler_remote_start",
                "state_topic": f"{BASE_TOPIC}/remote_start/state",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:remote",
            },
        ),
        component(
            "sensor",
            "pauseable_virtual_styler_status",
            {
                "name": "Current Status",
                "unique_id": "pauseable_virtual_styler_status",
                "default_entity_id": "sensor.pauseable_virtual_styler_status",
                "state_topic": f"{BASE_TOPIC}/status/state",
                "icon": "mdi:tumble-dryer",
            },
        ),
        component(
            "sensor",
            "pauseable_virtual_styler_remaining_time",
            {
                "name": "Remaining Time",
                "unique_id": "pauseable_virtual_styler_remaining_time",
                "default_entity_id": "sensor.pauseable_virtual_styler_remaining_time",
                "state_topic": f"{BASE_TOPIC}/remaining/state",
                "unit_of_measurement": "s",
                "device_class": "duration",
                "icon": "mdi:timer-outline",
            },
        ),
        component(
            "light",
            "pauseable_virtual_styler_display",
            {
                "name": "Display",
                "unique_id": "pauseable_virtual_styler_display",
                "default_entity_id": "light.pauseable_virtual_styler_display",
                "state_topic": f"{BASE_TOPIC}/display/state",
                "command_topic": f"{BASE_TOPIC}/display/command",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:monitor-shimmer",
            },
        ),
        component(
            "event",
            "pauseable_virtual_styler_notification",
            {
                "name": "Notification",
                "unique_id": "pauseable_virtual_styler_notification",
                "default_entity_id": "event.pauseable_virtual_styler_notification",
                "state_topic": f"{BASE_TOPIC}/notification/event",
                "event_types": ["styling_is_complete", "error_has_occurred"],
                "icon": "mdi:bell-check",
            },
        ),
    ]


def publish_virtual_discovery(client):
    for topic, payload in discovery_messages():
        client.publish_mqtt(topic, payload, retain=True)

    client.publish_mqtt(AVAILABILITY_TOPIC, "online", retain=True)
    initial_states = {
        f"{BASE_TOPIC}/power/state": "OFF",
        f"{BASE_TOPIC}/operation/state": "ready",
        f"{BASE_TOPIC}/remote_start/state": "ON",
        f"{BASE_TOPIC}/status/state": "idle",
        f"{BASE_TOPIC}/remaining/state": "0",
        f"{BASE_TOPIC}/display/state": "OFF",
    }
    for topic, payload in initial_states.items():
        client.publish_mqtt(topic, payload, retain=True)


def run_virtual_cycle(client, cycle_seconds, event_id, sleep=time.sleep):
    state_updates = {
        f"{BASE_TOPIC}/power/state": "ON",
        f"{BASE_TOPIC}/operation/state": "warm",
        f"{BASE_TOPIC}/status/state": "warming",
        f"{BASE_TOPIC}/display/state": "OFF",
    }
    for topic, payload in state_updates.items():
        client.publish_mqtt(topic, payload, retain=True)

    for remaining in range(cycle_seconds, 0, -1):
        client.publish_mqtt(
            f"{BASE_TOPIC}/remaining/state", str(remaining), retain=True
        )
        sleep(1)

    client.publish_mqtt(f"{BASE_TOPIC}/remaining/state", "0", retain=True)
    client.publish_mqtt(f"{BASE_TOPIC}/status/state", "complete", retain=True)
    client.publish_mqtt(f"{BASE_TOPIC}/power/state", "OFF", retain=True)
    client.publish_mqtt(f"{BASE_TOPIC}/display/state", "ON", retain=True)
    client.publish_mqtt(
        f"{BASE_TOPIC}/notification/event",
        {"event_type": "styling_is_complete", "event_id": event_id},
        retain=False,
    )


def normalized_states(values):
    return {str(value).strip().lower() for value in values}


def state_name(state):
    return str((state or {}).get("state", "")).strip().lower()


def event_type(state):
    return str((state or {}).get("attributes", {}).get("event_type", "")).lower()


def turn_on_optional_display(client, entity_id):
    if not entity_id:
        return
    domain = entity_id.split(".", 1)[0]
    if domain not in {"light", "switch"}:
        raise ValueError("display_entity_id는 light 또는 switch 엔티티여야 합니다.")
    client.call_service(domain, "turn_on", {"entity_id": entity_id})


def run_thinq_cycle(client, config, sleep=time.sleep, monotonic=time.monotonic):
    remote_id = str(config.get("remote_start_entity_id", "")).strip()
    if remote_id:
        ready_states = normalized_states(
            config.get("remote_start_ready_states", ["on"])
        )
        current = state_name(client.get_state(remote_id))
        if current not in ready_states:
            raise RuntimeError(
                f"ThinQ 원격 시작이 준비되지 않았습니다: {remote_id}={current}"
            )

    power_id = str(config.get("power_entity_id", "")).strip()
    if power_id:
        client.call_service("switch", "turn_on", {"entity_id": power_id})

    startup_delay = float(config.get("startup_delay_seconds", 2))
    if startup_delay > 0:
        sleep(startup_delay)

    operation_id = str(config["operation_entity_id"]).strip()
    client.call_service(
        "select",
        "select_option",
        {"entity_id": operation_id, "option": str(config["operation_option"])},
    )

    status_id = str(config.get("status_entity_id", "")).strip()
    initial_status = state_name(client.get_state(status_id)) if status_id else None
    status_changed = False

    completion_event_id = str(config.get("completion_event_entity_id", "")).strip()
    initial_event_state = None
    if completion_event_id:
        initial_event_state = state_name(client.get_state(completion_event_id))

    client.call_service(
        "button", "press", {"entity_id": str(config["start_entity_id"]).strip()}
    )

    complete_states = normalized_states(config.get("complete_states", []))
    error_states = normalized_states(config.get("error_states", ["error"]))
    complete_event_type = str(
        config.get("completion_event_type", "styling_is_complete")
    ).lower()
    error_event_type = str(config.get("error_event_type", "error_has_occurred")).lower()
    timeout_seconds = int(config.get("timeout_seconds", 7200))
    poll_seconds = max(1, int(config.get("poll_interval_seconds", 5)))
    deadline = monotonic() + timeout_seconds

    while monotonic() < deadline:
        if status_id:
            status = state_name(client.get_state(status_id))
            if status != initial_status:
                status_changed = True
            if status in error_states:
                raise RuntimeError(f"ThinQ 스타일러 오류 상태: {status}")
            if status_changed and status in complete_states:
                turn_on_optional_display(client, config.get("display_entity_id", ""))
                return

        if completion_event_id:
            event_state = client.get_state(completion_event_id)
            current_event_state = state_name(event_state)
            current_event_type = event_type(event_state)
            if current_event_state != initial_event_state:
                if current_event_type == error_event_type:
                    raise RuntimeError("ThinQ 스타일러가 오류 완료 이벤트를 보냈습니다.")
                if current_event_type == complete_event_type:
                    turn_on_optional_display(
                        client, config.get("display_entity_id", "")
                    )
                    return
        sleep(poll_seconds)

    raise TimeoutError("ThinQ 스타일러 완료 확인 시간이 초과되었습니다.")


def build_client(ha_config):
    return HomeAssistantClient(ha_config["ha_url"], ha_config["ha_token"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ha-config", required=True)
    parser.add_argument("--styler-config", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("discover")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--event-id", required=True)
    args = parser.parse_args()

    ha_config = load_ha_config(Path(args.ha_config))
    styler_config = load_styler_config(Path(args.styler_config))
    client = build_client(ha_config)
    backend = styler_config.get("backend", "virtual").lower()

    if args.command == "discover":
        if backend == "virtual":
            publish_virtual_discovery(client)
            print("STYLER_VIRTUAL_DISCOVERY_COMPLETE")
        else:
            print("STYLER_THINQ_MAPPING_READY")
        return

    if backend == "virtual":
        seconds = int(styler_config.get("virtual", {}).get("cycle_seconds", 15))
        run_virtual_cycle(client, seconds, args.event_id)
        print(f"STYLER_VIRTUAL_CYCLE_COMPLETE event_id={args.event_id}")
    else:
        run_thinq_cycle(client, styler_config["thinq"])
        print(f"STYLER_THINQ_CYCLE_COMPLETE event_id={args.event_id}")


if __name__ == "__main__":
    main()
