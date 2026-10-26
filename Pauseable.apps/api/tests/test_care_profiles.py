import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import care_profiles, main


class CareProfileApiTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for target, value in (
            ("app.care_profiles.PROFILE_DIR", Path(directory.name)),
            ("app.main.STORAGE_BACKEND", "local"),
        ):
            replacement = patch(target, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        environment = patch.dict(os.environ, {
            "PAUSEABLE_ENV": "production",
            "PAUSEABLE_APP_TOKEN": "profile-app-test",
            "PAUSEABLE_DEVICE_TOKEN": "profile-device-test",
            "PAUSEABLE_WORKER_TOKEN": "profile-worker-test",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.client = TestClient(main.app)
        self.url = "/api/patients/byunwoojin/care-profile"
        self.headers = {"Authorization": "Bearer profile-app-test"}

    def test_names_survive_reload_without_changing_device_patient_id(self):
        initial = self.client.get(self.url, headers=self.headers)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["name"], "")
        self.assertEqual(initial.json()["patient_name"], "")
        before = main._ensure_patient("byunwoojin")
        saved = self.client.put(self.url, headers=self.headers, json={
            "name": "  이보호  ", "patient_name": "  박돌봄  ",
            "relationship": "딸", "phone_number": "",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["name"], "이보호")
        self.assertEqual(saved.json()["patient_name"], "박돌봄")

        self.assertEqual(
            TestClient(main.app).get(self.url, headers=self.headers).json(), saved.json(),
        )
        self.assertEqual(main._ensure_patient("byunwoojin"), before)

    def test_authentication_validation_and_patient_boundary(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.put(self.url, json={}).status_code, 401)
        self.assertEqual(self.client.get(self.url, headers={
            "Authorization": "Bearer profile-device-test",
        }).status_code, 403)
        for payload in (
            {"name": "   ", "patient_name": "박돌봄"},
            {"name": "이보호", "patient_name": ""},
            {"name": "이보호", "patient_name": "가" * 41},
            {"name": "이보호", "patient_name": "박돌봄", "phone_number": "abc"},
        ):
            self.assertEqual(
                self.client.put(self.url, headers=self.headers, json=payload).status_code, 422,
            )
        self.assertEqual(self.client.get(
            "/api/patients/unknown/care-profile", headers=self.headers,
        ).status_code, 404)

    def test_r2_storage_uses_patient_scoped_key(self):
        objects = {}

        class FakeStorage:
            def get_json(self, key):
                return objects.get(key)

            def put_json(self, key, payload):
                objects[key] = dict(payload)

        with patch("app.care_profiles.R2Storage.from_environment", return_value=FakeStorage()):
            care_profiles.save_profile("byunwoojin", {
                "name": "이보호", "patient_name": "박돌봄",
            }, "r2")
            self.assertIn("patients/byunwoojin/care-profile.json", objects)
            self.assertEqual(care_profiles.load_profile("byunwoojin", "r2")["patient_name"], "박돌봄")
            self.assertEqual(care_profiles.load_profile("other", "r2")["patient_name"], "")


    def test_legacy_writes_preserve_spoken_name_and_explicit_empty_clears_it(self):
        profile = {
            "name": "이보호", "patient_name": "박돌봄", "relationship": "딸",
            "patient_call_name": "  엄마  ",
        }
        saved = self.client.put(self.url, headers=self.headers, json=profile)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["patient_call_name"], "엄마")
        self.assertEqual(saved.headers["Cache-Control"], "no-store")
        legacy = self.client.put(self.url, headers=self.headers, json={
            "name": "이보호 수정", "patient_name": "박돌봄",
        })
        self.assertEqual(legacy.json()["patient_call_name"], "엄마")
        self.assertEqual(legacy.json()["relationship"], "딸")
        self.assertEqual(TestClient(main.app).get(
            self.url, headers=self.headers,
        ).json(), legacy.json())
        cleared = self.client.put(self.url, headers=self.headers, json={
            **profile, "patient_call_name": "",
        })
        self.assertEqual(cleared.json()["patient_call_name"], "")

    def test_spoken_name_validation_and_existing_profiles(self):
        self.assertEqual(self.client.get(self.url, headers=self.headers).json()[
            "patient_call_name"], "")
        base = {"name": "이보호", "patient_name": "박돌봄"}
        for value in (None, 123, "가" * 41, "엄마\n아빠", "엄마\x00"):
            self.assertEqual(self.client.put(self.url, headers=self.headers, json={
                **base, "patient_call_name": value,
            }).status_code, 422)
        self.assertEqual(self.client.put(self.url, headers=self.headers, json={
            **base, "relationship": "딸\n손녀",
        }).status_code, 422)

    def test_tts_read_only_routes_enforce_roles_and_minimize_personal_data(self):
        before_patient = main._ensure_patient("byunwoojin")
        device_url = "/api/device/patients/byunwoojin/tts-context"
        worker_url = "/api/worker/patients/byunwoojin/tts-context"
        for path, valid, invalid in (
            (device_url, "profile-device-test", "profile-worker-test"),
            (worker_url, "profile-worker-test", "profile-device-test"),
        ):
            auth = {"Authorization": f"Bearer {valid}"}
            self.assertEqual(self.client.get(path).status_code, 401)
            for token in ("profile-app-test", invalid, "invalid"):
                self.assertEqual(self.client.get(path, headers={
                    "Authorization": f"Bearer {token}",
                }).status_code, 403)
            empty = self.client.get(path, headers=auth)
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.headers["Cache-Control"], "no-store")
            self.assertFalse(empty.json()["is_configured"])
            self.assertEqual(self.client.put(path, headers=auth, json={}).status_code, 405)
            self.assertEqual(self.client.get(path.replace(
                "byunwoojin", "unknown",
            ), headers=auth).status_code, 404)
        saved = self.client.put(self.url, headers=self.headers, json={
            "name": "이보호", "patient_name": "박돌봄", "relationship": "손자",
            "phone_number": "010-1234-5678", "patient_call_name": "할머니",
        })
        self.assertEqual(saved.status_code, 200)
        expected = {
            "patient_id": "byunwoojin", "relationship": "손자",
            "patient_call_name": "할머니", "is_configured": True,
        }
        for path, token in ((device_url, "profile-device-test"), (worker_url, "profile-worker-test")):
            self.assertEqual(self.client.get(path, headers={
                "Authorization": f"Bearer {token}",
            }).json(), expected)
        self.assertEqual(main._ensure_patient("byunwoojin"), before_patient)

    def test_r2_reload_keeps_family_context_without_touching_other_objects(self):
        other_objects = {
            "patients/byunwoojin/voice-models/latest.json": {"model_id": "existing"},
            "patients/byunwoojin/alerts/real.json": {"alert_id": "existing"},
            "patients/byunwoojin/door-events/real.json": {"image": "existing.png"},
        }
        objects = dict(other_objects)

        class Storage:
            def get_json(self, key):
                return objects.get(key)

            def put_json(self, key, payload):
                objects[key] = dict(payload)

        with patch.object(main, "STORAGE_BACKEND", "r2"), patch.object(
            care_profiles.R2Storage, "from_environment", return_value=Storage(),
        ):
            saved = self.client.put(self.url, headers=self.headers, json={
                "name": "이보호", "patient_name": "박돌봄", "relationship": "아들",
                "patient_call_name": "아버지",
            })
            self.assertEqual(saved.status_code, 200)
            with TemporaryDirectory() as fresh, patch.object(care_profiles, "PROFILE_DIR", Path(fresh)):
                self.assertEqual(TestClient(main.app).get(
                    self.url, headers=self.headers,
                ).json(), saved.json())
                context = TestClient(main.app).get(
                    "/api/device/patients/byunwoojin/tts-context",
                    headers={"Authorization": "Bearer profile-device-test"},
                ).json()
                self.assertEqual(context["patient_call_name"], "아버지")
            for key, value in other_objects.items():
                self.assertEqual(objects[key], value)
            self.assertEqual(set(objects) - set(other_objects), {
                "patients/byunwoojin/care-profile.json",
            })


if __name__ == "__main__":
    unittest.main()
