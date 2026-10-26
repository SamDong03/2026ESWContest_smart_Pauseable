import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.push_subscription_store import PushSubscriptionStore
from app.web_push import _webpush_send, send_behavior_alert, validate_subscription


class GonePushError(Exception):
    response = type("Response", (), {"status_code": 410})()


class FakeR2Storage:
    def __init__(self):
        self.objects = {}

    def put_json(self, key, payload):
        self.objects[key] = payload

    def get_json(self, key):
        return self.objects.get(key)

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]

    def delete_object(self, key):
        self.objects.pop(key, None)


class WebPushTest(unittest.IsolatedAsyncioTestCase):
    def test_push_requests_high_urgency(self):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-subscription",
            "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
        }
        with (
            patch.dict(os.environ, {
                "PAUSEABLE_VAPID_PRIVATE_KEY": "private",
                "PAUSEABLE_VAPID_SUBJECT": "mailto:test@example.com",
            }),
            patch("pywebpush.webpush") as sender,
        ):
            _webpush_send(subscription, "{}")
            self.assertEqual(sender.call_args.kwargs["headers"], {"Urgency": "high"})

    async def test_send_behavior_alert_and_remove_expired_subscription(self):
        with TemporaryDirectory() as directory:
            store = PushSubscriptionStore(local_dir=Path(directory))
            subscription = {
                "endpoint": "https://fcm.googleapis.com/fcm/send/test-subscription",
                "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
            }
            store.save("byunwoojin", subscription)
            alert = {
                "alert_id": "repeated-001",
                "alert_type": "repetitive_behavior",
                "risk_level": "caution",
            }
            with (
                patch.dict(os.environ, {
                    "PAUSEABLE_WEB_PUSH_ENABLED": "1",
                    "PAUSEABLE_VAPID_PUBLIC_KEY": "public",
                    "PAUSEABLE_VAPID_PRIVATE_KEY": "private",
                    "PAUSEABLE_VAPID_SUBJECT": "mailto:test@example.com",
                }),
                patch("app.web_push._webpush_send") as sender,
            ):
                result = await send_behavior_alert("byunwoojin", alert, store, sound_enabled=False)
                self.assertEqual(result, {"attempted": 1, "accepted": 1})
                sent = json.loads(sender.call_args.args[1])
                self.assertEqual(sent["alert_id"], "repeated-001")
                self.assertFalse(sent["sound_enabled"])
                self.assertIn("반복 행동", sent["body"])
                self.assertNotIn("patient_id", sent)
                sender.reset_mock()
                wandering = {**alert, "alert_id": "wandering-001", "alert_type": "wandering"}
                self.assertEqual(
                    await send_behavior_alert("byunwoojin", wandering, store),
                    {"attempted": 1, "accepted": 1},
                )
                sent = json.loads(sender.call_args.args[1])
                self.assertEqual(sent["alert_id"], "wandering-001")
                self.assertIn("배회 의심", sent["body"])
                self.assertNotIn("patient_id", sent)
                sender.reset_mock()
                normal = {**alert, "risk_level": "normal"}
                self.assertEqual(
                    await send_behavior_alert("byunwoojin", normal, store),
                    {"attempted": 0, "accepted": 0},
                )
                sender.assert_not_called()
                sender.side_effect = GonePushError()
                self.assertEqual(
                    await send_behavior_alert("byunwoojin", alert, store),
                    {"attempted": 1, "accepted": 0},
                )
                self.assertEqual(store.list_for_patient("byunwoojin"), [])

    def test_endpoint_validation_blocks_local_targets(self):
        keys = {"p256dh": "A" * 87, "auth": "B" * 22}
        for endpoint in (
            "http://fcm.googleapis.com/fcm/send/test",
            "https://localhost/private",
            "https://127.0.0.1/private",
            "https://fcm.googleapis.com.evil.example/private",
            "https://fcm.googleapis.com:444/private",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_subscription({"endpoint": endpoint, "keys": keys})

    def test_r2_subscriptions_survive_store_restart_and_remain_patient_scoped(self):
        r2 = FakeR2Storage()
        with TemporaryDirectory() as directory:
            first = PushSubscriptionStore(local_dir=Path(directory), r2_storage=r2)
            subscription = {
                "endpoint": "https://fcm.googleapis.com/fcm/send/test-subscription",
                "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
            }
            first.save("byunwoojin", subscription)
            restarted = PushSubscriptionStore(local_dir=Path(directory), r2_storage=r2)
            self.assertEqual(len(restarted.list_for_patient("byunwoojin")), 1)
            self.assertEqual(restarted.list_for_patient("different-patient"), [])
            restarted.delete("byunwoojin", subscription["endpoint"])
            self.assertEqual(first.list_for_patient("byunwoojin"), [])


if __name__ == "__main__":
    unittest.main()
