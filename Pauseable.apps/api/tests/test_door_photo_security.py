import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.alert_history_store import AlertHistoryStore
from app.door_event_store import DoorEventStore
from app.main import app


class DoorPhotoSecurityTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="pauseable-photo-auth-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.photos = DoorEventStore(local_dir=root / "photos")
        self.alerts = AlertHistoryStore(local_dir=root / "alerts")
        for target, kwargs in (
            ("app.main._door_event_store", {"return_value": self.photos}),
            ("app.main._alert_history_store", {"return_value": self.alerts}),
            ("app.main._alert_websockets.broadcast", {"new_callable": AsyncMock}),
            ("app.main.native_push_is_configured", {"return_value": False}),
            ("app.main.web_push_is_configured", {"return_value": False}),
        ):
            patched = patch(target, **kwargs)
            patched.start()
            self.addCleanup(patched.stop)
        environment = patch.dict(os.environ, {
            "PAUSEABLE_ENV": "production",
            "PAUSEABLE_APP_TOKEN": "photo-test-app",
            "PAUSEABLE_DEVICE_TOKEN": "photo-test-device",
            "PAUSEABLE_WORKER_TOKEN": "photo-test-worker",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer photo-test-app"}

    @staticmethod
    def routes():
        return (
            ("GET", "/api/patients/byunwoojin/dashboard"),
            ("GET", "/api/door-events"),
            ("GET", "/api/door-events/door-event-001"),
            ("GET", "/api/door-events/door-event-001/image"),
            ("POST", "/api/door-events/door-event-001/confirm"),
        )

    def assert_private(self, response):
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertIn("authorization", response.headers["vary"].lower())
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_photo_metadata_image_and_confirmation_require_app_auth_before_storage(self):
        with patch("app.main._door_event_store", side_effect=AssertionError("Private storage read")):
            for method, path in self.routes():
                with self.subTest(method=method, path=path):
                    response = self.client.request(method, path)
                    self.assertEqual(response.status_code, 401)
                    self.assert_private(response)
                    for token in ("wrong", "photo-test-device", "photo-test-worker"):
                        response = self.client.request(method, path, headers={
                            "Authorization": f"Bearer {token}",
                        })
                        self.assertEqual(response.status_code, 403)
                        self.assert_private(response)

    def test_legacy_urls_still_work_for_authenticated_apps_without_credentials_in_urls(self):
        for method, path in self.routes():
            with self.subTest(path=path):
                response = self.client.request(method, path, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assert_private(response)
        event = self.client.get("/api/door-events/door-event-001", headers=self.headers).json()
        self.assertTrue(event["image_url"].endswith("/api/door-events/door-event-001/image"))
        self.assertNotIn("photo-test-app", event["image_url"])
        image = self.client.get(event["image_url"], headers=self.headers)
        self.assertEqual(image.headers["content-type"], "image/png")
        self.assertGreater(len(image.content), 100_000)

    def test_query_string_credentials_are_not_accepted_and_missing_server_token_fails_closed(self):
        image = "/api/door-events/door-event-001/image"
        self.assertEqual(self.client.get(image + "?token=photo-test-app&app_token=photo-test-app").status_code, 401)
        with patch.dict(os.environ, {"PAUSEABLE_APP_TOKEN": ""}):
            self.assertEqual(self.client.get(image, headers=self.headers).status_code, 503)

    def test_authenticated_missing_photo_is_private_and_cors_allows_auth_header(self):
        response = self.client.get("/api/door-events/missing/image", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assert_private(response)
        preflight = self.client.options("/api/door-events/door-event-001/image", headers={
            "Origin": "http://127.0.0.1:18108",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        })
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "http://127.0.0.1:18108")

    def test_pi_upload_alert_and_authenticated_photo_read_still_work(self):
        event_id = "camera.20261023_001"
        data = {
            "event_id": event_id, "event_time": "2026-10-23T00:00:00Z",
            "decision": "EXIT", "patient_id": "byunwoojin",
        }
        jpeg = b"\xff\xd8private-test-frame\xff\xd9"
        files = {"representative": ("photo.jpg", jpeg, "image/jpeg")}
        upload_url = "/api/devices/pi4-front-door-01/door-events"
        self.assertEqual(self.client.post(upload_url, headers=self.headers, data=data, files=files).status_code, 403)
        with patch("app.main._alert_websockets.broadcast", new_callable=AsyncMock) as broadcast:
            response = self.client.post(upload_url, headers={
                "Authorization": "Bearer photo-test-device",
            }, data=data, files=files)
            self.assertEqual(response.status_code, 202)
            broadcast.assert_awaited_once()
            self.assertEqual(broadcast.await_args.args[1]["data"]["related_event_id"], event_id)
            photo_url = response.json()["event"]["image_url"]
            self.assertEqual(self.client.get(photo_url).status_code, 401)
            image = self.client.get(photo_url, headers=self.headers)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, jpeg)
            self.assert_private(image)
            duplicate = self.client.post(upload_url, headers={
                "Authorization": "Bearer photo-test-device",
            }, data=data, files=files)
            self.assertEqual(duplicate.status_code, 200)
            broadcast.assert_awaited_once()
            self.assertEqual(len(self.alerts.list_recent("byunwoojin")), 1)


if __name__ == "__main__":
    unittest.main()
