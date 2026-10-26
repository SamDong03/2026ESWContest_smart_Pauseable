import base64
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.voice_training_service import (
    DuplicateVoiceTrainingClip,
    InvalidVoiceTrainingRequest,
    VoiceTrainingClaimError,
    VoiceTrainingJobStateError,
    VoiceTrainingService,
)


class MemoryStorage:
    def __init__(self) -> None:
        self.byte_objects: dict[str, bytes] = {}
        self.json_objects: dict[str, dict] = {}
        self.etags: dict[str, str] = {}
        self.object_details: dict[str, dict] = {}

    def _etag(self, payload: dict) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return f'"{hashlib.sha256(encoded).hexdigest()}"'

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        self.byte_objects[key] = bytes(data)

    def get_bytes(self, key: str) -> bytes | None:
        return self.byte_objects.get(key)

    def object_exists(self, key: str) -> bool:
        return (
            key in self.byte_objects
            or key in self.json_objects
        )

    def delete_object(self, key: str) -> None:
        self.byte_objects.pop(key, None)
        self.json_objects.pop(key, None)
        self.etags.pop(key, None)
        self.object_details.pop(key, None)

    def put_json(self, key: str, payload: dict) -> None:
        self.json_objects[key] = copy.deepcopy(payload)
        self.etags[key] = self._etag(payload)

    def get_json(self, key: str) -> dict | None:
        payload = self.json_objects.get(key)
        return copy.deepcopy(payload) if payload is not None else None

    def get_json_with_etag(
        self,
        key: str,
    ) -> tuple[dict, str] | None:
        payload = self.json_objects.get(key)
        if payload is None:
            return None
        return copy.deepcopy(payload), self.etags[key]

    def put_json_if_absent(self, key: str, payload: dict) -> str | None:
        if key in self.json_objects or key in self.byte_objects:
            return None
        self.put_json(key, payload)
        return self.etags[key]

    def put_json_if_match(
        self,
        key: str,
        payload: dict,
        etag: str,
    ) -> str | None:
        if self.etags.get(key) != etag:
            return None
        self.put_json(key, payload)
        return self.etags[key]

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(
            key
            for key in set(self.byte_objects) | set(self.json_objects)
            if key.startswith(prefix)
        )

    def create_upload_url(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int = 900,
        metadata: dict[str, str] | None = None,
        content_md5: str | None = None,
        content_length: int | None = None,
    ) -> str:
        return f"memory://upload/{key}"

    def head_object(self, key: str) -> dict | None:
        details = self.object_details.get(key)
        return copy.deepcopy(details) if details is not None else None

    def simulate_artifact_upload(
        self,
        key: str,
        data: bytes,
        *,
        sha256: str,
    ) -> None:
        md5_hex = hashlib.md5(data, usedforsecurity=False).hexdigest()
        self.byte_objects[key] = bytes(data)
        self.object_details[key] = {
            "size_bytes": len(data),
            "etag": f'"{md5_hex}"',
            "content_type": "application/octet-stream",
            "metadata": {"sha256": sha256},
        }


class VoiceTrainingServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = MemoryStorage()
        self.service = VoiceTrainingService(self.storage)
        self.wave = (
            b"RIFF"
            + (36).to_bytes(4, "little")
            + b"WAVE"
            + bytes(64)
        )

    def test_empty_progress(self) -> None:
        progress = self.service.get_progress("patient-001")

        self.assertEqual(progress["job_status"], "not_started")
        self.assertEqual(progress["clip_count"], 0)
        self.assertEqual(progress["total_prompts"], 160)
        self.assertFalse(progress["is_ready"])

    def _manifest_with_raw_audio(
        self,
        *,
        created_at: datetime,
    ) -> tuple[dict, str]:
        manifest = self.service._new_manifest("patient-001")
        manifest_key = self.service._manifest_key(
            "patient-001", manifest["job_id"]
        )
        clip_key = self.service._clip_key(
            "patient-001", manifest["job_id"], "S001.wav"
        )
        self.storage.put_bytes(
            clip_key, self.wave, content_type="audio/wav"
        )
        manifest["clips"] = [
            {
                "id": "clip-0123456789ab",
                "file_name": "S001.wav",
                "object_key": clip_key,
                "duration_seconds": 5,
                "prompt_text": self.service.script["prompts"][0]["text"],
                "size_bytes": len(self.wave),
                "created_at": created_at.isoformat(),
            }
        ]
        manifest["created_at"] = created_at.isoformat()
        manifest["updated_at"] = created_at.isoformat()
        self.storage.put_json(manifest_key, manifest)
        return manifest, clip_key

    def test_verified_model_schedules_and_deletes_raw_audio_after_24_hours(self) -> None:
        verified_at = datetime(2026, 10, 24, tzinfo=timezone.utc)
        manifest, clip_key = self._manifest_with_raw_audio(
            created_at=verified_at - timedelta(days=1)
        )
        retention = self.service.schedule_raw_audio_deletion(
            patient_id="patient-001",
            job_id=manifest["job_id"],
            verified_at=verified_at,
        )
        self.assertEqual(retention["status"], "scheduled")

        early = self.service.cleanup_expired_raw_audio(
            now=verified_at + timedelta(hours=23, minutes=59)
        )
        self.assertEqual(early["objects_deleted"], 0)
        self.assertTrue(self.storage.object_exists(clip_key))

        due = self.service.cleanup_expired_raw_audio(
            now=verified_at + timedelta(hours=24)
        )
        self.assertEqual(due["objects_deleted"], 1)
        self.assertFalse(self.storage.object_exists(clip_key))
        stored = self.storage.get_json(
            self.service._manifest_key("patient-001", manifest["job_id"])
        )
        assert stored is not None
        self.assertEqual(stored["raw_audio_retention"]["status"], "deleted")
        self.assertNotIn("object_key", stored["clips"][0])

    def test_raw_audio_has_absolute_14_day_retention_cap(self) -> None:
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        manifest, clip_key = self._manifest_with_raw_audio(
            created_at=now - timedelta(days=14)
        )
        result = self.service.cleanup_expired_raw_audio(now=now)
        self.assertEqual(result["objects_deleted"], 1)
        self.assertFalse(self.storage.object_exists(clip_key))
        stored = self.storage.get_json(
            self.service._manifest_key("patient-001", manifest["job_id"])
        )
        assert stored is not None
        self.assertEqual(
            stored["raw_audio_retention"]["reason"],
            "hard_retention_limit",
        )

    def test_existing_successful_install_ack_backfills_retention(self) -> None:
        verified_at = datetime(2026, 10, 24, tzinfo=timezone.utc)
        manifest, _ = self._manifest_with_raw_audio(
            created_at=verified_at - timedelta(days=1)
        )
        self.storage.put_json(
            "devices/pi5-home-01/voice-model-installs/"
            "voice-model-0123456789ab.json",
            {
                "patient_id": "patient-001",
                "model_id": "voice-model-0123456789ab",
                "version": manifest["job_id"],
                "status": "installed",
                "reported_at": verified_at.isoformat(),
            },
        )
        result = self.service.reconcile_verified_installations()
        self.assertEqual(result["jobs_scheduled"], 1)
        stored = self.storage.get_json(
            self.service._manifest_key("patient-001", manifest["job_id"])
        )
        assert stored is not None
        self.assertEqual(
            stored["raw_audio_retention"]["delete_after"],
            (verified_at + timedelta(hours=24)).isoformat(),
        )

    def test_rejects_prompt_text_that_does_not_match(self) -> None:
        with self.assertRaises(InvalidVoiceTrainingRequest):
            self.service.upload_clip(
                patient_id="patient-001",
                file_name="S001.wav",
                prompt_text="잘못된 문장",
                duration_seconds=5,
                audio=self.wave,
            )

        self.assertEqual(self.storage.byte_objects, {})
        self.assertEqual(self.storage.json_objects, {})

    def test_uploads_first_clip_and_rejects_duplicate(self) -> None:
        prompt = self.service.prompts_by_file_name["S001.wav"]

        progress = self.service.upload_clip(
            patient_id="patient-001",
            file_name="S001.wav",
            prompt_text=prompt["text"],
            duration_seconds=5,
            audio=self.wave,
        )

        self.assertEqual(progress["job_status"], "collecting")
        self.assertEqual(progress["clip_count"], 1)
        self.assertFalse(progress["is_ready"])
        self.assertTrue(progress["job_id"].startswith("voice-job-"))

        with self.assertRaises(DuplicateVoiceTrainingClip):
            self.service.upload_clip(
                patient_id="patient-001",
                file_name="S001.wav",
                prompt_text=prompt["text"],
                duration_seconds=5,
                audio=self.wave,
            )

    def test_final_script_clip_auto_queues_below_recommended_seconds(self) -> None:
        progress = None
        progress_before_final = None

        for prompt in self.service.script["prompts"]:
            progress = self.service.upload_clip(
                patient_id="patient-001",
                file_name=prompt["file_name"],
                prompt_text=prompt["text"],
                duration_seconds=1,
                audio=self.wave,
            )
            if progress["clip_count"] == 159:
                progress_before_final = progress

        self.assertIsNotNone(progress)
        self.assertIsNotNone(progress_before_final)
        assert progress is not None
        assert progress_before_final is not None

        self.assertEqual(progress_before_final["job_status"], "collecting")
        self.assertEqual(progress["clip_count"], 160)
        self.assertEqual(progress["recorded_seconds"], 160)
        self.assertEqual(progress["remaining_seconds"], 640)
        self.assertEqual(progress["job_status"], "queued")
        self.assertFalse(progress["is_ready"])

        input_keys = [
            key
            for key in self.storage.byte_objects
            if "/input/" in key
        ]
        self.assertEqual(len(input_keys), 160)

        manifest = self.service.get_active_manifest("patient-001")
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest["status"], "queued")
        self.assertEqual(manifest["queued_at"], manifest["updated_at"])

        claim = self.service.claim_next_job(worker_id="gpu-pc-test")
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim["job_id"], progress["job_id"])
        self.assertEqual(len(claim["manifest"]["clips"]), 160)

        first_prompt = self.service.prompts_by_file_name["S001.wav"]
        with self.assertRaises(InvalidVoiceTrainingRequest):
            self.service.upload_clip(
                patient_id="patient-001",
                file_name="S161.wav",
                prompt_text=first_prompt["text"],
                duration_seconds=6,
                audio=self.wave,
            )

    def test_240_prompt_script_accepts_fixed_additional_clip(self) -> None:
        script = copy.deepcopy(self.service.script)
        script["prompts"].extend(
            {"file_name": f"S{number:03d}.wav", "text": f"추가 문장 {number}"}
            for number in range(161, 241)
        )
        script["total_prompts"] = 240

        with tempfile.TemporaryDirectory() as directory:
            script_path = Path(directory) / "voice_training_script.json"
            script_path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
            service = VoiceTrainingService(self.storage, script_path=script_path)
            progress = service.upload_clip(
                patient_id="patient-001",
                file_name="S161.wav",
                prompt_text="추가 문장 161",
                duration_seconds=6,
                audio=self.wave,
            )

        self.assertEqual(progress["clip_count"], 1)
        self.assertEqual(progress["total_prompts"], 240)
        self.assertEqual(progress["job_status"], "collecting")

    def _create_queued_job(self, patient_id: str = "patient-001") -> dict:
        manifest = self.service._new_manifest(patient_id)
        manifest["status"] = "queued"
        manifest["queued_at"] = "2026-09-11T00:00:00+00:00"
        manifest_key = self.service._manifest_key(
            patient_id,
            manifest["job_id"],
        )
        self.storage.put_json(manifest_key, manifest)
        return manifest

    def _result_artifacts(self) -> tuple[dict, dict[str, bytes]]:
        names = (
            "model.onnx",
            "model.onnx.json",
            "test.wav",
            "manifest.json",
            "status.json",
            "training.log",
        )
        data_by_name = {
            name: f"test artifact: {name}".encode("utf-8")
            for name in names
        }
        descriptors = {}
        for name, data in data_by_name.items():
            descriptors[name] = {
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "content_md5": base64.b64encode(
                    hashlib.md5(data, usedforsecurity=False).digest()
                ).decode("ascii"),
            }
        return descriptors, data_by_name

    def test_only_one_worker_can_claim_a_queued_job(self) -> None:
        manifest = self._create_queued_job()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)

        first = self.service.claim_next_job(
            worker_id="gpu-pc-one",
            lease_seconds=300,
            now=now,
        )
        second = self.service.claim_next_job(
            worker_id="gpu-pc-two",
            lease_seconds=300,
            now=now,
        )

        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first["job_id"], manifest["job_id"])
        self.assertEqual(first["attempt"], 1)
        self.assertIsNone(second)

        claim_key = self.service._claim_key(
            "patient-001",
            manifest["job_id"],
        )
        stored_claim = self.storage.get_json(claim_key)
        assert stored_claim is not None
        self.assertNotIn("lease_token", stored_claim)
        self.assertIn("lease_token_sha256", stored_claim)

    def test_expired_claim_can_be_recovered(self) -> None:
        self._create_queued_job()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)

        first = self.service.claim_next_job(
            worker_id="gpu-pc-one",
            lease_seconds=60,
            now=now,
        )
        recovered = self.service.claim_next_job(
            worker_id="gpu-pc-two",
            lease_seconds=60,
            now=now + timedelta(seconds=61),
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(recovered)
        assert first is not None
        assert recovered is not None
        self.assertNotEqual(first["claim_id"], recovered["claim_id"])
        self.assertEqual(recovered["attempt"], 2)
        self.assertEqual(recovered["worker_id"], "gpu-pc-two")

        with self.assertRaises(VoiceTrainingClaimError):
            self.service.update_claim_status(
                patient_id="patient-001",
                job_id=first["job_id"],
                claim_id=first["claim_id"],
                lease_token=first["lease_token"],
                state="training",
                now=now + timedelta(seconds=62),
            )

    def test_claim_owner_can_renew_lease_and_update_status(self) -> None:
        self._create_queued_job()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        claim = self.service.claim_next_job(
            worker_id="gpu-pc-one",
            lease_seconds=60,
            now=now,
        )
        assert claim is not None

        status = self.service.update_claim_status(
            patient_id=claim["patient_id"],
            job_id=claim["job_id"],
            claim_id=claim["claim_id"],
            lease_token=claim["lease_token"],
            state="training",
            message="Training subprocess is running",
            lease_seconds=300,
            now=now + timedelta(seconds=30),
        )

        self.assertEqual(status["status"], "training")
        self.assertEqual(
            status["lease_expires_at"],
            (now + timedelta(seconds=330)).isoformat(),
        )
        manifest = self.service.get_active_manifest("patient-001")
        assert manifest is not None
        self.assertEqual(manifest["status"], "training")
        self.assertEqual(
            manifest["worker_message"],
            "Training subprocess is running",
        )

    def test_wrong_lease_token_cannot_update_status(self) -> None:
        self._create_queued_job()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        claim = self.service.claim_next_job(
            worker_id="gpu-pc-one",
            lease_seconds=60,
            now=now,
        )
        assert claim is not None

        with self.assertRaises(VoiceTrainingClaimError):
            self.service.update_claim_status(
                patient_id=claim["patient_id"],
                job_id=claim["job_id"],
                claim_id=claim["claim_id"],
                lease_token="wrong-token",
                state="training",
                now=now + timedelta(seconds=1),
            )

    def test_job_completes_only_after_every_artifact_is_uploaded(self) -> None:
        self._create_queued_job()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        claim = self.service.claim_next_job(
            worker_id="gpu-pc-one",
            lease_seconds=600,
            now=now,
        )
        assert claim is not None
        descriptors, data_by_name = self._result_artifacts()
        plan = self.service.create_upload_plan(
            patient_id=claim["patient_id"],
            job_id=claim["job_id"],
            claim_id=claim["claim_id"],
            lease_token=claim["lease_token"],
            artifacts=descriptors,
            now=now + timedelta(seconds=1),
        )

        for name, artifact in plan["artifacts"].items():
            if name == "training.log":
                continue
            self.storage.simulate_artifact_upload(
                artifact["object_key"],
                data_by_name[name],
                sha256=artifact["sha256"],
            )

        with self.assertRaises(VoiceTrainingJobStateError):
            self.service.complete_job(
                patient_id=claim["patient_id"],
                job_id=claim["job_id"],
                claim_id=claim["claim_id"],
                lease_token=claim["lease_token"],
                now=now + timedelta(seconds=2),
            )

        manifest = self.service.get_active_manifest("patient-001")
        assert manifest is not None
        self.assertNotEqual(manifest["status"], "completed")

        missing = plan["artifacts"]["training.log"]
        self.storage.simulate_artifact_upload(
            missing["object_key"],
            data_by_name["training.log"],
            sha256=missing["sha256"],
        )
        completed = self.service.complete_job(
            patient_id=claim["patient_id"],
            job_id=claim["job_id"],
            claim_id=claim["claim_id"],
            lease_token=claim["lease_token"],
            now=now + timedelta(seconds=3),
        )

        self.assertEqual(completed["status"], "completed")
        manifest = self.service.get_active_manifest("patient-001")
        assert manifest is not None
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(manifest["result"]["artifacts"]), 6)

        repeated = self.service.complete_job(
            patient_id=claim["patient_id"],
            job_id=claim["job_id"],
            claim_id=claim["claim_id"],
            lease_token=claim["lease_token"],
            now=now + timedelta(seconds=4),
        )
        self.assertEqual(repeated["status"], "completed")

    def test_retryable_failure_is_claimed_after_delay(self) -> None:
        self._create_queued_job()
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        claim = self.service.claim_next_job(
            worker_id="gpu-pc-one",
            lease_seconds=60,
            now=now,
        )
        assert claim is not None

        failed = self.service.fail_job(
            patient_id=claim["patient_id"],
            job_id=claim["job_id"],
            claim_id=claim["claim_id"],
            lease_token=claim["lease_token"],
            failed_stage="TRAINING",
            error="Mock subprocess failed",
            retryable=True,
            retry_delay_seconds=60,
            now=now + timedelta(seconds=1),
        )

        self.assertTrue(failed["retryable"])
        self.assertIsNone(
            self.service.claim_next_job(
                worker_id="gpu-pc-two",
                lease_seconds=60,
                now=now + timedelta(seconds=30),
            )
        )
        retried = self.service.claim_next_job(
            worker_id="gpu-pc-two",
            lease_seconds=60,
            now=now + timedelta(seconds=62),
        )
        self.assertIsNotNone(retried)
        assert retried is not None
        self.assertEqual(retried["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
