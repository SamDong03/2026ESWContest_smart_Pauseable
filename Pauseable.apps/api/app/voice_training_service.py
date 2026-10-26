from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_SCRIPT_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "voice_training_script.json"
)

PATIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
JOB_ID_PATTERN = re.compile(r"^voice-job-[0-9a-f]{12}$")
TRAINING_FILE_PATTERN = re.compile(r"^S([0-9]{3,})\.wav$")
WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
JOB_MANIFEST_KEY_PATTERN = re.compile(
    r"^patients/(?P<patient_id>[A-Za-z0-9_-]{1,64})/"
    r"voice-training/jobs/(?P<job_id>voice-job-[0-9a-f]{12})/"
    r"manifest\.json$"
)
MODEL_INSTALL_KEY_PATTERN = re.compile(
    r"^devices/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/voice-model-installs/"
    r"voice-model-[0-9a-f]{12}\.json$"
)
CLAIM_ID_PATTERN = re.compile(r"^claim-[0-9a-f]{32}$")
WORKER_PROGRESS_STATES = frozenset(
    {
        "claimed",
        "downloading",
        "preprocessing",
        "training",
        "exporting",
        "validating_model",
        "uploading",
    }
)
MAX_WORKER_ATTEMPTS = 3
MIN_TRAINING_CLIPS = 160
MAX_TRAINING_CLIPS = 240
REQUIRED_RESULT_ARTIFACTS = {
    "model.onnx": "application/octet-stream",
    "model.onnx.json": "application/json; charset=utf-8",
    "test.wav": "audio/wav",
    "manifest.json": "application/json; charset=utf-8",
    "status.json": "application/json; charset=utf-8",
    "training.log": "text/plain; charset=utf-8",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RAW_AUDIO_ACK_GRACE = timedelta(hours=24)
RAW_AUDIO_HARD_RETENTION = timedelta(days=14)


class InvalidVoiceTrainingRequest(ValueError):
    pass


class DuplicateVoiceTrainingClip(FileExistsError):
    pass


class VoiceTrainingJobStateError(RuntimeError):
    pass


class VoiceTrainingClaimError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("Worker claim timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


class VoiceTrainingService:
    def __init__(
        self,
        storage: Any,
        *,
        script_path: Path = DEFAULT_SCRIPT_PATH,
    ) -> None:
        self.storage = storage
        self.script_path = script_path
        self.script = self._load_script()

        prompts = self.script["prompts"]
        self.prompts_by_file_name = {
            prompt["file_name"]: prompt
            for prompt in prompts
        }
        self.expected_file_names = tuple(
            f"S{index:03d}.wav"
            for index in range(1, len(prompts) + 1)
        )

        actual_file_names = tuple(
            prompt["file_name"]
            for prompt in prompts
        )

        if actual_file_names != self.expected_file_names:
            raise RuntimeError(
                "Voice training script must contain "
                "consecutive S001.wav filenames in order"
            )

    def _load_script(self) -> dict[str, Any]:
        with self.script_path.open(encoding="utf-8") as source:
            script = json.load(source)

        prompts = script.get("prompts")
        if not isinstance(prompts, list) or not MIN_TRAINING_CLIPS <= len(prompts) <= MAX_TRAINING_CLIPS:
            raise RuntimeError(
                "Voice training script must contain 160 to 240 prompts"
            )

        if int(script.get("total_prompts", 0)) != len(prompts):
            raise RuntimeError(
                "Voice training script total_prompts must match prompts"
            )

        return script

    def _validate_patient_id(self, patient_id: str) -> None:
        if not PATIENT_ID_PATTERN.fullmatch(patient_id):
            raise InvalidVoiceTrainingRequest("Invalid patient id")

    def _validate_job_id(self, job_id: str) -> None:
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise InvalidVoiceTrainingRequest("Invalid voice training job id")

    def _prompt_for_file_name(self, file_name: str) -> dict[str, Any]:
        match = TRAINING_FILE_PATTERN.fullmatch(file_name)
        if match is None:
            raise InvalidVoiceTrainingRequest(
                "Training file must use the S001.wav numbering format"
            )

        clip_number = int(match.group(1))
        if not 1 <= clip_number <= len(self.script["prompts"]):
            raise InvalidVoiceTrainingRequest(
                "Training clip number must match a fixed script prompt"
            )
        return self.script["prompts"][clip_number - 1]

    def _active_job_key(self, patient_id: str) -> str:
        self._validate_patient_id(patient_id)
        return (
            f"patients/{patient_id}/voice-training/"
            "active.json"
        )

    def _job_prefix(
        self,
        patient_id: str,
        job_id: str,
    ) -> str:
        self._validate_patient_id(patient_id)
        self._validate_job_id(job_id)
        return (
            f"patients/{patient_id}/voice-training/"
            f"jobs/{job_id}"
        )

    def _manifest_key(
        self,
        patient_id: str,
        job_id: str,
    ) -> str:
        return f"{self._job_prefix(patient_id, job_id)}/manifest.json"

    def _claim_key(
        self,
        patient_id: str,
        job_id: str,
    ) -> str:
        return f"{self._job_prefix(patient_id, job_id)}/claim.json"

    def _clip_key(
        self,
        patient_id: str,
        job_id: str,
        file_name: str,
    ) -> str:
        return (
            f"{self._job_prefix(patient_id, job_id)}"
            f"/input/{file_name}"
        )

    def _empty_manifest(
        self,
        patient_id: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        job_id = f"voice-job-{uuid.uuid4().hex[:12]}"

        manifest: dict[str, Any] = {
            "schema_version": 1,
            "script_version": self.script["version"],
            "patient_id": patient_id,
            "job_id": job_id,
            "status": "collecting",
            "target_seconds": int(self.script["target_seconds"]),
            "target_clips": MIN_TRAINING_CLIPS,
            "clips": [],
            "created_at": now,
            "updated_at": now,
        }

        return manifest

    def _new_manifest(self, patient_id: str) -> dict[str, Any]:
        manifest = self._empty_manifest(patient_id)
        self.storage.put_json(
            self._manifest_key(patient_id, manifest["job_id"]), manifest,
        )
        self.storage.put_json(
            self._active_job_key(patient_id),
            {
                "patient_id": patient_id,
                "job_id": manifest["job_id"],
                "updated_at": manifest["updated_at"],
            },
        )
        return manifest

    def start_new_session(self, patient_id: str, previous_job_id: str) -> dict[str, Any]:
        pass
        self._validate_patient_id(patient_id)
        self._validate_job_id(previous_job_id)
        pointer_key = self._active_job_key(patient_id)
        stored = self.storage.get_json_with_etag(pointer_key)
        if stored is None:
            raise VoiceTrainingJobStateError("Complete the current voice training set first")
        pointer, etag = stored
        active = self.get_active_manifest(patient_id)
        if active is None or active["job_id"] != pointer.get("job_id"):
            raise VoiceTrainingJobStateError("Voice training session changed; refresh first")
        if active["job_id"] != previous_job_id:


            if pointer.get("previous_job_id") == previous_job_id:
                return self.serialize_progress(active, patient_id=patient_id)
            raise VoiceTrainingJobStateError("Voice training session changed; refresh first")
        if active["status"] != "completed":
            raise VoiceTrainingJobStateError("Only a completed training set can start a new session")
        manifest = self._empty_manifest(patient_id)
        manifest["previous_job_id"] = previous_job_id
        manifest["requires_explicit_job_id"] = True
        manifest_key = self._manifest_key(patient_id, manifest["job_id"])
        self.storage.put_json(manifest_key, manifest)
        new_pointer = {
            "patient_id": patient_id, "job_id": manifest["job_id"],
            "previous_job_id": previous_job_id, "updated_at": manifest["updated_at"],
        }
        changed = self.storage.put_json_if_match(pointer_key, new_pointer, etag)
        if changed is None:


            current = self.storage.get_json(pointer_key)
            if current and current.get("job_id") == manifest["job_id"]:
                return self.serialize_progress(manifest, patient_id=patient_id)
            if current and current.get("previous_job_id") == previous_job_id:
                winner = self.get_active_manifest(patient_id)
                if winner is not None:
                    self.storage.delete_object(manifest_key)
                    return self.serialize_progress(winner, patient_id=patient_id)
            raise VoiceTrainingJobStateError("Voice training session changed; refresh first")
        return self.serialize_progress(manifest, patient_id=patient_id)

    def get_active_manifest(
        self,
        patient_id: str,
    ) -> dict[str, Any] | None:
        pointer = self.storage.get_json(
            self._active_job_key(patient_id)
        )

        if pointer is None:
            return None

        job_id = str(pointer.get("job_id", ""))
        self._validate_job_id(job_id)

        manifest = self.storage.get_json(
            self._manifest_key(patient_id, job_id)
        )
        if manifest is None:
            raise VoiceTrainingJobStateError(
                "Active voice training manifest is missing"
            )

        return manifest

    def serialize_progress(
        self,
        manifest: dict[str, Any] | None,
        *,
        patient_id: str,
    ) -> dict[str, Any]:
        target_seconds = int(self.script["target_seconds"])

        if manifest is None:
            return {
                "patient_id": patient_id,
                "job_id": None,
                "job_status": "not_started",
                "target_seconds": target_seconds,
                "recorded_seconds": 0,
                "remaining_seconds": target_seconds,
                "clip_count": 0,
                "total_prompts": len(self.script["prompts"]),
                "is_ready": False,
            }

        clips = manifest["clips"]
        recorded_seconds = sum(
            int(clip["duration_seconds"])
            for clip in clips
        )
        is_ready = recorded_seconds >= target_seconds

        return {
            "patient_id": patient_id,
            "job_id": manifest["job_id"],
            "job_status": manifest["status"],
            "target_seconds": target_seconds,
            "recorded_seconds": recorded_seconds,
            "remaining_seconds": max(
                0,
                target_seconds - recorded_seconds,
            ),
            "clip_count": len(clips),
            "total_prompts": len(self.script["prompts"]),
            "is_ready": is_ready,
        }

    def get_progress(
        self,
        patient_id: str,
    ) -> dict[str, Any]:
        self._validate_patient_id(patient_id)
        manifest = self.get_active_manifest(patient_id)

        return self.serialize_progress(
            manifest,
            patient_id=patient_id,
        )

    def _queued_manifest_keys(self) -> list[str]:
        return sorted(
            key
            for key in self.storage.list_keys("patients/")
            if JOB_MANIFEST_KEY_PATTERN.fullmatch(key)
        )

    def schedule_raw_audio_deletion(
        self,
        *,
        patient_id: str,
        job_id: str,
        verified_at: datetime | None = None,
    ) -> dict[str, Any]:
        pass
        self._validate_patient_id(patient_id)
        self._validate_job_id(job_id)
        scheduled_at = _as_utc(verified_at)
        manifest_key = self._manifest_key(patient_id, job_id)
        stored = self.storage.get_json_with_etag(manifest_key)
        if stored is None:
            raise VoiceTrainingJobStateError(
                "Source voice training manifest is missing"
            )
        manifest, etag = stored
        retention = manifest.get("raw_audio_retention")
        if isinstance(retention, dict) and retention.get("status") == "deleted":
            return retention

        created_at = _parse_timestamp(manifest.get("created_at"))
        hard_delete_after = (
            created_at + RAW_AUDIO_HARD_RETENTION
            if created_at is not None
            else scheduled_at + RAW_AUDIO_HARD_RETENTION
        )
        delete_after = min(
            scheduled_at + RAW_AUDIO_ACK_GRACE,
            hard_delete_after,
        )
        if isinstance(retention, dict):
            existing_deadline = _parse_timestamp(retention.get("delete_after"))
            if existing_deadline is not None:
                delete_after = min(delete_after, existing_deadline)

        updated = dict(manifest)
        updated["raw_audio_retention"] = {
            "status": "scheduled",
            "scheduled_at": scheduled_at.isoformat(),
            "delete_after": delete_after.isoformat(),
            "hard_delete_after": hard_delete_after.isoformat(),
            "reason": "device_model_verified",
        }
        updated["updated_at"] = scheduled_at.isoformat()
        if self.storage.put_json_if_match(manifest_key, updated, etag) is None:
            raise VoiceTrainingJobStateError(
                "Voice training manifest changed while scheduling deletion"
            )
        return updated["raw_audio_retention"]

    def reconcile_verified_installations(self) -> dict[str, int]:
        pass
        result = {"installations_checked": 0, "jobs_scheduled": 0}
        install_keys = sorted(
            key for key in self.storage.list_keys("devices/")
            if MODEL_INSTALL_KEY_PATTERN.fullmatch(key)
        )
        for install_key in install_keys:
            result["installations_checked"] += 1
            installation = self.storage.get_json(install_key)
            if not isinstance(installation, dict):
                continue
            if installation.get("status") != "installed":
                continue
            patient_id = installation.get("patient_id")
            source_job_id = installation.get("source_job_id")
            if source_job_id is None:
                source_job_id = installation.get("version")
            verified_at = _parse_timestamp(installation.get("reported_at"))
            if (
                not isinstance(patient_id, str)
                or not isinstance(source_job_id, str)
                or not PATIENT_ID_PATTERN.fullmatch(patient_id)
                or not JOB_ID_PATTERN.fullmatch(source_job_id)
                or verified_at is None
            ):
                continue
            manifest = self.storage.get_json(
                self._manifest_key(patient_id, source_job_id)
            )
            if not isinstance(manifest, dict):
                continue
            retention = manifest.get("raw_audio_retention")
            if isinstance(retention, dict) and retention.get("status") in {
                "scheduled",
                "deleted",
            }:
                continue
            self.schedule_raw_audio_deletion(
                patient_id=patient_id,
                job_id=source_job_id,
                verified_at=verified_at,
            )
            result["jobs_scheduled"] += 1
        return result

    def cleanup_expired_raw_audio(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        pass
        checked_at = _as_utc(now)
        result = {
            "manifests_checked": 0,
            "jobs_cleaned": 0,
            "objects_deleted": 0,
        }
        for manifest_key in self._queued_manifest_keys():
            result["manifests_checked"] += 1
            stored = self.storage.get_json_with_etag(manifest_key)
            if stored is None:
                continue
            manifest, etag = stored
            retention = manifest.get("raw_audio_retention")
            if isinstance(retention, dict) and retention.get("status") == "deleted":
                continue

            created_at = _parse_timestamp(manifest.get("created_at"))
            hard_deadline = (
                created_at + RAW_AUDIO_HARD_RETENTION
                if created_at is not None
                else None
            )
            scheduled_deadline = (
                _parse_timestamp(retention.get("delete_after"))
                if isinstance(retention, dict)
                else None
            )
            deadlines = [
                value for value in (scheduled_deadline, hard_deadline)
                if value is not None
            ]
            if not deadlines or min(deadlines) > checked_at:
                continue

            match = JOB_MANIFEST_KEY_PATTERN.fullmatch(manifest_key)
            assert match is not None
            patient_id = match.group("patient_id")
            job_id = match.group("job_id")
            input_prefix = f"{self._job_prefix(patient_id, job_id)}/input/"
            clips = manifest.get("clips")
            if not isinstance(clips, list):
                clips = []
            sanitized_clips: list[dict[str, Any]] = []
            deleted_count = 0
            for clip in clips:
                if not isinstance(clip, dict):
                    continue
                object_key = clip.get("object_key")
                if isinstance(object_key, str) and object_key.startswith(input_prefix):
                    self.storage.delete_object(object_key)
                    deleted_count += 1
                sanitized = dict(clip)
                sanitized.pop("object_key", None)
                sanitized["raw_audio_deleted"] = True
                sanitized_clips.append(sanitized)

            sanitized_result = manifest.get("result")
            if isinstance(sanitized_result, dict):
                sanitized_result = dict(sanitized_result)
                artifacts = sanitized_result.get("artifacts")
                if isinstance(artifacts, dict):
                    sanitized_artifacts: dict[str, dict[str, Any]] = {}
                    artifact_prefix = (
                        self._job_prefix(patient_id, job_id) + "/attempts/"
                    )
                    for name, descriptor in artifacts.items():
                        if not isinstance(descriptor, dict):
                            continue
                        object_key = descriptor.get("object_key")
                        if (
                            isinstance(object_key, str)
                            and object_key.startswith(artifact_prefix)
                        ):
                            self.storage.delete_object(object_key)
                            deleted_count += 1
                        sanitized_descriptor = dict(descriptor)
                        sanitized_descriptor.pop("object_key", None)
                        sanitized_descriptor["artifact_deleted"] = True
                        sanitized_artifacts[name] = sanitized_descriptor
                    sanitized_result["artifacts"] = sanitized_artifacts

            updated = dict(manifest)
            updated["clips"] = sanitized_clips
            if isinstance(sanitized_result, dict):
                updated["result"] = sanitized_result
            reason = (
                "device_model_verified"
                if scheduled_deadline is not None
                and scheduled_deadline <= checked_at
                else "hard_retention_limit"
            )
            updated["raw_audio_retention"] = {
                "status": "deleted",
                "deleted_at": checked_at.isoformat(),
                "reason": reason,
                "deleted_object_count": deleted_count,
            }
            updated["updated_at"] = checked_at.isoformat()
            if self.storage.put_json_if_match(
                manifest_key, updated, etag
            ) is None:
                raise VoiceTrainingJobStateError(
                    "Voice training manifest changed during retention cleanup"
                )
            result["jobs_cleaned"] += 1
            result["objects_deleted"] += deleted_count
        return result

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if not WORKER_ID_PATTERN.fullmatch(worker_id):
            raise InvalidVoiceTrainingRequest("Invalid worker id")
        if not 30 <= lease_seconds <= 3600:
            raise InvalidVoiceTrainingRequest(
                "Worker lease must be between 30 and 3600 seconds"
            )

        claimed_at = _as_utc(now)
        claimable: list[
            tuple[str, str, str, dict[str, Any], str]
        ] = []

        for manifest_key in self._queued_manifest_keys():
            match = JOB_MANIFEST_KEY_PATTERN.fullmatch(manifest_key)
            assert match is not None

            stored_manifest = self.storage.get_json_with_etag(manifest_key)
            if stored_manifest is None:
                continue

            manifest, manifest_etag = stored_manifest
            status = manifest.get("status")
            if status == "failed":
                next_retry_at = _parse_timestamp(
                    manifest.get("next_retry_at")
                )
                if (
                    manifest.get("retryable") is not True
                    or int(manifest.get("attempt_count", 0))
                    >= MAX_WORKER_ATTEMPTS
                    or (
                        next_retry_at is not None
                        and next_retry_at > claimed_at
                    )
                ):
                    continue
            elif status not in {"queued", "claimed"}:
                continue

            sort_timestamp = str(
                manifest.get("queued_at")
                or manifest.get("created_at")
                or ""
            )
            claimable.append(
                (
                    sort_timestamp,
                    match.group("patient_id"),
                    match.group("job_id"),
                    manifest,
                    manifest_etag,
                )
            )

        for _, patient_id, job_id, manifest, manifest_etag in sorted(
            claimable
        ):
            claim_key = self._claim_key(patient_id, job_id)
            stored_claim = self.storage.get_json_with_etag(claim_key)

            if stored_claim is not None:
                previous_claim, previous_claim_etag = stored_claim
                expires_at = _parse_timestamp(
                    previous_claim.get("lease_expires_at")
                )
                if expires_at is not None and expires_at > claimed_at:
                    continue
            else:
                previous_claim_etag = None

            claim_id = f"claim-{uuid.uuid4().hex}"
            lease_token = secrets.token_urlsafe(32)
            lease_expires_at = claimed_at + timedelta(
                seconds=lease_seconds
            )
            attempt = int(manifest.get("attempt_count", 0)) + 1
            claim = {
                "schema_version": 1,
                "patient_id": patient_id,
                "job_id": job_id,
                "claim_id": claim_id,
                "worker_id": worker_id,
                "attempt": attempt,
                "lease_token_sha256": _hash_secret(lease_token),
                "claimed_at": claimed_at.isoformat(),
                "heartbeat_at": claimed_at.isoformat(),
                "lease_expires_at": lease_expires_at.isoformat(),
            }

            if previous_claim_etag is None:
                claim_etag = self.storage.put_json_if_absent(
                    claim_key,
                    claim,
                )
            else:
                claim_etag = self.storage.put_json_if_match(
                    claim_key,
                    claim,
                    previous_claim_etag,
                )

            if claim_etag is None:
                continue

            updated_manifest = dict(manifest)
            updated_manifest.update(
                {
                    "status": "claimed",
                    "attempt_count": attempt,
                    "active_claim_id": claim_id,
                    "claimed_by": worker_id,
                    "claimed_at": claimed_at.isoformat(),
                    "lease_expires_at": lease_expires_at.isoformat(),
                    "updated_at": claimed_at.isoformat(),
                }
            )
            for stale_field in (
                "error",
                "failed_at",
                "failed_stage",
                "next_retry_at",
                "retryable",
            ):
                updated_manifest.pop(stale_field, None)

            updated_etag = self.storage.put_json_if_match(
                self._manifest_key(patient_id, job_id),
                updated_manifest,
                manifest_etag,
            )
            if updated_etag is None:
                released_claim = dict(claim)
                released_claim["lease_expires_at"] = claimed_at.isoformat()
                released_claim["released_at"] = claimed_at.isoformat()
                self.storage.put_json_if_match(
                    claim_key,
                    released_claim,
                    claim_etag,
                )
                continue

            return {
                "patient_id": patient_id,
                "job_id": job_id,
                "claim_id": claim_id,
                "lease_token": lease_token,
                "worker_id": worker_id,
                "attempt": attempt,
                "lease_expires_at": lease_expires_at.isoformat(),
                "manifest": updated_manifest,
            }

        return None

    def update_claim_status(
        self,
        *,
        patient_id: str,
        job_id: str,
        claim_id: str,
        lease_token: str,
        state: str | None = None,
        message: str | None = None,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._validate_patient_id(patient_id)
        self._validate_job_id(job_id)
        if not CLAIM_ID_PATTERN.fullmatch(claim_id):
            raise InvalidVoiceTrainingRequest("Invalid worker claim id")
        if not lease_token or len(lease_token) > 256:
            raise InvalidVoiceTrainingRequest("Invalid worker lease token")
        if state is not None and state not in WORKER_PROGRESS_STATES:
            raise InvalidVoiceTrainingRequest("Invalid worker progress state")
        if message is not None and len(message) > 1000:
            raise InvalidVoiceTrainingRequest(
                "Worker status message must be at most 1000 characters"
            )
        if not 30 <= lease_seconds <= 3600:
            raise InvalidVoiceTrainingRequest(
                "Worker lease must be between 30 and 3600 seconds"
            )

        heartbeat_at = _as_utc(now)
        claim_key = self._claim_key(patient_id, job_id)
        stored_claim = self.storage.get_json_with_etag(claim_key)
        if stored_claim is None:
            raise VoiceTrainingClaimError("Worker claim does not exist")

        claim, claim_etag = stored_claim
        expires_at = _parse_timestamp(claim.get("lease_expires_at"))
        if expires_at is None or expires_at <= heartbeat_at:
            raise VoiceTrainingClaimError("Worker claim has expired")
        if claim.get("claim_id") != claim_id:
            raise VoiceTrainingClaimError(
                "Worker claim belongs to another attempt"
            )
        if not secrets.compare_digest(
            str(claim.get("lease_token_sha256", "")),
            _hash_secret(lease_token),
        ):
            raise VoiceTrainingClaimError("Invalid worker lease token")

        lease_expires_at = heartbeat_at + timedelta(
            seconds=lease_seconds
        )
        updated_claim = dict(claim)
        updated_claim.update(
            {
                "heartbeat_at": heartbeat_at.isoformat(),
                "lease_expires_at": lease_expires_at.isoformat(),
            }
        )
        updated_claim_etag = self.storage.put_json_if_match(
            claim_key,
            updated_claim,
            claim_etag,
        )
        if updated_claim_etag is None:
            raise VoiceTrainingClaimError(
                "Worker claim changed during heartbeat"
            )

        manifest_key = self._manifest_key(patient_id, job_id)
        stored_manifest = self.storage.get_json_with_etag(manifest_key)
        if stored_manifest is None:
            raise VoiceTrainingJobStateError(
                "Claimed voice training manifest is missing"
            )

        manifest, manifest_etag = stored_manifest
        if manifest.get("active_claim_id") != claim_id:
            raise VoiceTrainingClaimError(
                "Voice training job belongs to another claim"
            )
        if manifest.get("status") in {"completed", "failed"}:
            raise VoiceTrainingJobStateError(
                "Voice training job is already in a terminal state"
            )

        updated_manifest = dict(manifest)
        updated_manifest.update(
            {
                "lease_expires_at": lease_expires_at.isoformat(),
                "heartbeat_at": heartbeat_at.isoformat(),
                "updated_at": heartbeat_at.isoformat(),
            }
        )
        if state is not None:
            updated_manifest["status"] = state
        if message is not None:
            updated_manifest["worker_message"] = message

        if self.storage.put_json_if_match(
            manifest_key,
            updated_manifest,
            manifest_etag,
        ) is None:
            raise VoiceTrainingJobStateError(
                "Voice training manifest changed during status update"
            )

        return {
            "patient_id": patient_id,
            "job_id": job_id,
            "claim_id": claim_id,
            "status": updated_manifest["status"],
            "heartbeat_at": heartbeat_at.isoformat(),
            "lease_expires_at": lease_expires_at.isoformat(),
        }

    def _load_active_claim(
        self,
        *,
        patient_id: str,
        job_id: str,
        claim_id: str,
        lease_token: str,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], str, datetime]:
        self._validate_patient_id(patient_id)
        self._validate_job_id(job_id)
        if not CLAIM_ID_PATTERN.fullmatch(claim_id):
            raise InvalidVoiceTrainingRequest("Invalid worker claim id")
        if not lease_token or len(lease_token) > 256:
            raise InvalidVoiceTrainingRequest("Invalid worker lease token")

        checked_at = _as_utc(now)
        stored_claim = self.storage.get_json_with_etag(
            self._claim_key(patient_id, job_id)
        )
        if stored_claim is None:
            raise VoiceTrainingClaimError("Worker claim does not exist")

        claim, claim_etag = stored_claim
        expires_at = _parse_timestamp(claim.get("lease_expires_at"))
        if expires_at is None or expires_at <= checked_at:
            raise VoiceTrainingClaimError("Worker claim has expired")
        if claim.get("claim_id") != claim_id:
            raise VoiceTrainingClaimError(
                "Worker claim belongs to another attempt"
            )
        if not secrets.compare_digest(
            str(claim.get("lease_token_sha256", "")),
            _hash_secret(lease_token),
        ):
            raise VoiceTrainingClaimError("Invalid worker lease token")

        return claim, claim_etag, checked_at

    def _validate_artifact_descriptors(
        self,
        artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if set(artifacts) != set(REQUIRED_RESULT_ARTIFACTS):
            raise InvalidVoiceTrainingRequest(
                "Worker artifacts must contain exactly: "
                + ", ".join(sorted(REQUIRED_RESULT_ARTIFACTS))
            )

        validated: dict[str, dict[str, Any]] = {}
        for name, content_type in REQUIRED_RESULT_ARTIFACTS.items():
            descriptor = artifacts[name]
            size_bytes = int(descriptor.get("size_bytes", 0))
            sha256 = str(descriptor.get("sha256", ""))
            content_md5 = str(descriptor.get("content_md5", ""))
            if size_bytes <= 0:
                raise InvalidVoiceTrainingRequest(
                    f"Worker artifact is empty: {name}"
                )
            if not SHA256_PATTERN.fullmatch(sha256):
                raise InvalidVoiceTrainingRequest(
                    f"Invalid SHA-256 for Worker artifact: {name}"
                )
            try:
                decoded_md5 = base64.b64decode(
                    content_md5,
                    validate=True,
                )
            except (ValueError, binascii.Error) as error:
                raise InvalidVoiceTrainingRequest(
                    f"Invalid Content-MD5 for Worker artifact: {name}"
                ) from error
            if len(decoded_md5) != 16:
                raise InvalidVoiceTrainingRequest(
                    f"Invalid Content-MD5 for Worker artifact: {name}"
                )

            validated[name] = {
                "size_bytes": size_bytes,
                "sha256": sha256,
                "content_md5": content_md5,
                "md5_hex": decoded_md5.hex(),
                "content_type": content_type,
            }

        return validated

    def create_upload_plan(
        self,
        *,
        patient_id: str,
        job_id: str,
        claim_id: str,
        lease_token: str,
        artifacts: dict[str, dict[str, Any]],
        expires_seconds: int = 3600,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not 300 <= expires_seconds <= 7200:
            raise InvalidVoiceTrainingRequest(
                "Upload URLs must expire between 300 and 7200 seconds"
            )
        validated = self._validate_artifact_descriptors(artifacts)
        self.update_claim_status(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=claim_id,
            lease_token=lease_token,
            state="uploading",
            message="Uploading validated training artifacts",
            now=now,
        )
        claim, _, planned_at = self._load_active_claim(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=claim_id,
            lease_token=lease_token,
            now=now,
        )

        attempt_prefix = (
            f"{self._job_prefix(patient_id, job_id)}/attempts/"
            f"{claim_id}/artifacts"
        )
        plan_artifacts: dict[str, dict[str, Any]] = {}
        stored_artifacts: dict[str, dict[str, Any]] = {}

        for name, descriptor in validated.items():
            object_key = f"{attempt_prefix}/{name}"
            stored_artifacts[name] = {
                **descriptor,
                "object_key": object_key,
            }
            plan_artifacts[name] = {
                **stored_artifacts[name],
                "upload_url": self.storage.create_upload_url(
                    object_key,
                    content_type=descriptor["content_type"],
                    expires_seconds=expires_seconds,
                    metadata={"sha256": descriptor["sha256"]},
                    content_md5=descriptor["content_md5"],
                    content_length=descriptor["size_bytes"],
                ),
                "headers": {
                    "Content-Type": descriptor["content_type"],
                    "Content-MD5": descriptor["content_md5"],
                    "Content-Length": str(descriptor["size_bytes"]),
                    "x-amz-meta-sha256": descriptor["sha256"],
                },
            }

        plan = {
            "schema_version": 1,
            "patient_id": patient_id,
            "job_id": job_id,
            "claim_id": claim_id,
            "attempt": claim["attempt"],
            "created_at": planned_at.isoformat(),
            "artifacts": stored_artifacts,
        }
        plan_key = f"{attempt_prefix}/upload-plan.json"
        existing_plan = self.storage.get_json(plan_key)
        if existing_plan is None:
            self.storage.put_json(plan_key, plan)
        elif existing_plan.get("artifacts") != stored_artifacts:
            raise VoiceTrainingJobStateError(
                "An upload plan already exists with different artifacts"
            )

        return {
            "patient_id": patient_id,
            "job_id": job_id,
            "claim_id": claim_id,
            "expires_seconds": expires_seconds,
            "artifacts": plan_artifacts,
        }

    def complete_job(
        self,
        *,
        patient_id: str,
        job_id: str,
        claim_id: str,
        lease_token: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        manifest_key = self._manifest_key(patient_id, job_id)
        existing_manifest = self.storage.get_json(manifest_key)
        if (
            existing_manifest is not None
            and existing_manifest.get("status") == "completed"
            and existing_manifest.get("completed_claim_id") == claim_id
        ):
            return {
                "patient_id": patient_id,
                "job_id": job_id,
                "claim_id": claim_id,
                "status": "completed",
                "completed_at": existing_manifest.get("completed_at"),
                "artifacts": existing_manifest.get("result", {}).get(
                    "artifacts",
                    {},
                ),
            }

        claim, claim_etag, completed_at = self._load_active_claim(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=claim_id,
            lease_token=lease_token,
            now=now,
        )
        attempt_prefix = (
            f"{self._job_prefix(patient_id, job_id)}/attempts/"
            f"{claim_id}/artifacts"
        )
        plan = self.storage.get_json(f"{attempt_prefix}/upload-plan.json")
        if plan is None:
            raise VoiceTrainingJobStateError("Worker upload plan is missing")

        artifacts = plan.get("artifacts")
        if not isinstance(artifacts, dict):
            raise VoiceTrainingJobStateError("Worker upload plan is invalid")

        for name in REQUIRED_RESULT_ARTIFACTS:
            descriptor = artifacts.get(name)
            if not isinstance(descriptor, dict):
                raise VoiceTrainingJobStateError(
                    f"Worker upload plan is missing artifact: {name}"
                )
            object_info = self.storage.head_object(descriptor["object_key"])
            if object_info is None:
                raise VoiceTrainingJobStateError(
                    f"Worker artifact was not uploaded: {name}"
                )
            if int(object_info["size_bytes"]) != int(
                descriptor["size_bytes"]
            ):
                raise VoiceTrainingJobStateError(
                    f"Worker artifact size mismatch: {name}"
                )
            if object_info.get("metadata", {}).get("sha256") != descriptor[
                "sha256"
            ]:
                raise VoiceTrainingJobStateError(
                    f"Worker artifact SHA-256 metadata mismatch: {name}"
                )
            if str(object_info.get("etag", "")).strip('"') != descriptor[
                "md5_hex"
            ]:
                raise VoiceTrainingJobStateError(
                    f"Worker artifact MD5 mismatch: {name}"
                )

        stored_manifest = self.storage.get_json_with_etag(manifest_key)
        if stored_manifest is None:
            raise VoiceTrainingJobStateError(
                "Claimed voice training manifest is missing"
            )
        manifest, manifest_etag = stored_manifest
        if manifest.get("active_claim_id") != claim_id:
            raise VoiceTrainingClaimError(
                "Voice training job belongs to another claim"
            )

        completed_manifest = dict(manifest)
        completed_manifest.update(
            {
                "status": "completed",
                "completed_at": completed_at.isoformat(),
                "updated_at": completed_at.isoformat(),
                "completed_claim_id": claim_id,
                "result": {
                    "attempt": claim["attempt"],
                    "artifacts": artifacts,
                },
            }
        )
        completed_manifest.pop("worker_message", None)
        if self.storage.put_json_if_match(
            manifest_key,
            completed_manifest,
            manifest_etag,
        ) is None:
            raise VoiceTrainingJobStateError(
                "Voice training manifest changed during completion"
            )

        completed_claim = dict(claim)
        completed_claim["completed_at"] = completed_at.isoformat()
        completed_claim["lease_expires_at"] = completed_at.isoformat()
        self.storage.put_json_if_match(
            self._claim_key(patient_id, job_id),
            completed_claim,
            claim_etag,
        )

        return {
            "patient_id": patient_id,
            "job_id": job_id,
            "claim_id": claim_id,
            "status": "completed",
            "completed_at": completed_at.isoformat(),
            "artifacts": artifacts,
        }

    def fail_job(
        self,
        *,
        patient_id: str,
        job_id: str,
        claim_id: str,
        lease_token: str,
        failed_stage: str,
        error: str,
        retryable: bool,
        retry_delay_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not failed_stage or len(failed_stage) > 64:
            raise InvalidVoiceTrainingRequest("Invalid failed stage")
        if not error or len(error) > 1000:
            raise InvalidVoiceTrainingRequest(
                "Worker error must be between 1 and 1000 characters"
            )
        if not 0 <= retry_delay_seconds <= 86400:
            raise InvalidVoiceTrainingRequest("Invalid retry delay")

        claim, claim_etag, failed_at = self._load_active_claim(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=claim_id,
            lease_token=lease_token,
            now=now,
        )
        manifest_key = self._manifest_key(patient_id, job_id)
        stored_manifest = self.storage.get_json_with_etag(manifest_key)
        if stored_manifest is None:
            raise VoiceTrainingJobStateError(
                "Claimed voice training manifest is missing"
            )
        manifest, manifest_etag = stored_manifest
        if manifest.get("active_claim_id") != claim_id:
            raise VoiceTrainingClaimError(
                "Voice training job belongs to another claim"
            )

        can_retry = (
            retryable
            and int(manifest.get("attempt_count", 0)) < MAX_WORKER_ATTEMPTS
        )
        failed_manifest = dict(manifest)
        failed_manifest.update(
            {
                "status": "failed",
                "failed_at": failed_at.isoformat(),
                "updated_at": failed_at.isoformat(),
                "failed_stage": failed_stage,
                "error": error,
                "retryable": can_retry,
                "next_retry_at": (
                    failed_at
                    + timedelta(seconds=retry_delay_seconds)
                ).isoformat()
                if can_retry
                else None,
            }
        )
        if self.storage.put_json_if_match(
            manifest_key,
            failed_manifest,
            manifest_etag,
        ) is None:
            raise VoiceTrainingJobStateError(
                "Voice training manifest changed during failure update"
            )

        failed_claim = dict(claim)
        failed_claim["failed_at"] = failed_at.isoformat()
        failed_claim["lease_expires_at"] = failed_at.isoformat()
        self.storage.put_json_if_match(
            self._claim_key(patient_id, job_id),
            failed_claim,
            claim_etag,
        )

        return {
            "patient_id": patient_id,
            "job_id": job_id,
            "claim_id": claim_id,
            "status": "failed",
            "failed_stage": failed_stage,
            "retryable": can_retry,
            "next_retry_at": failed_manifest["next_retry_at"],
        }

    def upload_clip(
        self,
        *,
        patient_id: str,
        file_name: str,
        prompt_text: str,
        duration_seconds: int,
        audio: bytes,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_patient_id(patient_id)
        if job_id is not None:
            self._validate_job_id(job_id)

        prompt = self._prompt_for_file_name(file_name)

        if _normalize_text(prompt_text) != _normalize_text(prompt["text"]):
            raise InvalidVoiceTrainingRequest(
                "Prompt text does not match the fixed training script"
            )

        if not 1 <= duration_seconds <= 45:
            raise InvalidVoiceTrainingRequest(
                "Training clip duration must be between 1 and 45 seconds"
            )

        manifest = self.get_active_manifest(patient_id)
        if manifest is None:
            if job_id is not None:
                raise VoiceTrainingJobStateError("Voice training session changed; refresh first")
            manifest = self._new_manifest(patient_id)

        manifest_key = self._manifest_key(patient_id, manifest["job_id"])
        stored_manifest = self.storage.get_json_with_etag(manifest_key)
        if stored_manifest is None:
            raise VoiceTrainingJobStateError(
                "Active voice training manifest is missing"
            )
        manifest, manifest_etag = stored_manifest

        if (job_id is not None and manifest["job_id"] != job_id) or (
            manifest.get("requires_explicit_job_id") and job_id is None
        ):
            raise VoiceTrainingJobStateError("Voice training session changed; refresh first")
        if manifest["status"] != "collecting":
            raise VoiceTrainingJobStateError(
                "The active voice training job is no longer collecting clips"
            )

        if any(
            clip["file_name"] == file_name
            for clip in manifest["clips"]
        ):
            raise DuplicateVoiceTrainingClip(
                f"{file_name} has already been uploaded"
            )

        job_id = manifest["job_id"]
        clip_key = self._clip_key(
            patient_id,
            job_id,
            file_name,
        )

        if self.storage.object_exists(clip_key):
            raise DuplicateVoiceTrainingClip(
                f"{file_name} already exists in object storage"
            )

        self.storage.put_bytes(
            clip_key,
            audio,
            content_type="audio/wav",
        )

        try:
            manifest["clips"].append(
                {
                    "id": f"clip-{uuid.uuid4().hex[:12]}",
                    "file_name": file_name,
                    "object_key": clip_key,
                    "duration_seconds": duration_seconds,
                    "prompt_text": prompt["text"],
                    "size_bytes": len(audio),
                    "created_at": _utc_now(),
                }
            )
            manifest["clips"].sort(
                key=lambda clip: clip["file_name"]
            )
            updated_at = _utc_now()
            manifest["updated_at"] = updated_at


            if len(manifest["clips"]) == len(self.script["prompts"]):
                manifest["status"] = "queued"
                manifest["queued_at"] = updated_at

            if self.storage.put_json_if_match(
                manifest_key, manifest, manifest_etag
            ) is None:
                raise VoiceTrainingJobStateError(
                    "Voice training job changed; reload progress and try again"
                )
        except Exception:
            self.storage.delete_object(clip_key)
            raise

        progress = self.serialize_progress(
            manifest,
            patient_id=patient_id,
        )
        progress["last_clip_id"] = manifest["clips"][-1]["id"]
        progress["status"] = "uploaded"
        return progress
