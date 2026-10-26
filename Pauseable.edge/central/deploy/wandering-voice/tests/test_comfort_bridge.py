import json
import pathlib
import tempfile
import unittest

import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import comfort_bridge as bridge


class FakeClient:
    def __init__(self):
        self.calls = []

    def publish_mqtt(self, topic, payload, retain=False):
        self.calls.append(("mqtt", topic, payload, retain))

    def call_service(self, domain, service, data):
        self.calls.append(("service", domain, service, data))


class ComfortBridgeTest(unittest.TestCase):
    def setUp(self):
        self.virtual_config = {
            "water_purifier": {
                "enabled": True,
                "backend": "virtual",
                "virtual": {"dispense_seconds": 3, "amount_ml": 150},
            },
            "tiiun": {
                "enabled": True,
                "backend": "virtual",
                "virtual": {"brightness": 80},
            },
        }

    def test_discovery_registers_water_and_tiiun_entities(self):
        client = FakeClient()
        bridge.publish_discovery(client, self.virtual_config)

        discovery = [call for call in client.calls if call[1].endswith("/config")]
        self.assertEqual(len(discovery), 9)
        entity_ids = {call[2]["default_entity_id"] for call in discovery}
        self.assertIn("button.pauseable_virtual_water_purifier_dispense", entity_ids)
        self.assertIn("light.pauseable_virtual_tiiun_grow_light", entity_ids)
        self.assertTrue(all(call[3] for call in discovery))

    def test_virtual_water_dispenses_and_announces_ready(self):
        client = FakeClient()
        sleeps = []
        bridge.run_virtual_water(
            client,
            {"dispense_seconds": 3, "amount_ml": 150},
            "evt-water",
            sleep=sleeps.append,
        )

        published = {(call[1], str(call[2])) for call in client.calls}
        self.assertIn(
            (f"{bridge.WATER_TOPIC}/status/state", "dispensing_cool_water"),
            published,
        )
        self.assertIn(
            (f"{bridge.WATER_TOPIC}/status/state", "cool_water_ready"), published
        )
        self.assertIn((f"{bridge.WATER_TOPIC}/amount/state", "150"), published)
        event = [call for call in client.calls if call[1].endswith("/notification/event")]
        self.assertEqual(event[0][2]["event_id"], "evt-water")
        self.assertEqual(event[0][2]["amount_ml"], 150)
        self.assertEqual(sleeps, [3])

    def test_virtual_tiiun_turns_on_dim_grow_light(self):
        client = FakeClient()
        bridge.run_virtual_tiiun(client, {"brightness": 80}, "evt-tiiun")

        published = {(call[1], str(call[2])) for call in client.calls}
        self.assertIn((f"{bridge.TIIUN_TOPIC}/power/state", "ON"), published)
        self.assertIn((f"{bridge.TIIUN_TOPIC}/light/state", "ON"), published)
        self.assertIn((f"{bridge.TIIUN_TOPIC}/light/brightness/state", "80"), published)
        self.assertIn(
            (f"{bridge.TIIUN_TOPIC}/status/state", "plant_care_focus"), published
        )
        event = [call for call in client.calls if call[1].endswith("/notification/event")]
        self.assertEqual(event[0][2]["event_id"], "evt-tiiun")

    def test_actual_outputs_call_only_mapped_home_assistant_entities(self):
        client = FakeClient()
        bridge.run_actual_water(
            client,
            {
                "power_entity_id": "switch.water_power",
                "action_entity_id": "button.water_dispense",
            },
        )
        bridge.run_actual_tiiun(
            client,
            {
                "power_entity_id": "switch.tiiun_power",
                "light_entity_id": "light.tiiun_grow_light",
                "brightness_pct": 30,
            },
        )

        self.assertEqual(
            [call[1:] for call in client.calls],
            [
                ("switch", "turn_on", {"entity_id": "switch.water_power"}),
                ("button", "press", {"entity_id": "button.water_dispense"}),
                ("switch", "turn_on", {"entity_id": "switch.tiiun_power"}),
                (
                    "light",
                    "turn_on",
                    {"entity_id": "light.tiiun_grow_light", "brightness_pct": 30},
                ),
            ],
        )

    def test_actual_config_requires_explicit_entity_mapping(self):
        config = {
            "water_purifier": {
                "enabled": True,
                "backend": "home_assistant",
                "home_assistant": {"action_entity_id": ""},
            },
            "tiiun": {"enabled": False, "backend": "virtual"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "comfort.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "action_entity_id"):
                bridge.load_comfort_config(path)

    def test_disabled_output_does_not_call_home_assistant(self):
        client = FakeClient()
        config = {"tiiun": {"enabled": False, "backend": "virtual"}}
        result = bridge.run_output(client, config, "tiiun", "evt-disabled")
        self.assertEqual(result, "disabled")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
