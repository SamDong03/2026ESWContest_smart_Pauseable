

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from threading import RLock

from app.r2_storage import R2Storage


logger = logging.getLogger(__name__)
DEFAULT_PREFERENCES = {"safety_notifications": True, "sound_enabled": False}


class NotificationPreferenceStore:
    def __init__(self, *, local_dir: Path, r2_storage: R2Storage | None = None):
        self.local_dir = local_dir
        self.r2_storage = r2_storage
        self._last_known: dict[str, dict[str, bool]] = {}
        self._lock = RLock()

    @staticmethod
    def _key(patient_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patient_id):
            raise ValueError("Invalid patient ID")
        return f"patients/{patient_id}/notification-preferences.json"

    @staticmethod
    def _validate(saved) -> dict[str, bool]:
        if not isinstance(saved, dict):
            raise ValueError("Invalid notification preferences")
        result = {field: saved.get(field, default) for field, default in DEFAULT_PREFERENCES.items()}
        if any(type(value) is not bool for value in result.values()):
            raise ValueError("Notification preferences must be booleans")
        return result

    def _remember(self, patient_id: str, saved: dict[str, bool]):
        with self._lock:
            if len(self._last_known) >= 64 and patient_id not in self._last_known:
                self._last_known.pop(next(iter(self._last_known)))
            self._last_known[patient_id] = dict(saved)

    def load(self, patient_id: str) -> dict[str, bool]:


        with self._lock:
            return self._load(patient_id)

    def _load(self, patient_id: str) -> dict[str, bool]:
        key = self._key(patient_id)
        if self.r2_storage is not None:
            saved = self.r2_storage.get_json(key)
        else:
            path = self.local_dir / f"{patient_id}.json"
            saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        result = self._validate(DEFAULT_PREFERENCES if saved is None else saved)
        self._remember(patient_id, result)
        return result

    def save(self, patient_id: str, preferences: dict[str, bool]) -> dict[str, bool]:
        with self._lock:
            return self._save(patient_id, preferences)

    def _save(self, patient_id: str, preferences: dict[str, bool]) -> dict[str, bool]:
        key = self._key(patient_id)
        saved = self._validate(preferences)
        if self.r2_storage is not None:
            self.r2_storage.put_json(key, saved)
        else:
            path = self.local_dir / f"{patient_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(saved), encoding="utf-8")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

        self._remember(patient_id, saved)
        return dict(saved)

    def for_delivery(self, patient_id: str) -> dict[str, bool]:
        self._key(patient_id)
        try:
            return self.load(patient_id)
        except Exception:


            logger.warning("Notification settings unavailable; using last-known safety policy")
            with self._lock:
                return dict(self._last_known.get(patient_id, DEFAULT_PREFERENCES))
