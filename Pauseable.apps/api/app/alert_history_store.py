

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.r2_storage import R2Storage


class AlertHistoryConflict(RuntimeError):
    pass


class AlertHistoryStore:
    def __init__(self, *, local_dir: Path, r2_storage: R2Storage | None = None) -> None:
        self.local_dir = local_dir
        self.r2_storage = r2_storage

    @staticmethod
    def _digest(alert_id: str) -> str:
        return hashlib.sha256(alert_id.encode("utf-8")).hexdigest()

    def _alert_key(self, patient_id: str, alert_id: str) -> str:
        return f"patients/{patient_id}/alerts/{self._digest(alert_id)}.json"

    def _read_key(self, patient_id: str, alert_id: str) -> str:
        return f"patients/{patient_id}/alert-reads/{self._digest(alert_id)}.json"

    def _alert_path(self, patient_id: str, alert_id: str) -> Path:
        return self.local_dir / patient_id / "alerts" / f"{self._digest(alert_id)}.json"

    def _read_path(self, patient_id: str, alert_id: str) -> Path:
        return self.local_dir / patient_id / "alert-reads" / f"{self._digest(alert_id)}.json"

    def get(self, patient_id: str, alert_id: str) -> dict[str, Any] | None:
        if self.r2_storage is not None:
            return self.r2_storage.get_json(self._alert_key(patient_id, alert_id))
        path = self._alert_path(patient_id, alert_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def create(self, alert: dict[str, Any]) -> bool:
        pass
        patient_id = str(alert["patient_id"])
        alert_id = str(alert["alert_id"])
        existing = self.get(patient_id, alert_id)
        if existing is not None:
            if self._same_alert(existing, alert):
                return False
            raise AlertHistoryConflict(alert_id)

        stored = {
            **alert,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.r2_storage is not None:
            created = self.r2_storage.put_json_if_absent(
                self._alert_key(patient_id, alert_id), stored,
            )
            if created is not None:
                return True
        else:
            path = self._alert_path(patient_id, alert_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as target:
                    json.dump(stored, target, ensure_ascii=False)
                return True
            except FileExistsError:
                pass

        existing = self.get(patient_id, alert_id)
        if existing is not None and self._same_alert(existing, alert):
            return False
        raise AlertHistoryConflict(alert_id)

    def list_recent(self, patient_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if self.r2_storage is not None:
            prefix = f"patients/{patient_id}/alerts/"
            alerts = [
                payload
                for key in self.r2_storage.list_keys(prefix)
                if key.endswith(".json")
                for payload in [self.r2_storage.get_json(key)]
                if payload is not None
            ]
            read_keys = set(
                self.r2_storage.list_keys(f"patients/{patient_id}/alert-reads/")
            )
            is_read = lambda alert_id: self._read_key(patient_id, alert_id) in read_keys
        else:
            root = self.local_dir / patient_id
            alerts = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (root / "alerts").glob("*.json")
            ]
            is_read = lambda alert_id: self._read_path(patient_id, alert_id).is_file()

        alerts.sort(
            key=lambda alert: (str(alert["received_at"]), str(alert["alert_id"])),
            reverse=True,
        )
        return [
            {**alert, "is_read": is_read(str(alert["alert_id"]))}
            for alert in alerts[:limit]
        ]

    def mark_read(self, patient_id: str, alert_id: str) -> bool:
        if self.get(patient_id, alert_id) is None:
            return False
        payload = {
            "alert_id": alert_id,
            "read_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.r2_storage is not None:
            self.r2_storage.put_json_if_absent(self._read_key(patient_id, alert_id), payload)
        else:
            path = self._read_path(patient_id, alert_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as target:
                    json.dump(payload, target, ensure_ascii=False)
            except FileExistsError:
                pass
        return True

    @staticmethod
    def _same_alert(stored: dict[str, Any], candidate: dict[str, Any]) -> bool:
        return all(stored.get(key) == value for key, value in candidate.items())
