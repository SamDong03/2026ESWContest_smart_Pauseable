import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.alert_history_store import AlertHistoryStore
from app.door_event_store import DoorEventStore
from app.main import app
from app.native_push_store import NativePushStore
from app.notification_preferences import NotificationPreferenceStore


TOKEN_A = "test-device-a:" + "A" * 140
TOKEN_B = "test-device-b:" + "B" * 140
PATIENT = "byunwoojin"
PREFIX = f"/api/patients/{PATIENT}/native-push"


class NativePushApiTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = NativePushStore(local_dir=Path(directory.name) / "tokens")
        self.alert_store = AlertHistoryStore(local_dir=Path(directory.name) / "alerts")
        self.door_store = DoorEventStore(local_dir=Path(directory.name) / "photos")
        self.preferences = NotificationPreferenceStore(local_dir=Path(directory.name) / "preferences")
        self.preferences.save(PATIENT, {"safety_notifications": True, "sound_enabled": True})
        for target, kwargs in (
            ("app.main._native_push_store", {"return_value": self.store}),
            ("app.main._alert_history_store", {"return_value": self.alert_store}),
            ("app.main._door_event_store", {"return_value": self.door_store}),
            ("app.main._notification_preferences_store", {"return_value": self.preferences}),
            ("app.main.native_push_is_configured", {"return_value": True}),
            ("app.native_push.is_configured", {"return_value": True}),
            ("app.main.web_push_is_configured", {"return_value": False}),
            ("app.main._alert_websockets.broadcast", {"new_callable": AsyncMock}),
        ):
            patched = patch(target, **kwargs)
            patched.start()
            self.addCleanup(patched.stop)
        environment = patch.dict(os.environ, {
            "PAUSEABLE_ENV": "production",
            "PAUSEABLE_APP_TOKEN": "app-test-token",
            "PAUSEABLE_DEVICE_TOKEN": "device-test-token",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.app_headers = {"Authorization": "Bearer app-test-token"}
        self.device_headers = {"Authorization": "Bearer device-test-token"}
        self.client = TestClient(app)

    def _register(self, token=TOKEN_A):
        return self.client.put(PREFIX + "/registration", headers=self.app_headers,
                               json={"token": token, "platform": "android"})

    @staticmethod
    def _decision(event_id="native-decision-001", **overrides):
        return {
            "contract_version": "1.0", "event_id": event_id,
            "occurred_at": "2026-10-05T00:00:00Z", "patient_id": PATIENT,
            "device_id": "pi5-central-01", "source": "central-atlas-app",
            "decision": "repetitive_behavior", "risk_level": "caution",
            "risk_score": 60, "message": "private patient detail must stay inside the app",
            "actions": ["notify_guardian"], **overrides,
        }

    def _upload_door(self, event_id, *, decision="EXIT", image=b"\xff\xd8test-photo\xff\xd9"):
        return self.client.post(
            "/api/devices/pi4-front-door-01/door-events",
            headers=self.device_headers,
            data={
                "event_id": event_id, "event_time": "2026-10-06T00:00:00Z",
                "decision": decision, "patient_id": PATIENT,
            },
            files={"representative": ("photo.jpg", image, "image/jpeg")},
        )

    def test_door_photo_is_stored_before_push_and_retries_do_not_resend(self):
        self._register()
        for decision in ("EXIT", "RETURN", "UNKNOWN_ACTIVE_BOTH", "NO_PASSAGE"):
            event_id = f"camera-{decision}"

            def check_saved_photo(token, **kwargs):
                self.assertEqual(token, TOKEN_A)
                stored = self.door_store.get_event(event_id)
                self.assertIsNotNone(stored)
                self.assertEqual(self.door_store.get_image(stored), b"\xff\xd8test-photo\xff\xd9")
                alerts = self.alert_store.list_recent(PATIENT)
                self.assertTrue(any(alert["alert_id"] == f"door-{event_id}" for alert in alerts))
                self.assertEqual(kwargs["data"], {
                    "alert_id": f"door-{event_id}", "type": "guardian_alert",
                    "related_event_id": event_id, "sound_enabled": "1",
                })
                self.assertEqual(kwargs["tag"], f"door-{event_id}")
                self.assertNotIn(PATIENT, kwargs["body"])
                self.assertNotIn("image", kwargs["data"])

            with self.subTest(decision=decision), patch(
                "app.native_push._fcm_send", side_effect=check_saved_photo,
            ) as sender:
                self.assertEqual(self._upload_door(event_id, decision=decision).status_code, 202)
                sender.assert_called_once()
                self.assertEqual(self._upload_door(event_id, decision=decision).status_code, 200)
                self.assertEqual(self._upload_door(event_id, decision=decision,
                                                 image=b"\xff\xd8different\xff\xd9").status_code, 409)
                sender.assert_called_once()

    def test_door_push_respects_preferences_and_delivery_failure_keeps_photo(self):
        self._register()
        self.preferences.save(PATIENT, {"safety_notifications": False, "sound_enabled": True})
        with patch(
            "app.native_push._fcm_send",
        ) as sender:
            self.assertEqual(self._upload_door("door-disabled").status_code, 202)
            sender.assert_not_called()
        self.preferences.save(PATIENT, {"safety_notifications": True, "sound_enabled": False})
        with patch(
            "app.native_push._fcm_send",
        ) as sender:
            self.assertEqual(self._upload_door("door-silent").status_code, 202)
            sender.assert_called_once()
            self.assertFalse(sender.call_args.kwargs["sound_enabled"])
            self.assertEqual(sender.call_args.kwargs["data"]["sound_enabled"], "0")
        with patch("app.native_push._fcm_send", side_effect=RuntimeError("network failure")):
            self.assertEqual(self._upload_door("door-failed-push").status_code, 202)
        self.assertIsNotNone(self.door_store.get_event("door-failed-push"))

    def test_door_upload_without_fcm_and_invalid_images_do_not_send(self):
        self._register()
        with patch("app.main.native_push_is_configured", return_value=False), patch(
            "app.native_push._fcm_send",
        ) as sender:
            self.assertEqual(self._upload_door("door-fcm-off").status_code, 202)
            sender.assert_not_called()
        with patch("app.native_push._fcm_send") as sender:
            self.assertEqual(self._upload_door("door-invalid-image", image=b"not a JPEG").status_code, 415)
            sender.assert_not_called()
        self.assertIsNone(self.door_store.get_event("door-invalid-image"))

    def test_all_native_routes_require_app_auth(self):
        operations = (
            ("GET", "/config", None),
            ("PUT", "/registration", {"token": TOKEN_A, "platform": "android"}),
            ("DELETE", "/registration", {"token": TOKEN_A}),
            ("POST", "/test", {"token": TOKEN_A}),
        )
        for method, suffix, body in operations:
            with self.subTest(method=method):
                self.assertEqual(self.client.request(method, PREFIX + suffix, json=body).status_code, 401)
                self.assertEqual(self.client.request(method, PREFIX + suffix,
                                                     headers=self.device_headers, json=body).status_code, 403)

    def test_registration_is_idempotent_and_can_be_withdrawn(self):
        response = self.client.get(PREFIX + "/config", headers=self.app_headers)
        self.assertEqual(response.json(), {"configured": True})
        first = self._register()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json(), {"registered": True})
        self.assertNotIn(TOKEN_A, first.text)
        self.assertEqual(self._register().status_code, 200)
        self.assertEqual(len(self.store.list_for_patient(PATIENT)), 1)
        for _ in range(2):
            self.assertEqual(self.client.request("DELETE", PREFIX + "/registration",
                                                 headers=self.app_headers, json={"token": TOKEN_A}).status_code, 204)
        self.assertEqual(self.store.list_for_patient(PATIENT), [])

    def test_disabled_fcm_unknown_patients_and_bad_tokens(self):
        with patch("app.main.native_push_is_configured", return_value=False):
            self.assertEqual(self.client.get(PREFIX + "/config", headers=self.app_headers).json(),
                             {"configured": False})
            self.assertEqual(self._register().status_code, 503)
            self.assertEqual(self.client.post(PREFIX + "/test", headers=self.app_headers,
                                              json={"token": TOKEN_A}).status_code, 503)
        self.assertEqual(self.client.get("/api/patients/other-patient/native-push/config",
                                         headers=self.app_headers).status_code, 404)
        bad_token = TOKEN_A + "\n"
        invalid = self._register(bad_token)
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn(TOKEN_A, invalid.text)
        self.assertEqual(self.client.put(PREFIX + "/registration", headers=self.app_headers,
                                         json={"token": TOKEN_A, "platform": "ios"}).status_code, 422)

    def test_manual_test_remains_available_but_honors_sound_off(self):
        self._register()
        self.preferences.save(PATIENT, {"safety_notifications": False, "sound_enabled": False})
        with patch("app.native_push._fcm_send") as sender:
            response = self.client.post(PREFIX + "/test", headers=self.app_headers, json={"token": TOKEN_A})
            self.assertEqual(response.status_code, 200)
            sender.assert_called_once()
            self.assertFalse(sender.call_args.kwargs["sound_enabled"])
            self.assertEqual(sender.call_args.kwargs["data"]["sound_enabled"], "0")

    def test_registration_limit_allows_existing_token_refresh(self):
        for index in range(8):
            self.store.save(PATIENT, f"device-{index}:" + "A" * 140)
        self.assertEqual(self._register().status_code, 409)
        self.assertEqual(self._register("device-0:" + "A" * 140).status_code, 200)

    def test_connectivity_test_sends_to_only_the_registered_requested_token(self):
        self._register(TOKEN_A)
        self._register(TOKEN_B)
        with patch("app.native_push._fcm_send") as sender:
            unregistered = self.client.post(PREFIX + "/test", headers=self.app_headers,
                                             json={"token": "unknown-device:" + "C" * 140})
            self.assertEqual(unregistered.status_code, 404)
            sender.assert_not_called()
            result = self.client.post(PREFIX + "/test", headers=self.app_headers,
                                      json={"token": TOKEN_A})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), {"attempted": 1, "accepted": 1})
            sender.assert_called_once()
            self.assertEqual(sender.call_args.args, (TOKEN_A,))
            self.assertEqual(sender.call_args.kwargs["data"], {"type": "push_test", "sound_enabled": "1"})
            self.assertEqual(sender.call_args.kwargs["body"], "알림 연결 시험입니다.")
            self.assertNotIn(TOKEN_A, result.text)

    def test_unique_behavior_decisions_send_after_history_and_duplicates_do_not_send(self):
        self._register()
        event = self._decision()

        def check_history(token, **kwargs):
            self.assertEqual(token, TOKEN_A)
            saved = self.alert_store.list_recent(PATIENT)
            self.assertEqual(saved[0]["alert_id"], event["event_id"])
            self.assertEqual(kwargs["data"], {
                "alert_id": event["event_id"], "type": "guardian_alert", "sound_enabled": "1",
            })
            self.assertNotIn("private patient", kwargs["body"])

        with patch("app.native_push._fcm_send", side_effect=check_history) as sender:
            self.assertEqual(self.client.post("/api/events/decisions", headers=self.device_headers,
                                              json=event).status_code, 202)
            sender.assert_called_once()
            duplicate = self.client.post("/api/events/decisions", headers=self.device_headers, json=event)
            self.assertEqual(duplicate.status_code, 200)
            self.assertTrue(duplicate.json()["duplicate"])
            sender.assert_called_once()
            conflict = self.client.post("/api/events/decisions", headers=self.device_headers,
                                        json={**event, "message": "different"})
            self.assertEqual(conflict.status_code, 409)
            sender.assert_called_once()

    def test_connectivity_test_delay_is_bounded_and_rechecks_withdrawal(self):
        self._register()
        with (
            patch("app.main.asyncio.sleep", new_callable=AsyncMock) as sleep,
            patch("app.native_push._fcm_send") as sender,
        ):
            result = self.client.post(PREFIX + "/test", headers=self.app_headers,
                                      json={"token": TOKEN_A, "delay_seconds": 10})
            self.assertEqual(result.json(), {"attempted": 1, "accepted": 1})
            sleep.assert_awaited_once_with(10)
            sender.assert_called_once()
            for delay in (-1, 16, 1.5, True):
                response = self.client.post(PREFIX + "/test", headers=self.app_headers,
                                            json={"token": TOKEN_A, "delay_seconds": delay})
                self.assertEqual(response.status_code, 422)
            sender.reset_mock()

            async def withdraw_during_delay(_seconds):
                self.store.delete(PATIENT, TOKEN_A)

            sleep.side_effect = withdraw_during_delay
            withdrawn = self.client.post(PREFIX + "/test", headers=self.app_headers,
                                         json={"token": TOKEN_A, "delay_seconds": 10})
            self.assertEqual(withdrawn.status_code, 404)
            sender.assert_not_called()

    def test_wandering_sends_but_no_notify_recovery_and_raw_ha_do_not(self):
        self._register()
        with patch("app.native_push._fcm_send") as sender:
            event = self._decision("wandering-001", decision="wandering_suspected", risk_level="danger")
            self.assertEqual(self.client.post("/api/events/decisions", headers=self.device_headers,
                                              json=event).status_code, 202)
            sender.assert_called_once()
            sender.reset_mock()
            for event in (
                self._decision("no-notify-001", actions=["control_appliance"]),
                self._decision("recovery-001", decision="normal", risk_level="normal"),
                self._decision("unknown-001", decision="unknown", risk_level="unknown"),
            ):
                self.assertEqual(self.client.post("/api/events/decisions", headers=self.device_headers,
                                                  json=event).status_code, 202)
            with patch("app.main._request_tts", new_callable=AsyncMock, return_value={"status": "accepted"}):
                raw_ha = self.client.post("/api/events/ha", headers=self.device_headers, json={
                    "event_id": "raw-ha-001", "occurred_at": "2026-10-05T00:01:00Z",
                    "patient_id": PATIENT, "entity_id": "binary_sensor.front_door", "state": "on",
                })
                self.assertEqual(raw_ha.status_code, 200)
            sender.assert_not_called()

    def test_push_failure_does_not_reject_durable_decision(self):
        self._register()
        with patch("app.native_push._fcm_send", side_effect=RuntimeError("network failure")):
            response = self.client.post("/api/events/decisions", headers=self.device_headers,
                                         json=self._decision())
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.alert_store.list_recent(PATIENT)), 1)

    def test_guardian_preferences_disable_push_and_control_silent_channel(self):
        self._register()
        preferences_url = "/api/guardians/me/preferences"
        preferences_body = {"safety_notifications": False, "sound_enabled": False}
        for method in ("GET", "PUT"):
            with self.subTest(method=method):
                body = preferences_body if method == "PUT" else None
                self.assertEqual(self.client.request(method, preferences_url, json=body).status_code, 401)
                self.assertEqual(self.client.request(method, preferences_url, headers=self.device_headers,
                                                     json=body).status_code, 403)
        self.assertEqual(self.client.get(preferences_url, headers=self.app_headers).status_code, 200)
        update = self.client.put(preferences_url, headers=self.app_headers, json=preferences_body)
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json(), preferences_body)
        with patch("app.native_push._fcm_send") as sender:
            response = self.client.post("/api/events/decisions", headers=self.device_headers,
                                         json=self._decision("notifications-off"))
            self.assertEqual(response.status_code, 202)
            sender.assert_not_called()
            self.assertEqual(len(self.alert_store.list_recent(PATIENT)), 1)
        update = self.client.put(preferences_url, headers=self.app_headers,
                                  json={"safety_notifications": True, "sound_enabled": False})
        self.assertEqual(update.status_code, 200)
        with patch("app.native_push._fcm_send") as sender:
            response = self.client.post("/api/events/decisions", headers=self.device_headers,
                                         json=self._decision("silent-notification"))
            self.assertEqual(response.status_code, 202)
            sender.assert_called_once()
            self.assertFalse(sender.call_args.kwargs["sound_enabled"])
            self.assertEqual(sender.call_args.kwargs["data"]["sound_enabled"], "0")


if __name__ == "__main__":
    unittest.main()
