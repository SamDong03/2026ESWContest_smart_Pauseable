import os
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from firebase_admin import exceptions, messaging

from app import native_push
from app.native_push_store import NativePushStore, validate_device_token


TOKEN_A = "test-device-a:" + "A" * 140
TOKEN_B = "test-device-b:" + "B" * 140


class FakeR2Storage:
    def __init__(self):
        self.objects = {}

    def put_json(self, key, payload):
        self.objects[key] = dict(payload)

    def get_json(self, key):
        return self.objects.get(key)

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]

    def delete_object(self, key):
        self.objects.pop(key, None)


class NativePushTest(unittest.IsolatedAsyncioTestCase):
    def test_local_and_r2_registration_survive_restart_and_are_scoped(self):
        for r2 in (None, FakeR2Storage()):
            with self.subTest(r2=bool(r2)), TemporaryDirectory() as directory:
                first = NativePushStore(local_dir=Path(directory), r2_storage=r2)
                self.assertTrue(first.save("byunwoojin", TOKEN_A))
                self.assertFalse(first.save("byunwoojin", TOKEN_A))
                first.save("other-patient", TOKEN_B)
                restarted = NativePushStore(local_dir=Path(directory), r2_storage=r2)
                records = restarted.list_for_patient("byunwoojin")
                self.assertEqual([item["token"] for item in records], [TOKEN_A])
                self.assertIsNone(restarted.get("other-patient", TOKEN_A))
                keys = list(r2.objects) if r2 else [str(path) for path in Path(directory).rglob("*.json")]
                self.assertTrue(keys)
                self.assertFalse(any(TOKEN_A in key or TOKEN_B in key for key in keys))
                restarted.delete("byunwoojin", TOKEN_A)
                restarted.delete("byunwoojin", TOKEN_A)
                self.assertEqual(first.list_for_patient("byunwoojin"), [])
                self.assertEqual(len(first.list_for_patient("other-patient")), 1)

    def test_validation_rejects_controls_and_patient_path_traversal(self):
        for token in ("short", "A" * 4097, TOKEN_A + "\n", TOKEN_A + " ", TOKEN_A + "\x00"):
            with self.subTest(token_length=len(token)), self.assertRaises(ValueError):
                validate_device_token(token)
        with TemporaryDirectory() as directory:
            store = NativePushStore(local_dir=Path(directory))
            with self.assertRaises(ValueError):
                store.save("../outside", TOKEN_A)

    def test_sdk_payload_is_generic_and_uses_android_channel(self):
        with (
            patch("app.native_push._firebase_app", return_value=object()),
            patch("firebase_admin.messaging.send") as sender,
        ):
            native_push._fcm_send(
                TOKEN_A,
                body="새 보호자 알림이 있습니다. 앱에서 확인해 주세요.",
                data={"alert_id": "decision-001", "type": "guardian_alert"},
                tag="decision-001",
            )
        message = sender.call_args.args[0]
        self.assertEqual(message.token, TOKEN_A)
        self.assertEqual(message.notification.title, "Pauseable 알림")
        self.assertEqual(message.data, {"alert_id": "decision-001", "type": "guardian_alert"})
        self.assertEqual(message.android.priority, "high")
        self.assertEqual(message.android.ttl, timedelta(seconds=300))
        self.assertEqual(message.android.restricted_package_name, "com.pauseable.pauseable_guardian")
        self.assertEqual(message.android.notification.channel_id, "pauseable_guardian_alerts")
        self.assertEqual(message.android.notification.icon, "ic_stat_notification")
        self.assertEqual(message.android.notification.sound, "default")
        self.assertNotIn("patient_id", message.data)

    def test_invalid_config_does_not_leak_credentials_or_break_startup(self):
        native_push._firebase_app.cache_clear()
        self.addCleanup(native_push._firebase_app.cache_clear)
        credential_marker = "private-credential-marker-not-json"
        with patch.dict(os.environ, {
            "PAUSEABLE_FCM_ENABLED": "1",
            "PAUSEABLE_FIREBASE_SERVICE_ACCOUNT_JSON": credential_marker,
            "GOOGLE_APPLICATION_CREDENTIALS": "",
        }), self.assertLogs("app.native_push", level="WARNING") as logs:
            self.assertFalse(native_push.is_configured())
        self.assertNotIn(credential_marker, " ".join(logs.output))
        with patch.dict(os.environ, {"PAUSEABLE_FCM_ENABLED": "0"}):
            self.assertFalse(native_push.is_configured())

    def test_initialization_accepts_json_or_secret_file_without_network(self):
        for values, source in (
            ({"PAUSEABLE_FIREBASE_SERVICE_ACCOUNT_JSON": '{"type":"service_account"}',
              "GOOGLE_APPLICATION_CREDENTIALS": ""}, {"type": "service_account"}),
            ({"PAUSEABLE_FIREBASE_SERVICE_ACCOUNT_JSON": "",
              "GOOGLE_APPLICATION_CREDENTIALS": "/etc/secrets/firebase-admin.json"},
             "/etc/secrets/firebase-admin.json"),
        ):
            native_push._firebase_app.cache_clear()
            self.addCleanup(native_push._firebase_app.cache_clear)
            with (
                patch.dict(os.environ, {"PAUSEABLE_FCM_ENABLED": "1", **values}),
                patch("firebase_admin.credentials.Certificate") as certificate,
                patch("firebase_admin.get_app", side_effect=ValueError()),
                patch("firebase_admin.initialize_app", return_value=object()) as initialize,
            ):
                self.assertTrue(native_push.is_configured())
                certificate.assert_called_once_with(source)
                self.assertEqual(initialize.call_args.args[1], {"httpTimeout": 8})

    async def test_delivery_is_patient_scoped_and_removes_only_unregistered_tokens(self):
        with TemporaryDirectory() as directory:
            store = NativePushStore(local_dir=Path(directory))
            store.save("byunwoojin", TOKEN_A)
            store.save("other-patient", TOKEN_B)
            alert = {"alert_id": "decision-001", "alert_type": "repetitive_behavior", "risk_level": "caution"}
            with (
                patch("app.native_push.is_configured", return_value=True),
                patch("app.native_push._fcm_send") as sender,
            ):
                self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                 {"attempted": 1, "accepted": 1})
                self.assertEqual(sender.call_args.args, (TOKEN_A,))
                self.assertEqual(sender.call_args.kwargs["data"],
                                 {"alert_id": "decision-001", "type": "guardian_alert", "sound_enabled": "1"})
                sender.side_effect = exceptions.InvalidArgumentError("invalid payload " + TOKEN_A)
                with self.assertLogs("app.native_push", level="WARNING") as logs:
                    self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                     {"attempted": 1, "accepted": 0})
                self.assertNotIn(TOKEN_A, " ".join(logs.output))
                self.assertIsNotNone(store.get("byunwoojin", TOKEN_A))
                sender.side_effect = messaging.UnregisteredError("expired " + TOKEN_A)
                self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                 {"attempted": 1, "accepted": 0})
                self.assertIsNone(store.get("byunwoojin", TOKEN_A))
                self.assertIsNotNone(store.get("other-patient", TOKEN_B))

    def test_silent_sdk_payload_uses_silent_channel_without_sound_or_vibration(self):
        with (
            patch("app.native_push._firebase_app", return_value=object()),
            patch("firebase_admin.messaging.send") as sender,
        ):
            native_push._fcm_send(
                TOKEN_A, body="새 보호자 알림이 있습니다. 앱에서 확인해 주세요.",
                data={"alert_id": "silent-001", "type": "guardian_alert", "sound_enabled": "0"},
                tag="silent-001", sound_enabled=False,
            )
        message = sender.call_args.args[0]
        self.assertEqual(message.android.notification.channel_id, "pauseable_guardian_alerts_silent")
        self.assertIsNone(message.android.notification.sound)
        self.assertFalse(message.android.notification.default_sound)
        self.assertFalse(message.android.notification.default_vibrate_timings)

    async def test_only_caution_danger_behavior_alerts_are_sent(self):
        with TemporaryDirectory() as directory:
            store = NativePushStore(local_dir=Path(directory))
            store.save("byunwoojin", TOKEN_A)
            with (
                patch("app.native_push.is_configured", return_value=True),
                patch("app.native_push._fcm_send") as sender,
            ):
                for alert_type in ("repetitive_behavior", "wandering"):
                    alert = {"alert_id": "decision-001", "alert_type": alert_type, "risk_level": "danger"}
                    self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                     {"attempted": 1, "accepted": 1})
                sender.reset_mock()
                for alert_type, risk_level in (("recovery", "normal"), ("wandering", "normal"),
                                               ("door_exit", "danger")):
                    alert = {"alert_id": "ignored", "alert_type": alert_type, "risk_level": risk_level}
                    self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                     {"attempted": 0, "accepted": 0})
                sender.assert_not_called()

    async def test_store_failure_and_disabled_fcm_are_best_effort(self):
        with TemporaryDirectory() as directory:
            store = NativePushStore(local_dir=Path(directory))
            alert = {"alert_id": "decision-001", "alert_type": "wandering", "risk_level": "caution"}
            with (
                patch("app.native_push.is_configured", return_value=True),
                patch.object(store, "list_for_patient", side_effect=RuntimeError("storage failure")),
                patch("app.native_push._fcm_send") as sender,
            ):
                self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                 {"attempted": 0, "accepted": 0})
                sender.assert_not_called()
            with patch("app.native_push.is_configured", return_value=False):
                self.assertEqual(await native_push.send_behavior_alert("byunwoojin", alert, store),
                                 {"attempted": 0, "accepted": 0})


if __name__ == "__main__":
    unittest.main()
