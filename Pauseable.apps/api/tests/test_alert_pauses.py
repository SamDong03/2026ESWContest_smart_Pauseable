from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import main
from app.alert_pauses import RepetitiveAlertPauseStore
from tests import test_notification_preferences as notifications

PATIENT = "byunwoojin"
URL = f"/api/patients/{PATIENT}/repetitive-alert-pause"


class AlertPauseStoreTest(unittest.TestCase):
    def test_local_restart_expiry_resume_and_patient_isolation(self):
        now = datetime(2026, 10, 28, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = RepetitiveAlertPauseStore(local_dir=root)
            self.assertFalse(first.load(PATIENT, now=now)["is_paused"])
            first.save(PATIENT, duration_minutes=30, now=now)
            second = RepetitiveAlertPauseStore(local_dir=root)
            self.assertTrue(second.load(PATIENT, now=now)["is_paused"])
            self.assertFalse(second.load("other", now=now)["is_paused"])
            self.assertFalse(second.load(PATIENT, now=now + timedelta(minutes=30))["is_paused"])
            second.save(PATIENT, duration_minutes=None, now=now)
            self.assertFalse(first.load(PATIENT, now=now)["is_paused"])

    def test_r2_reload_preserves_other_objects_and_rejects_invalid_input(self):
        r2 = notifications.MemoryR2()
        r2.objects[f"patients/{PATIENT}/notification-preferences.json"] = {"sound_enabled": True}
        before = deepcopy(r2.objects)
        with TemporaryDirectory() as directory:
            first = RepetitiveAlertPauseStore(local_dir=Path(directory), r2_storage=r2)
            first.save(PATIENT, duration_minutes=60)
            second = RepetitiveAlertPauseStore(local_dir=Path(directory), r2_storage=r2)
            self.assertTrue(second.load(PATIENT)["is_paused"])
            self.assertEqual({key: r2.objects[key] for key in before}, before)
            for patient in ("../other", "", "x" * 65):
                with self.assertRaises(ValueError):
                    first.load(patient)
            for duration in (0, -1, 1441, True, "30"):
                with self.assertRaises(ValueError):
                    first.save(PATIENT, duration_minutes=duration)


class AlertPauseApiTest(unittest.TestCase):
    def setUp(self):
        self.fixture = notifications.NotificationPreferenceApiTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = RepetitiveAlertPauseStore(local_dir=Path(directory.name))
        patched = patch.object(main, "_repetitive_alert_pause_store", return_value=self.store)
        patched.start()
        self.addCleanup(patched.stop)
        self.client = self.fixture.client
        self.headers = self.fixture.headers

    def pause(self):
        return self.client.post(URL, headers=self.headers, json={"duration_minutes": 30})

    def test_pause_blocks_new_repeat_push_and_websocket_but_keeps_history(self):
        self.assertEqual(self.pause().status_code, 200)
        self.assertEqual(self.fixture.decision("paused-repeat").status_code, 202)
        self.fixture.web.assert_not_awaited()
        self.fixture.native.assert_not_awaited()
        self.fixture.broadcast.assert_not_awaited()
        self.assertEqual(len(self.fixture.alerts.list_recent(PATIENT)), 1)
        # Old event IDs are not replayed when notifications resume.
        self.assertEqual(self.client.delete(URL, headers=self.headers).status_code, 200)
        self.assertEqual(self.fixture.decision("paused-repeat").status_code, 200)
        self.fixture.web.assert_not_awaited()
        self.assertEqual(self.fixture.decision("resumed-repeat").status_code, 202)
        self.fixture.web.assert_awaited_once()
        self.fixture.native.assert_awaited_once()
        self.fixture.broadcast.assert_awaited_once()

    def test_pause_never_blocks_wandering_or_photo_upload_read_and_notification(self):
        self.pause()
        self.assertEqual(self.fixture.decision("paused-wander", wandering=True).status_code, 202)
        self.fixture.web.assert_awaited_once()
        self.fixture.native.assert_awaited_once()
        jpeg = b"\xff\xd8photo-still-works\xff\xd9"
        uploaded = self.client.post("/api/devices/pi4-front-door-01/door-events",
            headers=self.fixture.device_headers,
            data={"event_id": "paused-photo", "event_time": "2026-10-28T00:00:00Z",
                  "decision": "EXIT", "patient_id": PATIENT},
            files={"representative": ("photo.jpg", jpeg, "image/jpeg")})
        self.assertEqual(uploaded.status_code, 202)
        image_url = uploaded.json()["event"]["image_url"]
        self.assertEqual(self.client.get(image_url).status_code, 401)
        self.assertEqual(self.client.get(image_url, headers=self.headers).content, jpeg)
        self.fixture.door_push.assert_awaited_once()
        self.assertEqual(self.fixture.broadcast.await_count, 2)

    def test_expired_pause_automatically_allows_new_notifications(self):
        self.store.save(PATIENT, duration_minutes=30,
                        now=datetime.now(timezone.utc) - timedelta(minutes=31))
        self.assertFalse(self.client.get(URL, headers=self.headers).json()["is_paused"])
        self.assertEqual(self.fixture.decision("after-expiry").status_code, 202)
        self.fixture.web.assert_awaited_once()
        self.fixture.native.assert_awaited_once()
        self.fixture.broadcast.assert_awaited_once()

    def test_auth_validation_and_no_silencing_other_types_through_legacy_route(self):
        for method in ("GET", "POST", "DELETE"):
            kwargs = {"json": {"duration_minutes": 30}} if method == "POST" else {}
            self.assertEqual(self.client.request(method, URL, **kwargs).status_code, 401)
            self.assertEqual(self.client.request(method, URL, headers=self.fixture.device_headers, **kwargs).status_code, 403)
        for value in (0, 1441, True, 1.5, "30"):
            self.assertEqual(self.client.post(URL, headers=self.headers, json={"duration_minutes": value}).status_code, 422)
        self.assertEqual(self.client.post(URL.replace(PATIENT, "other"), headers=self.headers,
            json={"duration_minutes": 30}).status_code, 404)
        self.assertEqual(self.client.post("/api/alerts/alert-night-001/pause", headers=self.headers,
            json={"duration_minutes": 30}).status_code, 422)

    def test_legacy_real_alert_id_can_pause_and_dashboard_restores_shared_state(self):
        self.fixture.decision("real-repeat-id")
        self.fixture.web.reset_mock()
        self.fixture.native.reset_mock()
        self.fixture.broadcast.reset_mock()
        alert_id = self.fixture.alerts.list_recent(PATIENT)[0]["alert_id"]
        paused = self.client.post(f"/api/alerts/{alert_id}/pause", headers=self.headers,
                                  json={"duration_minutes": 60})
        self.assertEqual(paused.status_code, 200)
        restarted = RepetitiveAlertPauseStore(local_dir=self.store.local_dir)
        with patch.object(main, "_repetitive_alert_pause_store", return_value=restarted):
            state = self.client.get(f"/api/patients/{PATIENT}/dashboard", headers=self.headers).json()
            self.assertTrue(state["repetitive_alert_pause"]["is_paused"])
            self.assertEqual(self.fixture.decision("after-restart").status_code, 202)
            self.fixture.web.assert_not_awaited()
        # Demo changes must not silently undo a real notification pause.
        self.client.post("/api/demo/scenarios/normal")
        self.assertTrue(self.client.get(URL, headers=self.headers).json()["is_paused"])
        self.client.post("/api/demo/scenarios/repetitive_behavior")

    def test_storage_failure_does_not_claim_success_or_hide_existing_photos(self):
        with patch.object(self.store, "save", side_effect=OSError("outage")):
            self.assertEqual(self.pause().status_code, 503)
        with patch.object(self.store, "load", side_effect=OSError("outage")):
            self.assertEqual(self.client.get(URL, headers=self.headers).status_code, 503)
            snapshot = self.client.get(f"/api/patients/{PATIENT}/dashboard", headers=self.headers)
            self.assertEqual(snapshot.status_code, 200)
            self.assertFalse(snapshot.json()["repetitive_alert_pause"]["available"])
            self.assertTrue(snapshot.json()["door_events"])
            self.assertEqual(self.fixture.decision("safety-fallback").status_code, 202)
            self.fixture.web.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
