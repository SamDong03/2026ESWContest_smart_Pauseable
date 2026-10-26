from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any


PATIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MODEL_ID_PATTERN = re.compile(r"^voice-model-[0-9a-f]{12}$")
JOB_ID_PATTERN = re.compile(r"^voice-job-[0-9a-f]{12}$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MODEL_ARTIFACT_CONTENT_TYPES = {
    "model.onnx": "application/octet-stream",
    "model.onnx.json": "application/json; charset=utf-8",
    "test.wav": "audio/wav",
    "manifest.json": "application/json; charset=utf-8",
    "status.json": "application/json; charset=utf-8",
    "training.log": "text/plain; charset=utf-8",
}
REQUIRED_MODEL_ARTIFACTS = frozenset({"model.onnx", "model.onnx.json"})
MODEL_ROLLBACK_RETENTION = timedelta(days=7)
MODEL_RETENTION_KEY_PATTERN = re.compile(
    r"^patients/(?P<patient_id>[A-Za-z0-9_-]{1,64})/voice-models/"
    r"releases/(?P<model_id>voice-model-[0-9a-f]{12})/retention\.json$"
)


class InvalidVoiceModelRequest(ValueError):
    pass


class VoiceModelStateError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("Voice model timestamps must be timezone-aware")
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


def _validate_identifier(value: str, pattern: re.Pattern[str], label: str) -> None:
    if not pattern.fullmatch(value):
        raise InvalidVoiceModelRequest(f"Invalid {label}")


class VoiceModelService:
    def __init__(self, storage: Any) -> None:
        self.storage = storage

    @staticmethod
    def _release_prefix(patient_id: str, model_id: str) -> str:
        return f"patients/{patient_id}/voice-models/releases/{model_id}"

    @staticmethod
    def _latest_key(patient_id: str) -> str:
        return f"patients/{patient_id}/voice-models/latest.json"

    @staticmethod
    def _model_id(artifacts: dict[str, dict[str, Any]]) -> str:
        fingerprint = "\n".join(
            f"{name}:{artifacts[name]['sha256']}"
            for name in sorted(artifacts)
        )
        digest = hashlib.sha256(fingerprint.encode("ascii")).hexdigest()
        return f"voice-model-{digest[:12]}"

    def create_upload_plan(
        self,
        *,
        patient_id: str,
        version: str,
        artifacts: dict[str, dict[str, Any]],
        source_job_id: str | None = None,
        expires_seconds: int = 3600,
    ) -> dict[str, Any]:
        _validate_identifier(patient_id, PATIENT_ID_PATTERN, "patient id")
        _validate_identifier(version, VERSION_PATTERN, "model version")
        if source_job_id is not None:
            _validate_identifier(
                source_job_id, JOB_ID_PATTERN, "source voice training job id"
            )
        artifact_names = set(artifacts)
        missing = REQUIRED_MODEL_ARTIFACTS - artifact_names
        unknown = artifact_names - set(MODEL_ARTIFACT_CONTENT_TYPES)
        if missing:
            raise InvalidVoiceModelRequest(
                "Missing required artifacts: " + ", ".join(sorted(missing))
            )
        if unknown:
            raise InvalidVoiceModelRequest(
                "Unknown model artifacts: " + ", ".join(sorted(unknown))
            )

        normalized: dict[str, dict[str, Any]] = {}
        for name in sorted(artifacts):
            content_type = MODEL_ARTIFACT_CONTENT_TYPES[name]
            descriptor = artifacts[name]
            size_bytes = descriptor.get("size_bytes")
            sha256 = descriptor.get("sha256")
            content_md5 = descriptor.get("content_md5")
            if not isinstance(size_bytes, int) or size_bytes <= 0:
                raise InvalidVoiceModelRequest(f"Invalid size for {name}")
            if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
                raise InvalidVoiceModelRequest(f"Invalid SHA-256 for {name}")
            try:
                md5_bytes = base64.b64decode(content_md5, validate=True)
            except (TypeError, ValueError):
                md5_bytes = b""
            if len(md5_bytes) != 16:
                raise InvalidVoiceModelRequest(f"Invalid Content-MD5 for {name}")
            normalized[name] = {
                "size_bytes": size_bytes,
                "sha256": sha256,
                "content_md5": content_md5,
                "md5_hex": md5_bytes.hex(),
                "content_type": content_type,
            }

        model_id = self._model_id(normalized)
        release_prefix = self._release_prefix(patient_id, model_id)
        stored_artifacts: dict[str, dict[str, Any]] = {}
        upload_artifacts: dict[str, dict[str, Any]] = {}
        for name, descriptor in normalized.items():
            object_key = f"{release_prefix}/artifacts/{name}"
            stored_artifacts[name] = {**descriptor, "object_key": object_key}
            upload_artifacts[name] = {
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
            "model_id": model_id,
            "version": version,
            "created_at": _utc_now(),
            "artifacts": stored_artifacts,
        }
        if source_job_id is not None:
            plan["source_job_id"] = source_job_id
        plan_key = f"{release_prefix}/upload-plan.json"
        existing = self.storage.get_json(plan_key)
        if existing is None:
            self.storage.put_json(plan_key, plan)
        elif (
            existing.get("patient_id") != patient_id
            or existing.get("version") != version
            or existing.get("source_job_id") != source_job_id
            or existing.get("artifacts") != stored_artifacts
        ):
            raise VoiceModelStateError(
                "This model content already has a different upload plan"
            )

        return {
            "patient_id": patient_id,
            "model_id": model_id,
            "version": version,
            "expires_seconds": expires_seconds,
            "artifacts": upload_artifacts,
        }

    def publish(self, *, patient_id: str, model_id: str) -> dict[str, Any]:
        _validate_identifier(patient_id, PATIENT_ID_PATTERN, "patient id")
        _validate_identifier(model_id, MODEL_ID_PATTERN, "model id")
        release_prefix = self._release_prefix(patient_id, model_id)
        plan = self.storage.get_json(f"{release_prefix}/upload-plan.json")
        if plan is None:
            raise VoiceModelStateError("Voice model upload plan is missing")
        if plan.get("patient_id") != patient_id or plan.get("model_id") != model_id:
            raise VoiceModelStateError("Voice model upload plan does not match")

        artifacts = plan.get("artifacts")
        if not isinstance(artifacts, dict):
            raise VoiceModelStateError("Voice model upload plan is invalid")
        for name in artifacts:
            descriptor = artifacts.get(name)
            if not isinstance(descriptor, dict):
                raise VoiceModelStateError(f"Missing model artifact: {name}")
            object_info = self.storage.head_object(descriptor["object_key"])
            if object_info is None:
                raise VoiceModelStateError(f"Model artifact was not uploaded: {name}")
            if int(object_info["size_bytes"]) != int(descriptor["size_bytes"]):
                raise VoiceModelStateError(f"Model artifact size mismatch: {name}")
            if object_info.get("metadata", {}).get("sha256") != descriptor["sha256"]:
                raise VoiceModelStateError(f"Model artifact SHA-256 mismatch: {name}")
            if str(object_info.get("etag", "")).strip('"') != descriptor["md5_hex"]:
                raise VoiceModelStateError(f"Model artifact MD5 mismatch: {name}")

        manifest = {
            "schema_version": 1,
            "patient_id": patient_id,
            "model_id": model_id,
            "version": plan["version"],
            "created_at": plan["created_at"],
            "published_at": _utc_now(),
            "artifacts": artifacts,
        }
        if plan.get("source_job_id") is not None:
            manifest["source_job_id"] = plan["source_job_id"]
        self.storage.put_json(f"{release_prefix}/manifest.json", manifest)
        self.storage.put_json(self._latest_key(patient_id), manifest)
        return manifest

    def get_latest(self, *, patient_id: str) -> dict[str, Any] | None:
        _validate_identifier(patient_id, PATIENT_ID_PATTERN, "patient id")
        return self.storage.get_json(self._latest_key(patient_id))

    def create_device_release(
        self,
        *,
        patient_id: str,
        device_id: str,
        expires_seconds: int = 900,
    ) -> dict[str, Any] | None:
        _validate_identifier(device_id, DEVICE_ID_PATTERN, "device id")
        manifest = self.get_latest(patient_id=patient_id)
        if manifest is None:
            return None
        artifacts = manifest.get("artifacts", {})
        onnx = artifacts.get("model.onnx", {})
        config = artifacts.get("model.onnx.json", {})
        if not onnx or not config:
            raise VoiceModelStateError("Published voice model manifest is incomplete")
        return {
            "model_id": manifest["model_id"],
            "version": manifest["version"],
            "onnx_download_url": self.storage.create_download_url(
                onnx["object_key"], expires_seconds=expires_seconds
            ),
            "config_download_url": self.storage.create_download_url(
                config["object_key"], expires_seconds=expires_seconds
            ),
            "onnx_sha256": onnx["sha256"],
            "config_sha256": config["sha256"],
            "created_at": manifest["created_at"],
            "published_at": manifest["published_at"],
        }

    def record_installation(
        self,
        *,
        patient_id: str,
        device_id: str,
        model_id: str,
        status: str,
        detail: str | None,
        previous_model_id: str | None,
    ) -> dict[str, Any]:
        _validate_identifier(patient_id, PATIENT_ID_PATTERN, "patient id")
        _validate_identifier(device_id, DEVICE_ID_PATTERN, "device id")
        _validate_identifier(model_id, MODEL_ID_PATTERN, "model id")
        if previous_model_id is not None:
            _validate_identifier(previous_model_id, MODEL_ID_PATTERN, "previous model id")
        latest = self.get_latest(patient_id=patient_id)
        if latest is None or latest.get("model_id") != model_id:
            raise VoiceModelStateError("Voice model is not the latest release")
        payload = {
            "schema_version": 1,
            "patient_id": patient_id,
            "device_id": device_id,
            "model_id": model_id,
            "version": latest["version"],
            "status": status,
            "detail": detail,
            "previous_model_id": previous_model_id,
            "reported_at": _utc_now(),
        }
        source_job_id = latest.get("source_job_id")
        if source_job_id is None and JOB_ID_PATTERN.fullmatch(
            str(latest.get("version", ""))
        ):


            source_job_id = latest["version"]
        if source_job_id is not None:
            payload["source_job_id"] = source_job_id
        key = f"devices/{device_id}/voice-model-installs/{model_id}.json"
        self.storage.put_json(key, payload)
        return payload

    def schedule_previous_model_deletion(
        self,
        *,
        patient_id: str,
        model_id: str,
        replaced_at: datetime | None = None,
    ) -> dict[str, Any]:
        _validate_identifier(patient_id, PATIENT_ID_PATTERN, "patient id")
        _validate_identifier(model_id, MODEL_ID_PATTERN, "model id")
        latest = self.get_latest(patient_id=patient_id)
        if latest is not None and latest.get("model_id") == model_id:
            raise VoiceModelStateError("The active voice model cannot be scheduled for deletion")
        release_prefix = self._release_prefix(patient_id, model_id)
        if self.storage.get_json(f"{release_prefix}/manifest.json") is None:
            return {
                "schema_version": 1,
                "patient_id": patient_id,
                "model_id": model_id,
                "status": "already_absent",
                "reason": "superseded_model_not_in_storage",
            }
        scheduled_at = _as_utc(replaced_at)
        retention_key = f"{release_prefix}/retention.json"
        existing = self.storage.get_json(retention_key)
        if isinstance(existing, dict):
            return existing
        retention = {
            "schema_version": 1,
            "patient_id": patient_id,
            "model_id": model_id,
            "status": "scheduled",
            "scheduled_at": scheduled_at.isoformat(),
            "delete_after": (
                scheduled_at + MODEL_ROLLBACK_RETENTION
            ).isoformat(),
            "reason": "superseded_model_rollback_window",
        }
        self.storage.put_json(retention_key, retention)
        return retention

    def cleanup_expired_models(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        checked_at = _as_utc(now)
        result = {
            "retentions_checked": 0,
            "models_deleted": 0,
            "objects_deleted": 0,
        }
        retention_keys = sorted(
            key for key in self.storage.list_keys("patients/")
            if MODEL_RETENTION_KEY_PATTERN.fullmatch(key)
        )
        for retention_key in retention_keys:
            result["retentions_checked"] += 1
            match = MODEL_RETENTION_KEY_PATTERN.fullmatch(retention_key)
            assert match is not None
            patient_id = match.group("patient_id")
            model_id = match.group("model_id")
            retention = self.storage.get_json(retention_key)
            if not isinstance(retention, dict):
                continue
            delete_after = _parse_timestamp(retention.get("delete_after"))
            if delete_after is None or delete_after > checked_at:
                continue
            latest = self.get_latest(patient_id=patient_id)
            if latest is not None and latest.get("model_id") == model_id:
                continue
            release_prefix = self._release_prefix(patient_id, model_id) + "/"
            release_keys = self.storage.list_keys(release_prefix)
            for key in release_keys:
                self.storage.delete_object(key)
            result["models_deleted"] += 1
            result["objects_deleted"] += len(release_keys)
        return result
