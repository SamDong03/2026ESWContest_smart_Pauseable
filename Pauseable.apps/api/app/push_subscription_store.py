

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.r2_storage import R2Storage


class PushSubscriptionStore:
    def __init__(self, *, local_dir: Path, r2_storage: R2Storage | None = None) -> None:
        self.local_dir = local_dir
        self.r2_storage = r2_storage

    @staticmethod
    def _digest(endpoint: str) -> str:
        return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()

    def _key(self, patient_id: str, endpoint: str) -> str:
        return f"patients/{patient_id}/push-subscriptions/{self._digest(endpoint)}.json"

    def _path(self, patient_id: str, endpoint: str) -> Path:
        return self.local_dir / patient_id / f"{self._digest(endpoint)}.json"

    def save(self, patient_id: str, subscription: dict[str, Any]) -> None:
        payload = {
            "patient_id": patient_id,
            "endpoint": subscription["endpoint"],
            "keys": dict(subscription["keys"]),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        endpoint = str(subscription["endpoint"])
        if self.r2_storage is not None:
            self.r2_storage.put_json(self._key(patient_id, endpoint), payload)
            return
        path = self._path(patient_id, endpoint)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def list_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        if self.r2_storage is not None:
            return [
                payload
                for key in self.r2_storage.list_keys(
                    f"patients/{patient_id}/push-subscriptions/"
                )
                for payload in [self.r2_storage.get_json(key)]
                if payload is not None
            ]
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.local_dir / patient_id).glob("*.json")
        ]

    def get(self, patient_id: str, endpoint: str) -> dict[str, Any] | None:
        if self.r2_storage is not None:
            payload = self.r2_storage.get_json(self._key(patient_id, endpoint))
        else:
            path = self._path(patient_id, endpoint)
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        if payload is None or payload.get("patient_id") != patient_id or payload.get("endpoint") != endpoint:
            return None
        return payload

    def delete(self, patient_id: str, endpoint: str) -> None:
        if self.r2_storage is not None:
            self.r2_storage.delete_object(self._key(patient_id, endpoint))
        else:
            self._path(patient_id, endpoint).unlink(missing_ok=True)
