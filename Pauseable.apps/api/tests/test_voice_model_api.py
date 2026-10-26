from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FakeVoiceModelService:
    def create_upload_plan(self, **arguments):
        return {"model_id": "voice-model-0123456789ab", **arguments}

    def publish(self, **arguments):
        return {"status": "published", **arguments}

    def create_device_release(self, **arguments):
        return {
            "model_id": "voice-model-0123456789ab",
            "version": "2026.09.16.1",
            "onnx_download_url": "https://r2.test/model.onnx",
            "config_download_url": "https://r2.test/model.onnx.json",
            "onnx_sha256": "a" * 64,
            "config_sha256": "b" * 64,
            "created_at": "2026-09-16T00:00:00+00:00",
            "published_at": "2026-09-16T00:01:00+00:00",
        }

    def record_installation(self, **arguments):
        return {
            **arguments,
            "source_job_id": "voice-job-0123456789ab",
        }

    def cleanup_expired_models(self):
        return {"models_deleted": 0, "objects_deleted": 0}


class FakeVoiceTrainingService:
    def __init__(self) -> None:
        self.scheduled = []

    def schedule_raw_audio_deletion(self, **arguments):
        self.scheduled.append(arguments)
        return {"status": "scheduled", "delete_after": "2026-10-25T00:00:00+00:00"}

    def cleanup_expired_raw_audio(self):
        return {"jobs_cleaned": 0, "objects_deleted": 0}

    def reconcile_verified_installations(self):
        return {"jobs_scheduled": 0}


class VoiceModelApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.old_worker = os.environ.get("PAUSEABLE_WORKER_TOKEN")
        self.old_device = os.environ.get("PAUSEABLE_DEVICE_TOKEN")
        os.environ["PAUSEABLE_WORKER_TOKEN"] = "worker-test"
        os.environ["PAUSEABLE_DEVICE_TOKEN"] = "device-test"
        self.storage_patch = patch.object(main, "STORAGE_BACKEND", "r2")
        self.service_patch = patch.object(
            main,
            "_r2_voice_model_service",
            return_value=FakeVoiceModelService(),
        )
        self.training_service = FakeVoiceTrainingService()
        self.training_patch = patch.object(
            main,
            "_r2_voice_training_service",
            return_value=self.training_service,
        )
        self.storage_patch.start()
        self.service_patch.start()
        self.training_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.service_patch.stop()
        self.training_patch.stop()
        self.storage_patch.stop()
        for name, old in (
            ("PAUSEABLE_WORKER_TOKEN", self.old_worker),
            ("PAUSEABLE_DEVICE_TOKEN", self.old_device),
        ):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old

    def test_publisher_and_device_tokens_are_separate(self) -> None:
        upload = self.client.post(
            "/api/worker/voice-models/upload-plan",
            headers={"Authorization": "Bearer device-test"},
            json={
                "patient_id": "byunwoojin",
                "version": "2026.09.16.1",
                "artifacts": {},
            },
        )
        latest = self.client.get(
            "/api/devices/pi5-home-01/voice-models/latest",
            params={"patient_id": "byunwoojin"},
            headers={"Authorization": "Bearer worker-test"},
        )
        self.assertEqual(upload.status_code, 403)
        self.assertEqual(latest.status_code, 403)

    def test_device_gets_latest_and_sends_ack(self) -> None:
        headers = {"Authorization": "Bearer device-test"}
        latest = self.client.get(
            "/api/devices/pi5-home-01/voice-models/latest",
            params={"patient_id": "byunwoojin"},
            headers=headers,
        )
        ack = self.client.post(
            "/api/devices/pi5-home-01/voice-models/voice-model-0123456789ab/ack",
            headers=headers,
            json={"patient_id": "byunwoojin", "status": "installed"},
        )
        self.assertEqual(latest.status_code, 200)
        self.assertEqual(ack.status_code, 200)
        self.assertEqual(ack.json()["status"], "installed")
        self.assertEqual(
            self.training_service.scheduled,
            [{
                "patient_id": "byunwoojin",
                "job_id": "voice-job-0123456789ab",
            }],
        )
        self.assertEqual(
            ack.json()["raw_audio_retention"]["status"],
            "scheduled",
        )


if __name__ == "__main__":
    unittest.main()
