from __future__ import annotations

import base64
import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from app.voice_model_service import (
    VoiceModelService,
    VoiceModelStateError,
)


def descriptor(data: bytes) -> dict[str, object]:
    return {
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_md5": base64.b64encode(
            hashlib.md5(data, usedforsecurity=False).digest()
        ).decode("ascii"),
    }


class FakeStorage:
    def __init__(self) -> None:
        self.json_objects = {}
        self.uploaded_objects = {}

    def get_json(self, key):
        return self.json_objects.get(key)

    def put_json(self, key, payload):
        self.json_objects[key] = payload

    def create_upload_url(self, key, **arguments):
        return f"https://r2.test/{key}"

    def create_download_url(self, key, *, expires_seconds):
        return f"https://r2.test/{key}?expires={expires_seconds}"

    def head_object(self, key):
        return self.uploaded_objects.get(key)

    def list_keys(self, prefix):
        return sorted(
            key for key in set(self.json_objects) | set(self.uploaded_objects)
            if key.startswith(prefix)
        )

    def delete_object(self, key):
        self.json_objects.pop(key, None)
        self.uploaded_objects.pop(key, None)


class VoiceModelServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = FakeStorage()
        self.service = VoiceModelService(self.storage)
        self.onnx = b"fake onnx"
        self.config = b'{"audio": {"sample_rate": 22050}}'
        self.artifacts = {
            "model.onnx": descriptor(self.onnx),
            "model.onnx.json": descriptor(self.config),
        }

    def _plan_and_upload(self, *, source_job_id=None):
        plan = self.service.create_upload_plan(
            patient_id="byunwoojin",
            version="2026.09.16.1",
            source_job_id=source_job_id,
            artifacts=self.artifacts,
        )
        plan_key = (
            "patients/byunwoojin/voice-models/releases/"
            f"{plan['model_id']}/upload-plan.json"
        )
        stored = self.storage.json_objects[plan_key]
        for name, item in stored["artifacts"].items():
            self.storage.uploaded_objects[item["object_key"]] = {
                "size_bytes": item["size_bytes"],
                "etag": f'"{item["md5_hex"]}"',
                "metadata": {"sha256": item["sha256"]},
            }
        return plan

    def test_upload_plan_is_content_addressed_and_idempotent(self) -> None:
        first = self.service.create_upload_plan(
            patient_id="byunwoojin",
            version="2026.09.16.1",
            artifacts=self.artifacts,
        )
        second = self.service.create_upload_plan(
            patient_id="byunwoojin",
            version="2026.09.16.1",
            artifacts=self.artifacts,
        )
        self.assertEqual(first["model_id"], second["model_id"])
        self.assertTrue(first["model_id"].startswith("voice-model-"))

    def test_publish_verifies_objects_and_creates_latest(self) -> None:
        plan = self._plan_and_upload()
        manifest = self.service.publish(
            patient_id="byunwoojin",
            model_id=plan["model_id"],
        )
        latest = self.service.get_latest(patient_id="byunwoojin")
        self.assertEqual(manifest["model_id"], latest["model_id"])
        self.assertEqual(manifest["version"], "2026.09.16.1")

    def test_publish_rejects_missing_artifact(self) -> None:
        plan = self.service.create_upload_plan(
            patient_id="byunwoojin",
            version="2026.09.16.1",
            artifacts=self.artifacts,
        )
        with self.assertRaisesRegex(VoiceModelStateError, "not uploaded"):
            self.service.publish(
                patient_id="byunwoojin",
                model_id=plan["model_id"],
            )

    def test_device_release_has_presigned_urls_and_ack(self) -> None:
        plan = self._plan_and_upload()
        self.service.publish(
            patient_id="byunwoojin",
            model_id=plan["model_id"],
        )
        release = self.service.create_device_release(
            patient_id="byunwoojin",
            device_id="pi5-home-01",
        )
        self.assertIn("onnx_download_url", release)
        ack = self.service.record_installation(
            patient_id="byunwoojin",
            device_id="pi5-home-01",
            model_id=plan["model_id"],
            status="installed",
            detail="ok",
            previous_model_id=None,
        )
        self.assertEqual(ack["status"], "installed")
        self.assertIn(
            f"devices/pi5-home-01/voice-model-installs/{plan['model_id']}.json",
            self.storage.json_objects,
        )

    def test_install_ack_preserves_source_training_job(self) -> None:
        source_job_id = "voice-job-0123456789ab"
        plan = self._plan_and_upload(source_job_id=source_job_id)
        manifest = self.service.publish(
            patient_id="byunwoojin",
            model_id=plan["model_id"],
        )
        ack = self.service.record_installation(
            patient_id="byunwoojin",
            device_id="pi5-home-01",
            model_id=plan["model_id"],
            status="installed",
            detail="local synthesis passed",
            previous_model_id=None,
        )
        self.assertEqual(manifest["source_job_id"], source_job_id)
        self.assertEqual(ack["source_job_id"], source_job_id)

    def test_superseded_model_is_deleted_after_seven_day_rollback_window(self) -> None:
        first = self._plan_and_upload()
        self.service.publish(
            patient_id="byunwoojin",
            model_id=first["model_id"],
        )
        first_model_id = first["model_id"]

        self.artifacts["model.onnx"] = descriptor(b"new fake onnx")
        second = self._plan_and_upload()
        self.service.publish(
            patient_id="byunwoojin",
            model_id=second["model_id"],
        )
        replaced_at = datetime(2026, 10, 24, tzinfo=timezone.utc)
        self.service.schedule_previous_model_deletion(
            patient_id="byunwoojin",
            model_id=first_model_id,
            replaced_at=replaced_at,
        )

        early = self.service.cleanup_expired_models(
            now=replaced_at + timedelta(days=6, hours=23)
        )
        self.assertEqual(early["models_deleted"], 0)
        due = self.service.cleanup_expired_models(
            now=replaced_at + timedelta(days=7)
        )
        self.assertEqual(due["models_deleted"], 1)
        first_prefix = (
            "patients/byunwoojin/voice-models/releases/"
            f"{first_model_id}/"
        )
        self.assertFalse(self.storage.list_keys(first_prefix))


if __name__ == "__main__":
    unittest.main()
