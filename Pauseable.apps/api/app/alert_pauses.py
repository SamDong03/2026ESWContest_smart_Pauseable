from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from app.r2_storage import R2Storage


class RepetitiveAlertPauseStore:
    """Patient-scoped notification pause; never stops detection or photo storage."""

    def __init__(self, *, local_dir: Path, r2_storage: R2Storage | None = None):
        self.local_dir = local_dir
        self.r2_storage = r2_storage
        self._lock = RLock()

    @staticmethod
    def _key(patient_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patient_id):
            raise ValueError("Invalid patient ID")
        return f"patients/{patient_id}/repetitive-alert-pause.json"

    def load(self, patient_id: str, *, now: datetime | None = None) -> dict:
        with self._lock:
            key = self._key(patient_id)
            if self.r2_storage is not None:
                saved = self.r2_storage.get_json(key)
            else:
                path = self.local_dir / f"{patient_id}.json"
                saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            until = None
            if saved is not None:
                if not isinstance(saved, dict) or saved.get("scope") != "repetitive_behavior":
                    raise ValueError("Invalid alert pause")
                if saved.get("paused_until") is not None:
                    until = datetime.fromisoformat(saved["paused_until"])
                    if until.tzinfo is None or until.utcoffset() != timedelta(0):
                        raise ValueError("Pause expiry must be UTC")
            active = until is not None and until > (now or datetime.now(timezone.utc))
            return {
                "patient_id": patient_id,
                "scope": "repetitive_behavior",
                "available": True,
                "is_paused": active,
                "paused_until": until.isoformat() if active else None,
            }

    def save(self, patient_id: str, *, duration_minutes: int | None, now: datetime | None = None) -> dict:
        if duration_minutes is not None and (type(duration_minutes) is not int or not 1 <= duration_minutes <= 1440):
            raise ValueError("Pause duration must be between 1 and 1440 minutes")
        current = now or datetime.now(timezone.utc)
        until = current + timedelta(minutes=duration_minutes) if duration_minutes is not None else None
        saved = {
            "scope": "repetitive_behavior",
            "paused_until": until.isoformat() if until else None,
        }
        with self._lock:
            key = self._key(patient_id)
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
            return self.load(patient_id, now=current)
