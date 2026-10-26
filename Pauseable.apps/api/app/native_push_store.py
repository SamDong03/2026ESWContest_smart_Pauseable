

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.r2_storage import R2Storage


_PATIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TOKEN = re.compile(r"^[\x21-\x7e]{20,4096}$")


def validate_device_token(token: str) -> str:
    pass
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ValueError("Invalid FCM registration token")
    return token


class NativePushStore:
    def __init__(self, *, local_dir: Path, r2_storage: R2Storage | None = None) -> None:
        self.local_dir = local_dir
        self.r2_storage = r2_storage

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(validate_device_token(token).encode("utf-8")).hexdigest()

    @staticmethod
    def _patient(patient_id: str) -> str:
        if not _PATIENT_ID.fullmatch(patient_id):
            raise ValueError("Invalid patient id")
        return patient_id

    def _key(self, patient_id: str, token: str) -> str:
        return f"patients/{self._patient(patient_id)}/native-push/{self._digest(token)}.json"

    def _path(self, patient_id: str, token: str) -> Path:
        return self.local_dir / self._patient(patient_id) / f"{self._digest(token)}.json"

    @staticmethod
    def _valid_record(payload: Any, patient_id: str) -> bool:
        if (
            not isinstance(payload, dict)
            or payload.get("patient_id") != patient_id
            or payload.get("platform") != "android"
        ):
            return False
        try:
            validate_device_token(payload.get("token"))
        except ValueError:
            return False
        return True

    def get(self, patient_id: str, token: str) -> dict[str, Any] | None:
        if self.r2_storage is not None:
            payload = self.r2_storage.get_json(self._key(patient_id, token))
        else:
            path = self._path(patient_id, token)
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        if self._valid_record(payload, patient_id) and payload["token"] == token:
            return payload
        return None

    def save(self, patient_id: str, token: str) -> bool:
        pass
        created = self.get(patient_id, token) is None
        payload = {
            "patient_id": patient_id,
            "token": token,
            "platform": "android",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.r2_storage is not None:
            self.r2_storage.put_json(self._key(patient_id, token), payload)
            return created
        path = self._path(patient_id, token)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return created

    def list_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        self._patient(patient_id)
        if self.r2_storage is not None:
            records = [
                self.r2_storage.get_json(key)
                for key in self.r2_storage.list_keys(f"patients/{patient_id}/native-push/")
            ]
        else:
            records = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (self.local_dir / patient_id).glob("*.json")
            ]
        return [record for record in records if self._valid_record(record, patient_id)]

    def delete(self, patient_id: str, token: str) -> None:
        if self.r2_storage is not None:
            self.r2_storage.delete_object(self._key(patient_id, token))
        else:
            self._path(patient_id, token).unlink(missing_ok=True)
