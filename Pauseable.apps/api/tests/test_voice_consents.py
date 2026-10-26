from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.voice_consents import VoiceConsentStore, VOICE_CONSENT_POLICY_VERSION

PATIENT = "byunwoojin"
REQUEST_ID = "a" * 32
CONSENT_ID = f"voice-consent-{REQUEST_ID}"
URL = f"/api/patients/{PATIENT}/voice-training/consents"
BODY = {"request_id": REQUEST_ID, "policy_version": VOICE_CONSENT_POLICY_VERSION, "accepted": True}


class MemoryR2:
    def __init__(self):
        self.objects = {}

    def get_json(self, key):
        return deepcopy(self.objects.get(key))

    def put_json_if_absent(self, key, payload):
        if key not in self.objects:
            self.objects[key] = deepcopy(payload)
            return '"etag"'
        return None


class VoiceConsentStoreTest(unittest.TestCase):
    def test_local_restart_and_retry_preserve_original_timestamp(self):
        with TemporaryDirectory() as directory:
            first = VoiceConsentStore(local_dir=Path(directory))
            receipt = first.accept(PATIENT, REQUEST_ID)
            restarted = VoiceConsentStore(local_dir=Path(directory))
            self.assertEqual(restarted.load(PATIENT, CONSENT_ID), receipt)
            self.assertEqual(restarted.accept(PATIENT, REQUEST_ID), receipt)
            self.assertEqual(len(list(Path(directory).rglob("*.json"))), 1)
            self.assertEqual(list(Path(directory).rglob("*.tmp")), [])
            self.assertIsNone(restarted.load("other-patient", CONSENT_ID))

    def test_r2_restart_retries_and_other_features_are_isolated(self):
        r2 = MemoryR2()
        r2.objects = {
            "patients/byunwoojin/care-profile.json": {"patient_call_name": "unchanged"},
            "patients/byunwoojin/home-environment.json": {"region_code": "unchanged"},
            "patients/byunwoojin/notification-preferences.json": {"safety_notifications": True},
            "door-events/photo.json": {"image": "unchanged"},
            "voice-training/current.json": {"model": "unchanged"},
        }
        before = deepcopy(r2.objects)
        with TemporaryDirectory() as directory:
            first = VoiceConsentStore(local_dir=Path(directory), r2_storage=r2)
            receipt = first.accept(PATIENT, REQUEST_ID)
            restarted = VoiceConsentStore(local_dir=Path(directory), r2_storage=r2)
            self.assertEqual(restarted.load(PATIENT, CONSENT_ID), receipt)
            self.assertEqual(restarted.accept(PATIENT, REQUEST_ID), receipt)
            restarted.accept(PATIENT, "b" * 32)
            self.assertEqual(len(r2.objects), len(before) + 2)
            self.assertEqual({key: r2.objects[key] for key in before}, before)

    def test_failed_or_unconfirmed_storage_never_looks_saved(self):
        r2 = MemoryR2()
        with TemporaryDirectory() as directory:
            store = VoiceConsentStore(local_dir=Path(directory), r2_storage=r2)
            with patch.object(r2, "put_json_if_absent", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    store.accept(PATIENT, REQUEST_ID)
            self.assertEqual(r2.objects, {})
            with patch.object(r2, "put_json_if_absent", return_value=None):
                with self.assertRaises(OSError):
                    store.accept(PATIENT, REQUEST_ID)

    def test_untrusted_ids_and_invalid_receipts_are_rejected(self):
        with TemporaryDirectory() as directory:
            store = VoiceConsentStore(local_dir=Path(directory))
            for patient_id in ("../outside", "a/b", "", "x" * 65):
                with self.assertRaises(ValueError):
                    store.accept(patient_id, REQUEST_ID)
            for request_id in ("../outside", "a" * 31, "x" * 32):
                with self.assertRaises(ValueError):
                    store.accept(PATIENT, request_id)


class VoiceConsentApiTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.r2 = MemoryR2()
        self.root = Path(directory.name)
        self.store = VoiceConsentStore(local_dir=self.root, r2_storage=self.r2)
        for patcher in (
            patch.object(main, "_voice_consent_store", return_value=self.store),
            patch.dict(os.environ, {
                "PAUSEABLE_ENV": "production", "PAUSEABLE_APP_TOKEN": "consent-app",
                "PAUSEABLE_DEVICE_TOKEN": "consent-device", "PAUSEABLE_WORKER_TOKEN": "consent-worker",
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer consent-app"}

    def test_authentication_and_roles_are_required_for_write_and_read(self):
        for method, url in (("POST", URL), ("GET", URL + "/" + CONSENT_ID)):
            self.assertEqual(self.client.request(method, url, json=BODY).status_code, 401)
            for role in ("device", "worker"):
                response = self.client.request(method, url, json=BODY,
                    headers={"Authorization": f"Bearer consent-{role}"})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.r2.objects, {})

    def test_receipt_is_durable_idempotent_and_not_publicly_cached(self):
        saved = self.client.post(URL, json=BODY, headers=self.headers)
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.headers["cache-control"], "private, no-store")
        self.assertEqual(saved.headers["vary"], "Authorization")
        self.assertEqual(saved.json()["policy_version"], VOICE_CONSENT_POLICY_VERSION)
        restarted = VoiceConsentStore(local_dir=self.root, r2_storage=self.r2)
        with patch.object(main, "_voice_consent_store", return_value=restarted):
            self.assertEqual(self.client.get(URL + "/" + CONSENT_ID, headers=self.headers).json(), saved.json())
            self.assertEqual(self.client.post(URL, json=BODY, headers=self.headers).json(), saved.json())
        self.assertEqual(self.client.get(URL + "/voice-consent-" + "b" * 32, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get(URL.replace(PATIENT, "other") + "/" + CONSENT_ID,
            headers=self.headers).status_code, 404)

    def test_rejection_old_policy_coercion_and_untrusted_fields_never_write(self):
        for body in (
            {**BODY, "accepted": False}, {**BODY, "accepted": "true"},
            {**BODY, "accepted": 1}, {**BODY, "policy_version": "old-version"},
            {**BODY, "accepted_at": "2026-01-01T00:00:00Z"},
            {**BODY, "request_id": "../outside"},
        ):
            self.assertEqual(self.client.post(URL, json=body, headers=self.headers).status_code, 422)
        self.assertEqual(self.r2.objects, {})

    def test_storage_errors_return_retryable_failure_without_false_receipt(self):
        with patch.object(self.r2, "put_json_if_absent", side_effect=OSError("sensitive detail")):
            result = self.client.post(URL, json=BODY, headers=self.headers)
            self.assertEqual(result.status_code, 503)
            self.assertNotIn("sensitive detail", result.text)
        self.assertEqual(self.r2.objects, {})
