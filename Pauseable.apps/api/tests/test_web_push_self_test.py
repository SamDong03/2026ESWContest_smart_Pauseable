import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.push_subscription_store import PushSubscriptionStore
from app.notification_preferences import NotificationPreferenceStore
from tests.test_web_push import FakeR2Storage, GonePushError


PATIENT = "byunwoojin"
PREFIX = f"/api/patients/{PATIENT}/push"
ENDPOINT = "https://fcm.googleapis.com/fcm/send/browser-one-test"
OTHER = "https://fcm.googleapis.com/fcm/send/browser-two-test"


class WebPushSelfTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = PushSubscriptionStore(local_dir=Path(self.directory.name))
        self.preferences = NotificationPreferenceStore(local_dir=Path(self.directory.name) / "preferences")
        for endpoint in (ENDPOINT, OTHER):
            self.store.save(PATIENT, {
                "endpoint": endpoint, "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
            })
        main._web_push_test_results.clear()
        main._web_push_test_cooldowns.clear()
        self.addCleanup(main._web_push_test_results.clear)
        self.addCleanup(main._web_push_test_cooldowns.clear)
        for patcher in (
            patch("app.main._push_subscription_store", return_value=self.store),
            patch("app.main._notification_preferences_store", return_value=self.preferences),
            patch.dict("os.environ", {
                "PAUSEABLE_ENV": "production", "PAUSEABLE_APP_TOKEN": "web-test-app",
                "PAUSEABLE_DEVICE_TOKEN": "web-test-device", "PAUSEABLE_WORKER_TOKEN": "web-test-worker",
                "PAUSEABLE_WEB_PUSH_ENABLED": "1", "PAUSEABLE_VAPID_PUBLIC_KEY": "test-public",
                "PAUSEABLE_VAPID_PRIVATE_KEY": "test-private", "PAUSEABLE_VAPID_SUBJECT": "https://example.test",
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.headers = {"Authorization": "Bearer web-test-app"}
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def schedule(self, **overrides):
        return self.client.post(PREFIX + "/test", headers=self.headers,
                                json={"endpoint": ENDPOINT, "delay_seconds": 0, **overrides})

    def test_only_the_requested_browser_receives_test_without_safety_side_effects(self):
        self.preferences.save(PATIENT, {"safety_notifications": False, "sound_enabled": False})
        with patch("app.web_push._webpush_send") as sender, \
                patch("app.main._alert_history_store") as history, \
                patch("app.main._request_tts", new_callable=AsyncMock) as tts, \
                patch("app.main._r2_voice_training_service") as training:
            response = self.schedule()
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "scheduled")
            sender.assert_called_once()
            self.assertEqual(sender.call_args.args[0]["endpoint"], ENDPOINT)
            payload = json.loads(sender.call_args.args[1])
            self.assertEqual(payload["type"], "push_test")
            self.assertFalse(payload["sound_enabled"])
            self.assertNotIn("patient_id", payload)
            result = self.client.get(PREFIX + "/test/" + response.json()["test_id"], headers=self.headers)
            self.assertEqual(result.json()["status"], "accepted")
            self.assertEqual(result.json()["attempted"], 1)
            self.assertEqual(result.json()["accepted"], 1)
            self.assertNotIn(ENDPOINT, response.text + result.text)
            history.assert_not_called()
            tts.assert_not_called()
            training.assert_not_called()

    def test_app_auth_is_required_for_schedule_and_result(self):
        for method, path, body in (
            ("POST", PREFIX + "/test", {"endpoint": ENDPOINT}),
            ("GET", PREFIX + "/test/web-push-test-example", None),
        ):
            with self.subTest(method=method):
                self.assertEqual(self.client.request(method, path, json=body).status_code, 401)
                for token in ("web-test-device", "web-test-worker"):
                    self.assertEqual(self.client.request(method, path, json=body,
                        headers={"Authorization": "Bearer " + token}).status_code, 403)

    def test_unknown_patient_unregistered_endpoint_and_disabled_server_do_not_send(self):
        with patch("app.web_push._webpush_send") as sender:
            self.assertEqual(self.client.post("/api/patients/other/push/test", headers=self.headers,
                                             json={"endpoint": ENDPOINT}).status_code, 404)
            for endpoint in ("https://localhost/private", "https://fcm.googleapis.com/fcm/send/not-registered"):
                self.assertEqual(self.schedule(endpoint=endpoint).status_code, 404)
            with patch("app.main.web_push_is_configured", return_value=False):
                self.assertEqual(self.schedule().status_code, 503)
            sender.assert_not_called()

    def test_strict_delay_and_extra_fields_are_rejected(self):
        with patch("app.web_push._webpush_send") as sender:
            for delay in (-1, 16, True, "10", 1.5):
                self.assertEqual(self.schedule(delay_seconds=delay).status_code, 422)
            self.assertEqual(self.schedule(unexpected="value").status_code, 422)
            sender.assert_not_called()

    def test_repeated_tests_are_limited_and_results_expire(self):
        with patch("app.web_push._webpush_send") as sender:
            first = self.schedule()
            second = self.schedule()
            self.assertEqual(second.status_code, 429)
            self.assertEqual(second.headers["Retry-After"], "30")
            sender.assert_called_once()
            test_id = first.json()["test_id"]
            main._web_push_test_results[test_id]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
            self.assertEqual(self.client.get(PREFIX + "/test/" + test_id, headers=self.headers).status_code, 404)

    def test_unsubscribe_during_delay_prevents_delivery(self):
        async def withdraw(_delay):
            self.store.delete(PATIENT, ENDPOINT)

        with patch("app.main.asyncio.sleep", side_effect=withdraw) as sleep, \
                patch("app.web_push._webpush_send") as sender:
            response = self.schedule(delay_seconds=10)
            sleep.assert_called_once_with(10)
            sender.assert_not_called()
            result = self.client.get(PREFIX + "/test/" + response.json()["test_id"], headers=self.headers).json()
            self.assertEqual((result["status"], result["attempted"]), ("skipped", 0))

    def test_delivery_failure_is_reported_and_only_expired_target_is_removed(self):
        with patch("app.web_push._webpush_send", side_effect=GonePushError()):
            response = self.schedule()
        result = self.client.get(PREFIX + "/test/" + response.json()["test_id"], headers=self.headers).json()
        self.assertEqual((result["status"], result["attempted"], result["accepted"]), ("failed", 1, 0))
        self.assertIsNone(self.store.get(PATIENT, ENDPOINT))
        self.assertIsNotNone(self.store.get(PATIENT, OTHER))

    def test_r2_lookup_survives_restart_and_enforces_patient_and_endpoint(self):
        r2 = FakeR2Storage()
        store = PushSubscriptionStore(local_dir=Path(self.directory.name), r2_storage=r2)
        subscription = {"endpoint": ENDPOINT, "keys": {"p256dh": "A" * 87, "auth": "B" * 22}}
        store.save(PATIENT, subscription)
        restored = PushSubscriptionStore(local_dir=Path(self.directory.name), r2_storage=r2)
        self.assertEqual(restored.get(PATIENT, ENDPOINT)["endpoint"], ENDPOINT)
        self.assertIsNone(restored.get("other", ENDPOINT))
        self.assertIsNone(restored.get(PATIENT, OTHER))


if __name__ == "__main__":
    unittest.main()
