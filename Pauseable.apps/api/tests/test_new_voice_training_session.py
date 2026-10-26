import copy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from tests.test_voice_training_service import MemoryStorage
from app.voice_training_service import VoiceTrainingJobStateError, VoiceTrainingService


class NewVoiceTrainingSessionTest(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryStorage()
        self.service = VoiceTrainingService(self.storage)
        self.patient = "byunwoojin"
        self.wave = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + bytes(64)
        self.prompt = self.service.script["prompts"][0]
        first = self.upload()
        self.old_id = first["job_id"]
        self.old_key = self.service._manifest_key(self.patient, self.old_id)
        old = self.storage.get_json(self.old_key)
        old["status"] = "completed"
        self.storage.put_json(self.old_key, old)
        self.old_manifest = copy.deepcopy(old)
        self.latest_key = f"patients/{self.patient}/voice-models/latest.json"
        self.storage.put_json(self.latest_key, {"model_id": "voice-model-existing", "version": self.old_id})
        self.storage.put_bytes(f"patients/{self.patient}/voice-models/existing/model.onnx", b"old-trained-model", content_type="application/octet-stream")
        self.original_bytes = copy.deepcopy(self.storage.byte_objects)

    def upload(self, **extra):
        return self.service.upload_clip(
            patient_id=self.patient, file_name=self.prompt["file_name"],
            prompt_text=self.prompt["text"], duration_seconds=5, audio=self.wave, **extra,
        )

    def test_new_set_keeps_old_recordings_and_published_voice(self):
        original_latest = self.storage.get_json(self.latest_key)
        progress = self.service.start_new_session(self.patient, self.old_id)
        self.assertNotEqual(progress["job_id"], self.old_id)
        self.assertEqual(progress["job_status"], "collecting")
        self.assertEqual(progress["clip_count"], 0)
        self.assertEqual(progress["recorded_seconds"], 0)
        self.assertEqual(self.storage.byte_objects, self.original_bytes)
        self.assertEqual(self.storage.get_json(self.old_key), self.old_manifest)
        self.assertEqual(self.storage.get_json(self.latest_key), original_latest)
        self.assertIsNone(self.service.claim_next_job(worker_id="test-worker"))
        uploaded = self.upload(job_id=progress["job_id"])
        self.assertEqual(uploaded["clip_count"], 1)
        self.assertEqual(uploaded["job_id"], progress["job_id"])
        for key, value in self.original_bytes.items():
            self.assertEqual(self.storage.get_bytes(key), value)
        self.assertEqual(self.storage.get_json(self.old_key), self.old_manifest)
        self.assertEqual(self.storage.get_json(self.latest_key), original_latest)

    def test_double_tap_and_lost_response_retry_return_the_same_set(self):
        first = self.service.start_new_session(self.patient, self.old_id)
        self.upload(job_id=first["job_id"])
        second = self.service.start_new_session(self.patient, self.old_id)
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(second["clip_count"], 1)
        manifests = [key for key in self.storage.json_objects if key.endswith("/manifest.json")]
        self.assertEqual(len(manifests), 2)

    def test_concurrent_start_uses_one_active_set(self):
        original = self.storage.put_json_if_match
        raced = False
        winner = None

        def race(key, value, etag):
            nonlocal raced, winner
            if key == self.service._active_job_key(self.patient) and not raced:
                raced = True
                winner = self.service.start_new_session(self.patient, self.old_id)
            return original(key, value, etag)

        with patch.object(self.storage, "put_json_if_match", side_effect=race):
            result = self.service.start_new_session(self.patient, self.old_id)
        self.assertEqual(result["job_id"], winner["job_id"])
        self.assertEqual(len([key for key in self.storage.json_objects if key.endswith("/manifest.json")]), 2)
        self.assertEqual(self.storage.get_json(self.old_key), self.old_manifest)

    def test_uncertain_write_does_not_delete_the_active_manifest(self):
        original = self.storage.put_json_if_match

        def write_then_disconnect(key, value, etag):
            original(key, value, etag)
            raise TimeoutError("simulated response loss")

        with patch.object(self.storage, "put_json_if_match", side_effect=write_then_disconnect):
            with self.assertRaises(TimeoutError):
                self.service.start_new_session(self.patient, self.old_id)
        retried = self.service.start_new_session(self.patient, self.old_id)
        self.assertEqual(retried["job_status"], "collecting")
        self.assertIsNotNone(self.service.get_active_manifest(self.patient))
        self.assertEqual(self.storage.get_json(self.old_key), self.old_manifest)

    def test_missing_success_etag_is_reconciled_without_deleting_data(self):
        original = self.storage.put_json_if_match

        def missing_etag(key, value, etag):
            original(key, value, etag)
            return None

        with patch.object(self.storage, "put_json_if_match", side_effect=missing_etag):
            result = self.service.start_new_session(self.patient, self.old_id)
        self.assertEqual(self.service.get_active_manifest(self.patient)["job_id"], result["job_id"])

    def test_active_or_retrying_training_cannot_be_replaced(self):
        for status in ("collecting", "queued", "claimed", "downloading", "training", "uploading", "failed"):
            with self.subTest(status=status):
                manifest = dict(self.old_manifest, status=status)
                self.storage.put_json(self.old_key, manifest)
                before = copy.deepcopy(self.storage.json_objects)
                with self.assertRaises(VoiceTrainingJobStateError):
                    self.service.start_new_session(self.patient, self.old_id)
                self.assertEqual(self.storage.json_objects, before)

    def test_stale_and_legacy_uploads_cannot_mix_into_the_new_set(self):
        self.service.start_new_session(self.patient, self.old_id)
        before = copy.deepcopy(self.storage.byte_objects)
        for options in ({}, {"job_id": self.old_id}, {"job_id": "voice-job-ffffffffffff"}):
            with self.subTest(options=options), self.assertRaises(VoiceTrainingJobStateError):
                self.upload(**options)
        self.assertEqual(self.storage.byte_objects, before)

    def test_api_requires_app_role_preserves_data_and_binds_upload_job(self):
        with patch.object(main, "STORAGE_BACKEND", "r2"), patch.object(
            main, "_r2_voice_training_service", return_value=self.service,
        ), patch.dict("os.environ", {
            "PAUSEABLE_ENV": "production", "PAUSEABLE_APP_TOKEN": "session-app-test",
            "PAUSEABLE_DEVICE_TOKEN": "session-device-test", "PAUSEABLE_WORKER_TOKEN": "session-worker-test",
        }), TestClient(main.app) as client:
            url = f"/api/patients/{self.patient}/voice-training/sessions"
            payload = {"previous_job_id": self.old_id}
            headers = {"Authorization": "Bearer session-app-test"}
            self.assertEqual(client.post(url, json=payload).status_code, 401)
            for token in ("session-device-test", "session-worker-test"):
                self.assertEqual(client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}).status_code, 403)
            self.assertEqual(client.post("/api/patients/other/voice-training/sessions", json=payload, headers=headers).status_code, 404)
            self.assertEqual(client.post(url, json={"previous_job_id": "invalid"}, headers=headers).status_code, 422)
            result = client.post(url, json=payload, headers=headers)
            self.assertEqual(result.status_code, 201)
            new_id = result.json()["job_id"]
            self.assertEqual(client.post(url, json=payload, headers=headers).json()["job_id"], new_id)
            data = {"patient_id": self.patient, "duration_seconds": "5", "prompt_text": self.prompt["text"]}
            files = {"file": ("S001.wav", self.wave, "audio/wav")}
            self.assertEqual(client.post("/api/voice-training/clips", headers=headers, data=data, files=files).status_code, 409)
            uploaded = client.post("/api/voice-training/clips", headers=headers, data=dict(data, job_id=new_id), files=files)
            self.assertEqual(uploaded.status_code, 201)
            self.assertEqual(uploaded.json()["job_id"], new_id)
            self.assertEqual(self.storage.get_json(self.old_key), self.old_manifest)
            self.assertEqual(self.storage.get_json(self.latest_key)["version"], self.old_id)

    def test_api_refuses_nonpersistent_local_restart(self):
        with patch.object(main, "STORAGE_BACKEND", "local"), patch.dict("os.environ", {"PAUSEABLE_APP_TOKEN": "session-app-test"}), TestClient(main.app) as client:
            response = client.post(f"/api/patients/{self.patient}/voice-training/sessions",
                json={"previous_job_id": self.old_id}, headers={"Authorization": "Bearer session-app-test"})
            self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
