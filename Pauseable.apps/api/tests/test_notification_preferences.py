import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.alert_history_store import AlertHistoryStore
from app.door_event_store import DoorEventStore
from app.notification_preferences import DEFAULT_PREFERENCES, NotificationPreferenceStore


PATIENT = "byunwoojin"
URL = "/api/guardians/me/preferences"


class MemoryR2:
    def __init__(self):
        self.objects = {}

    def get_json(self, key):
        return deepcopy(self.objects.get(key))

    def put_json(self, key, payload):
        self.objects[key] = deepcopy(payload)


class NotificationPreferenceStoreTest(unittest.TestCase):
    def test_local_restart_defaults_and_patient_isolation(self):
        with TemporaryDirectory() as directory:
            first = NotificationPreferenceStore(local_dir=Path(directory))
            self.assertEqual(first.load(PATIENT), DEFAULT_PREFERENCES)
            disabled = {"safety_notifications": False, "sound_enabled": True}
            first.save(PATIENT, disabled)
            restarted = NotificationPreferenceStore(local_dir=Path(directory))
            self.assertEqual(restarted.load(PATIENT), disabled)
            self.assertEqual(restarted.load("other-patient"), DEFAULT_PREFERENCES)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_r2_restart_reads_fresh_policy_without_modifying_other_patient_objects(self):
        r2 = MemoryR2()
        r2.objects[f"patients/{PATIENT}/care-profile.json"] = {"patient_call_name": "unchanged"}
        r2.objects[f"patients/{PATIENT}/home-environment.json"] = {"region_code": "unchanged"}
        r2.objects["door-events/photo/event.json"] = {"id": "unchanged"}
        before = deepcopy(r2.objects)
        with TemporaryDirectory() as directory:
            first = NotificationPreferenceStore(local_dir=Path(directory), r2_storage=r2)
            disabled = {"safety_notifications": False, "sound_enabled": False}
            first.save(PATIENT, disabled)
            second = NotificationPreferenceStore(local_dir=Path(directory), r2_storage=r2)
            self.assertEqual(second.load(PATIENT), disabled)
            second.save(PATIENT, {"safety_notifications": True, "sound_enabled": True})
            self.assertTrue(first.for_delivery(PATIENT)["sound_enabled"])
            self.assertEqual(first.load("other-patient"), DEFAULT_PREFERENCES)
            self.assertEqual({key: r2.objects[key] for key in before}, before)

    def test_storage_failure_keeps_last_confirmed_opt_out_and_does_not_fake_a_save(self):
        r2 = MemoryR2()
        with TemporaryDirectory() as directory:
            store = NotificationPreferenceStore(local_dir=Path(directory), r2_storage=r2)
            disabled = {"safety_notifications": False, "sound_enabled": False}
            store.save(PATIENT, disabled)
            with patch.object(r2, "put_json", side_effect=OSError("unavailable")):
                with self.assertRaises(OSError):
                    store.save(PATIENT, {"safety_notifications": True, "sound_enabled": True})
            with patch.object(r2, "get_json", side_effect=OSError("unavailable")):
                self.assertEqual(store.for_delivery(PATIENT), disabled)
                self.assertEqual(store.for_delivery("no-cache-patient"), DEFAULT_PREFERENCES)
                with self.assertRaises(OSError):
                    store.load(PATIENT)

    def test_invalid_ids_and_non_boolean_storage_are_not_treated_as_valid_settings(self):
        with TemporaryDirectory() as directory:
            store = NotificationPreferenceStore(local_dir=Path(directory))
            for patient_id in ("../other", "a/b", "", "x" * 65):
                with self.assertRaises(ValueError):
                    store.load(patient_id)
            for value in ("false", 0, 1, None):
                with self.assertRaises(ValueError):
                    store.save(PATIENT, {"safety_notifications": value, "sound_enabled": False})


class NotificationPreferenceApiTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.preferences = NotificationPreferenceStore(local_dir=root / "preferences")
        self.alerts = AlertHistoryStore(local_dir=root / "alerts")
        self.photos = DoorEventStore(local_dir=root / "photos")
        self.web = AsyncMock(return_value={"attempted": 1, "accepted": 1})
        self.native = AsyncMock(return_value={"attempted": 1, "accepted": 1})
        self.door_push = AsyncMock(return_value={"attempted": 1, "accepted": 1})
        self.broadcast = AsyncMock()
        for target, value in (
            ("_notification_preferences_store", lambda: self.preferences),
            ("_alert_history_store", lambda: self.alerts),
            ("_door_event_store", lambda: self.photos),
            ("_push_subscription_store", lambda: object()),
            ("_native_push_store", lambda: object()),
            ("web_push_is_configured", lambda: True),
            ("native_push_is_configured", lambda: True),
            ("send_behavior_alert", self.web),
            ("send_native_behavior_alert", self.native),
            ("send_native_door_alert", self.door_push),
        ):
            patched = patch.object(main, target, value)
            patched.start()
            self.addCleanup(patched.stop)
        patched = patch.object(main._alert_websockets, "broadcast", self.broadcast)
        patched.start()
        self.addCleanup(patched.stop)
        environment = patch.dict(os.environ, {
            "PAUSEABLE_ENV": "production", "PAUSEABLE_APP_TOKEN": "prefs-app",
            "PAUSEABLE_DEVICE_TOKEN": "prefs-device", "PAUSEABLE_WORKER_TOKEN": "prefs-worker",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer prefs-app"}
        self.device_headers = {"Authorization": "Bearer prefs-device"}

    def save(self, enabled, sound):
        return self.client.put(URL, headers=self.headers, json={
            "safety_notifications": enabled, "sound_enabled": sound,
        })

    def decision(self, event_id, wandering=False):
        return self.client.post("/api/events/decisions", headers=self.device_headers, json={
            "contract_version": "1.0", "event_id": event_id,
            "occurred_at": "2026-10-23T00:00:00Z", "patient_id": PATIENT,
            "device_id": "pi5-central-01", "source": "central-atlas-app",
            "decision": "wandering_suspected" if wandering else "repetitive_behavior",
            "risk_level": "caution", "risk_score": 60, "actions": ["notify_guardian"],
        })

    def test_api_auth_validation_legacy_compatibility_and_durable_restart(self):
        for method in ("GET", "PUT"):
            data = {"safety_notifications": True, "sound_enabled": False} if method == "PUT" else None
            self.assertEqual(self.client.request(method, URL, json=data).status_code, 401)
            self.assertEqual(self.client.request(method, URL, headers=self.device_headers, json=data).status_code, 403)
            self.assertEqual(self.client.request(method, URL, headers={"Authorization": "Bearer prefs-worker"}, json=data).status_code, 403)
        self.assertEqual(self.client.get(URL, headers=self.headers).json(), DEFAULT_PREFERENCES)
        saved = self.save(False, True)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.headers["cache-control"], "private, no-store")
        restarted = NotificationPreferenceStore(local_dir=self.preferences.local_dir)
        with patch.object(main, "_notification_preferences_store", return_value=restarted):
            self.assertEqual(self.client.get(URL + f"?patient_id={PATIENT}", headers=self.headers).json(), saved.json())
        self.assertEqual(self.client.get(URL + "?patient_id=other", headers=self.headers).status_code, 404)
        for value in ("false", 0, None):
            self.assertEqual(self.save(value, False).status_code, 422)

    def test_off_suppresses_both_pushes_but_preserves_websocket_history_and_deduplication(self):
        self.assertEqual(self.save(False, False).status_code, 200)
        for event_id, wandering in (("off-repeat", False), ("off-wander", True)):
            self.assertEqual(self.decision(event_id, wandering).status_code, 202)
        self.web.assert_not_awaited()
        self.native.assert_not_awaited()
        self.assertEqual(self.broadcast.await_count, 2)
        self.assertEqual(len(self.alerts.list_recent(PATIENT)), 2)
        self.assertEqual(self.save(True, True).status_code, 200)
        self.assertEqual(self.decision("off-repeat").status_code, 200)
        self.web.assert_not_awaited()
        self.assertEqual(self.decision("new-repeat").status_code, 202)
        self.web.assert_awaited_once()
        self.native.assert_awaited_once()

    def test_sound_flag_reaches_both_transports_and_toggle_is_read_before_delivery(self):
        for index, sound in enumerate((False, True)):
            self.save(True, sound)
            self.assertEqual(self.decision(f"sound-{index}").status_code, 202)
            self.assertEqual(self.web.await_args.kwargs["sound_enabled"], sound)
            self.assertEqual(self.native.await_args.kwargs["sound_enabled"], sound)
        self.save(False, False)
        asyncio.run(main._deliver_alert_notifications(PATIENT, {
            "alert_id": "queued-before-disable", "alert_type": "repetitive_behavior", "risk_level": "caution",
        }))
        self.assertEqual(self.web.await_count, 2)
        self.assertEqual(self.native.await_count, 2)

    def test_settings_and_transport_failures_do_not_lose_alerts(self):
        self.save(True, False)
        self.web.side_effect = RuntimeError("temporary push outage")
        self.assertEqual(self.decision("web-unavailable").status_code, 202)
        self.native.assert_awaited_once()
        self.native.side_effect = RuntimeError("temporary push outage")
        self.assertEqual(self.decision("both-unavailable").status_code, 202)
        self.assertEqual(len(self.alerts.list_recent(PATIENT)), 2)
        with patch.object(self.preferences, "load", side_effect=OSError("settings outage")):
            self.assertEqual(self.client.get(URL, headers=self.headers).status_code, 503)
            self.assertEqual(self.decision("settings-unavailable").status_code, 202)
        self.assertEqual(len(self.alerts.list_recent(PATIENT)), 3)
        with patch.object(self.preferences, "save", side_effect=OSError("settings outage")):
            self.assertEqual(self.save(False, False).status_code, 503)

    def test_delivery_outage_honors_cached_opt_out_and_unknown_cache_defaults_to_safety(self):
        self.save(False, False)
        with patch.object(self.preferences, "load", side_effect=OSError("settings outage")):
            self.assertEqual(self.decision("cached-opt-out").status_code, 202)
            self.web.assert_not_awaited()
            self.native.assert_not_awaited()
        with patch.object(main, "_notification_preferences_store", side_effect=OSError("store unavailable")):
            self.assertEqual(self.decision("no-cached-policy").status_code, 202)
            self.web.assert_awaited_once()
            self.native.assert_awaited_once()
            self.assertFalse(self.web.await_args.kwargs["sound_enabled"])
        self.assertEqual(len(self.alerts.list_recent(PATIENT)), 2)

    def test_photo_upload_and_private_read_survive_off_and_silent_notifications(self):
        jpeg = b"\xff\xd8photo-unchanged\xff\xd9"
        for event_id, enabled in (("photo-off", False), ("photo-on", True)):
            self.save(enabled, False)
            response = self.client.post("/api/devices/pi4-front-door-01/door-events", headers=self.device_headers,
                data={"event_id": event_id, "event_time": "2026-10-23T00:00:00Z", "decision": "EXIT", "patient_id": PATIENT},
                files={"representative": ("photo.jpg", jpeg, "image/jpeg")})
            self.assertEqual(response.status_code, 202)
            image_url = response.json()["event"]["image_url"]
            self.assertEqual(self.client.get(image_url).status_code, 401)
            self.assertEqual(self.client.get(image_url, headers=self.headers).content, jpeg)
            self.assertEqual(self.door_push.await_count, int(enabled))
        self.assertFalse(self.door_push.await_args.kwargs["sound_enabled"])
        self.assertEqual(len(self.alerts.list_recent(PATIENT)), 2)


if __name__ == "__main__":
    unittest.main()
