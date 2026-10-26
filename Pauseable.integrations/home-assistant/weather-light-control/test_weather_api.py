import json
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError

import weather_api


class WeatherApiTest(unittest.TestCase):
    def render_config(self):
        return {
            "location_source": "render",
            "pauseable_api_base_url": "https://pauseable-api.test",
            "patient_id": "byunwoojin",
            "pauseable_device_token": "private-device-test",
        }

    def render_response(self):
        return {
            "patient_id": "byunwoojin",
            "region": {"code": "1111051500", "province": "서울특별시",
                       "city": "종로구", "district": "청운효자동", "nx": 60, "ny": 127},
        }

    @patch("weather_api.request_json")
    def test_render_source_overrides_an_old_location_file(self, request):
        request.return_value = (200, self.render_response(), "")
        with patch("weather_api.LOCATION_CONFIG_FILE") as legacy, patch(
            "weather_api.get_ha_state",
        ) as ha:
            location = weather_api.load_location(self.render_config())
            self.assertEqual((location["nx"], location["ny"]), (60, 127))
            self.assertEqual(location["source"], "render")
            legacy.exists.assert_not_called()
            ha.assert_not_called()
        self.assertFalse(request.call_args.kwargs["follow_redirects"])
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer private-device-test")

    @patch("weather_api.request_json")
    def test_render_failures_never_fall_back_to_local_or_expose_private_data(self, request):
        for status in (301, 302, 401, 403, 404, 503):
            with self.subTest(status=status), patch("weather_api.get_ha_state") as ha, patch(
                "weather_api.LOCATION_CONFIG_FILE",
            ) as legacy:
                request.return_value = (status, {"secret": "private-device-test"}, "private-body-test")
                with self.assertRaises(RuntimeError) as error:
                    weather_api.load_location(self.render_config())
                self.assertNotIn("private-device-test", str(error.exception))
                self.assertNotIn("private-body-test", str(error.exception))
                legacy.exists.assert_not_called()
                ha.assert_not_called()
        request.side_effect = RuntimeError("private-device-test")
        with self.assertRaises(RuntimeError) as error:
            weather_api.load_location(self.render_config())
        self.assertNotIn("private-device-test", str(error.exception))

    @patch("weather_api.request_json")
    def test_missing_region_does_not_issue_a_light_command(self, request):
        request.return_value = (200, {"patient_id": "byunwoojin", "region": None}, "")
        with patch("weather_api.load_config", return_value=self.render_config()), patch(
            "weather_api.set_ha_light",
        ) as light, patch("weather_api.get_weather") as weather, patch("builtins.print"):
            self.assertEqual(weather_api.main(), 2)
            light.assert_not_called()
            weather.assert_not_called()

    @patch("weather_api.request_json")
    def test_render_validates_patient_and_grid_without_hardware_fallback(self, request):
        for payload in (
            {"patient_id": "different-patient", "region": self.render_response()["region"]},
            {"patient_id": "byunwoojin"},
            {"patient_id": "byunwoojin", "region": []},
            *({"patient_id": "byunwoojin", "region": dict(self.render_response()["region"], nx=value)}
              for value in (True, "60", 0, -1, 1001)),
        ):
            with self.subTest(payload=payload):
                request.return_value = (200, payload, "")
                with self.assertRaises(RuntimeError):
                    weather_api.load_location(self.render_config())

    @patch("weather_api.request_json")
    def test_render_requires_safe_configuration_before_sending_credentials(self, request):
        for overrides in (
            {"pauseable_api_base_url": "http://pauseable-api.test"},
            {"pauseable_api_base_url": "https://name:password@pauseable-api.test"},
            {"pauseable_api_base_url": "https://pauseable-api.test/?key=value"},
            {"patient_id": "../other"}, {"patient_id": ""},
            {"pauseable_device_token": ""}, {"pauseable_device_token": "bad\ntoken"},
            {"location_source": "unknown"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    weather_api.load_location(dict(self.render_config(), **overrides))
        request.assert_not_called()

    @patch("weather_api.request_json")
    def test_check_location_does_not_need_kma_or_ha_keys_or_change_lights(self, request):
        request.return_value = (200, self.render_response(), "")
        with patch.dict("os.environ", {
            "WEATHER_LOCATION_SOURCE": "render", "PATIENT_ID": "byunwoojin",
            "PAUSEABLE_API_BASE_URL": "https://pauseable-api.test",
            "PAUSEABLE_DEVICE_TOKEN": "private-device-test", "KMA_SERVICE_KEY": "", "HA_TOKEN": "",
        }), patch("weather_api.os.path.exists", return_value=False), patch(
            "weather_api.get_weather",
        ) as weather, patch("weather_api.get_sun_elevation") as sun, patch(
            "weather_api.set_ha_light",
        ) as light, patch("builtins.print") as output:
            weather_api.main(check_location=True)
            weather.assert_not_called()
            sun.assert_not_called()
            light.assert_not_called()
            self.assertNotIn("private-device-test", str(output.call_args_list))

    @patch("weather_api.request_json")
    def test_render_grid_is_used_by_the_unchanged_lighting_policy(self, request):
        request.return_value = (200, self.render_response(), "")
        config = dict(self.render_config(), ha_light_entity_id="light.tapo_l530", publish_helper_states=False)
        with patch("weather_api.load_config", return_value=config), patch(
            "weather_api.get_weather", return_value=({"SKY": "1", "PTY": "0", "TMP": "20"},
                datetime(2026, 10, 22, 12, tzinfo=weather_api.KST)),
        ) as get_weather, patch("weather_api.get_sun_elevation", return_value=30), patch(
            "weather_api.set_ha_light",
        ) as light, patch("builtins.print"):
            weather_api.main()
            self.assertEqual(get_weather.call_args.args[1:3], (60, 127))
            light.assert_called_once_with(config, "light.tapo_l530", False, 10, 4500)

    @patch("weather_api.urlopen")
    @patch("weather_api.build_opener")
    def test_render_http_transport_does_not_follow_redirects(self, opener, urlopen):
        url = "https://pauseable-api.test/location"
        opener.return_value.open.side_effect = HTTPError(url, 302, "Moved", {}, None)
        status, _, _ = weather_api.request_json("GET", url, follow_redirects=False)
        self.assertEqual(status, 302)
        urlopen.assert_not_called()
        handler = opener.call_args.args[0]
        self.assertIsNone(handler.redirect_request(None, None, 302, "Moved", {}, "https://elsewhere.test"))

    def test_lat_lon_to_kma_grid_converts_seoul_coordinates(self):
        self.assertEqual(
            weather_api.lat_lon_to_kma_grid(37.5665, 126.9780),
            (60, 127),
        )

    def test_calculate_light_uses_l530_minimum_kelvin(self):
        brightness, kelvin = weather_api.calculate_light(
            {"SKY": "4", "PTY": "1"},
            -6,
        )

        self.assertEqual(brightness, 97)
        self.assertEqual(kelvin, 2500)

    def test_should_turn_off_during_clear_daylight(self):
        self.assertFalse(
            weather_api.should_turn_on({"SKY": "1", "PTY": "0"}, 30)
        )

    def test_should_turn_on_when_sun_is_low_or_weather_is_bad(self):
        self.assertTrue(
            weather_api.should_turn_on({"SKY": "1", "PTY": "0"}, 10)
        )
        self.assertTrue(
            weather_api.should_turn_on({"SKY": "4", "PTY": "0"}, 30)
        )
        self.assertTrue(
            weather_api.should_turn_on({"SKY": "1", "PTY": "1"}, 30)
        )

    @patch("weather_api.request_json")
    def test_get_weather_selects_forecast_nearest_to_current_time(self, request_json):
        response_data = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
                "body": {
                    "items": {
                        "item": [
                            {
                                "category": category,
                                "fcstDate": date,
                                "fcstTime": time,
                                "fcstValue": value,
                            }
                            for date, time, values in [
                                ("20261011", "1000", {"SKY": "1", "PTY": "0", "TMP": "20"}),
                                ("20261011", "1100", {"SKY": "4", "PTY": "1", "TMP": "18"}),
                                ("20261012", "0000", {"SKY": "3", "PTY": "0", "TMP": "12"}),
                            ]
                            for category, value in values.items()
                        ]
                    }
                },
            }
        }
        request_json.return_value = (200, response_data, json.dumps(response_data))

        weather, forecast_time = weather_api.get_weather(
            {"kma_service_key": "test"},
            60,
            127,
            "20261011",
            "0800",
            target_time=datetime(2026, 10, 11, 10, 40, tzinfo=weather_api.KST),
        )

        self.assertEqual(weather, {"SKY": "4", "PTY": "1", "TMP": "18"})
        self.assertEqual(forecast_time.hour, 11)

    @patch("weather_api.request_json")
    def test_get_weather_does_not_expose_service_key_on_http_error(
        self,
        request_json,
    ):
        response_data = {
            "OpenAPI_ServiceResponse": {
                "cmmMsgHeader": {"returnAuthMsg": "등록되지 않은 서비스키"}
            }
        }
        request_json.return_value = (403, response_data, json.dumps(response_data))

        with self.assertRaisesRegex(RuntimeError, "등록되지 않은 서비스키") as error:
            weather_api.get_weather(
                {"kma_service_key": "SECRET_KEY"},
                60,
                127,
                "20261011",
                "0800",
            )

        self.assertNotIn("SECRET_KEY", str(error.exception))

    @patch("weather_api.LOCATION_CONFIG_FILE")
    @patch("weather_api.get_ha_state")
    def test_load_location_uses_home_assistant_when_file_is_missing(
        self,
        get_ha_state,
        location_file,
    ):
        location_file.exists.return_value = False
        get_ha_state.return_value = {
            "attributes": {"latitude": 37.5665, "longitude": 126.9780}
        }

        location = weather_api.load_location({})

        self.assertEqual((location["nx"], location["ny"]), (60, 127))
        get_ha_state.assert_called_once_with({}, "zone.home")

    @patch("weather_api.call_ha_service")
    def test_set_ha_light_uses_expected_home_assistant_payload(self, call_service):
        config = {}

        weather_api.set_ha_light(config, "light.tapo_l530", True, 55, 3000)

        call_service.assert_called_once_with(
            config,
            "light",
            "turn_on",
            {
                "entity_id": "light.tapo_l530",
                "brightness_pct": 55,
                "color_temp_kelvin": 3000,
            },
        )

    @patch("weather_api.call_ha_service")
    def test_set_ha_light_turns_off_without_brightness_payload(self, call_service):
        config = {}

        weather_api.set_ha_light(config, "light.tapo_l530", False, 55, 3000)

        call_service.assert_called_once_with(
            config,
            "light",
            "turn_off",
            {"entity_id": "light.tapo_l530"},
        )


if __name__ == "__main__":
    unittest.main()
