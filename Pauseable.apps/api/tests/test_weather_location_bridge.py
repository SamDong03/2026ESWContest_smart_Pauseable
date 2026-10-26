import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app import home_environment, main


WEATHER_PATH = Path(__file__).resolve().parents[3] / "Pauseable.integrations/home-assistant/weather-light-control/weather_api.py"
SPEC = importlib.util.spec_from_file_location("weather_location_bridge", WEATHER_PATH)
weather = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(weather)


class WeatherLocationBridgeTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for change in (
            patch.object(home_environment, "HOME_SETTINGS_DIR", Path(directory.name)),
            patch.object(main, "STORAGE_BACKEND", "local"),
            patch.dict("os.environ", {
                "PAUSEABLE_ENV": "production",
                "PAUSEABLE_APP_TOKEN": "region-app-test",
                "PAUSEABLE_DEVICE_TOKEN": "region-device-test",
                "PAUSEABLE_WORKER_TOKEN": "region-worker-test",
            }),
        ):
            change.start()
            self.addCleanup(change.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.app_url = "/api/patients/byunwoojin/home-environment"
        self.device_url = "/api/device/patients/byunwoojin/home-environment"
        self.guardian = {"Authorization": "Bearer region-app-test"}
        self.device = {"Authorization": "Bearer region-device-test"}

    def test_device_read_requires_device_role_and_is_read_only(self):
        self.assertEqual(self.client.get(self.device_url).status_code, 401)
        for token in ("region-app-test", "region-worker-test", "invalid-test"):
            self.assertEqual(self.client.get(self.device_url, headers={
                "Authorization": f"Bearer {token}",
            }).status_code, 403)
        response = self.client.get(self.device_url, headers=self.device)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["region"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.put(self.device_url, headers=self.device, json={}).status_code, 405)
        self.assertEqual(self.client.put(self.app_url, headers=self.device, json={
            "region_code": "1111051500",
        }).status_code, 403)
        self.assertEqual(self.client.get(
            "/api/device/patients/other-patient/home-environment", headers=self.device,
        ).status_code, 404)

    def test_guardian_save_flows_through_device_api_into_weather_grid(self):
        config = {
            "location_source": "render", "patient_id": "byunwoojin",
            "pauseable_api_base_url": "https://pauseable-api.test",
            "pauseable_device_token": "region-device-test",
        }

        def read_render(method, url, headers, **options):
            self.assertEqual(method, "GET")
            self.assertEqual(url, f"https://pauseable-api.test{self.device_url}")
            self.assertEqual(headers["Authorization"], self.device["Authorization"])
            self.assertFalse(options["follow_redirects"])
            response = self.client.get(urlsplit(url).path, headers=headers)
            return response.status_code, response.json(), response.text

        first = home_environment.region_catalog()["1111051500"]
        second = next(region for region in home_environment.region_catalog().values()
                      if (region["nx"], region["ny"]) != (first["nx"], first["ny"]))
        with patch.object(weather, "request_json", side_effect=read_render) as get, patch.object(
            weather, "get_ha_state",
        ) as ha, patch.object(weather, "set_ha_light") as light, patch.object(
            weather, "LOCATION_CONFIG_FILE",
        ) as legacy_file:
            for region in (first, second):
                saved = self.client.put(self.app_url, headers=self.guardian, json={
                    "region_code": region["code"], "auto_lighting_enabled": False,
                })
                self.assertEqual(saved.status_code, 200)
                location = weather.load_location(config)
                self.assertEqual((location["nx"], location["ny"]), (region["nx"], region["ny"]))
                self.assertEqual(location["source"], "render")
                device_region = self.client.get(self.device_url, headers=self.device).json()["region"]
                self.assertEqual(set(device_region), {"code", "province", "city", "district", "nx", "ny"})
            self.assertEqual(get.call_count, 2)
            ha.assert_not_called()
            light.assert_not_called()
            legacy_file.exists.assert_not_called()

    def test_device_reads_the_same_persistent_r2_selection(self):
        objects = {}

        class Storage:
            def get_json(self, key):
                return objects.get(key)

            def put_json(self, key, value):
                objects[key] = value

        with patch.object(main, "STORAGE_BACKEND", "r2"), patch.object(
            home_environment.R2Storage, "from_environment", return_value=Storage(),
        ):
            self.assertEqual(self.client.put(self.app_url, headers=self.guardian, json={
                "region_code": "1111051500",
            }).status_code, 200)
            with TemporaryDirectory() as fresh, patch.object(
                home_environment, "HOME_SETTINGS_DIR", Path(fresh),
            ):
                response = self.client.get(self.device_url, headers=self.device)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["is_persistent"])
                self.assertEqual(response.json()["region"]["code"], "1111051500")
                self.assertEqual(response.json()["storage_backend"], "r2")


if __name__ == "__main__":
    unittest.main()
