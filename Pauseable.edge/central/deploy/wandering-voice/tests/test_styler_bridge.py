import json
import pathlib
import tempfile
import unittest

import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import styler_bridge as bridge


class FakeClient:
    def __init__(self, states=None):
        self.calls = []
        self.states = {key: list(value) for key, value in (states or {}).items()}

    def publish_mqtt(self, topic, payload, retain=False):
        self.calls.append(("mqtt", topic, payload, retain))

    def call_service(self, domain, service, data):
        self.calls.append(("service", domain, service, data))

    def get_state(self, entity_id):
        values = self.states[entity_id]
        if len(values) > 1:
            return values.pop(0)
        return values[0]


class StylerBridgeTest(unittest.TestCase):
    def test_virtual_discovery_registers_thinq_shaped_entities(self):
        client = FakeClient()
        bridge.publish_virtual_discovery(client)
        discovery = [call for call in client.calls if call[1].endswith("/config")]
        self.assertEqual(len(discovery), 8)
        payloads = [call[2] for call in discovery]
        entity_ids = {payload["default_entity_id"] for payload in payloads}
        self.assertIn("switch.pauseable_virtual_styler_power", entity_ids)
        self.assertIn("event.pauseable_virtual_styler_notification", entity_ids)
        self.assertTrue(all(call[3] for call in discovery))

    def test_virtual_cycle_warms_completes_and_lights_display(self):
        client = FakeClient()
        sleeps = []
        bridge.run_virtual_cycle(client, 2, "evt-1", sleep=sleeps.append)

        published = {(call[1], json.dumps(call[2], sort_keys=True) if isinstance(call[2], dict) else call[2]) for call in client.calls}
        self.assertIn((f"{bridge.BASE_TOPIC}/status/state", "warming"), published)
        self.assertIn((f"{bridge.BASE_TOPIC}/status/state", "complete"), published)
        self.assertIn((f"{bridge.BASE_TOPIC}/display/state", "ON"), published)
        self.assertIn((f"{bridge.BASE_TOPIC}/remaining/state", "2"), published)
        self.assertIn((f"{bridge.BASE_TOPIC}/remaining/state", "0"), published)
        completion = [call for call in client.calls if call[1].endswith("/notification/event")]
        self.assertEqual(completion[0][2]["event_type"], "styling_is_complete")
        self.assertEqual(completion[0][2]["event_id"], "evt-1")
        self.assertEqual(sleeps, [1, 1])

    def test_thinq_cycle_checks_remote_start_and_calls_entities(self):
        states = {
            "binary_sensor.styler_remote_start": [{"state": "on"}],
            "sensor.styler_status": [
                {"state": "running"},
                {"state": "running"},
                {"state": "complete"},
            ],
        }
        client = FakeClient(states)
        times = iter([0, 0, 1])
        config = {
            "remote_start_entity_id": "binary_sensor.styler_remote_start",
            "power_entity_id": "switch.styler_power",
            "operation_entity_id": "select.styler_operation",
            "operation_option": "warm",
            "start_entity_id": "button.styler_operation",
            "status_entity_id": "sensor.styler_status",
            "complete_states": ["complete"],
            "poll_interval_seconds": 1,
            "timeout_seconds": 30,
            "startup_delay_seconds": 0,
            "display_entity_id": "light.styler_display",
        }
        bridge.run_thinq_cycle(
            client, config, sleep=lambda _: None, monotonic=lambda: next(times)
        )
        services = [call[1:3] for call in client.calls if call[0] == "service"]
        self.assertEqual(
            services,
            [
                ("switch", "turn_on"),
                ("select", "select_option"),
                ("button", "press"),
                ("light", "turn_on"),
            ],
        )

    def test_thinq_cycle_fails_closed_when_remote_start_is_off(self):
        client = FakeClient(
            {"binary_sensor.styler_remote_start": [{"state": "off"}]}
        )
        with self.assertRaisesRegex(RuntimeError, "원격 시작"):
            bridge.run_thinq_cycle(
                client,
                {
                    "remote_start_entity_id": "binary_sensor.styler_remote_start",
                    "operation_entity_id": "select.styler_operation",
                    "operation_option": "warm",
                    "start_entity_id": "button.styler_operation",
                    "status_entity_id": "sensor.styler_status",
                },
                sleep=lambda _: None,
            )
        self.assertFalse(any(call[0] == "service" for call in client.calls))

    def test_thinq_does_not_accept_a_stale_complete_status(self):
        states = {
            "sensor.styler_status": [
                {"state": "complete"},
                {"state": "complete"},
                {"state": "running"},
                {"state": "complete"},
            ],
        }
        client = FakeClient(states)
        times = iter([0, 0, 1, 2])
        bridge.run_thinq_cycle(
            client,
            {
                "operation_entity_id": "select.styler_operation",
                "operation_option": "warm",
                "start_entity_id": "button.styler_operation",
                "status_entity_id": "sensor.styler_status",
                "complete_states": ["complete"],
                "startup_delay_seconds": 0,
                "poll_interval_seconds": 1,
                "timeout_seconds": 30,
            },
            sleep=lambda _: None,
            monotonic=lambda: next(times),
        )
        self.assertEqual(len(client.states["sensor.styler_status"]), 1)

    def test_config_requires_thinq_completion_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "backend": "thinq",
                        "thinq": {
                            "operation_entity_id": "select.styler_operation",
                            "operation_option": "warm",
                            "start_entity_id": "button.styler_operation",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "완료 확인"):
                bridge.load_styler_config(path)


if __name__ == "__main__":
    unittest.main()
