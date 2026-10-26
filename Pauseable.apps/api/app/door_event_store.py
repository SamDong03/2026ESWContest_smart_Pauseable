from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

from app.r2_storage import R2Storage


EVENT_PREFIX = "door-events/events/"
IMAGE_PREFIX = "door-events/images/"
R2_READ_WORKERS = 4
METADATA_CACHE_SIZE = 512
logger = logging.getLogger("uvicorn.error")


class DoorEventConflict(RuntimeError):
    pass


class DoorEventStore:
    def __init__(
        self,
        *,
        local_dir: Path,
        r2_storage: R2Storage | None = None,
    ) -> None:
        self.local_dir = local_dir
        self.r2_storage = r2_storage


        self._metadata_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._metadata_lock = RLock()

    def list_events(self) -> list[dict[str, Any]]:
        if self.r2_storage is not None:
            events = self._list_r2_events()
        else:
            if not self.local_dir.is_dir():
                return []
            events = []
            for path in self.local_dir.glob("*/event.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    events.append(payload)

        return sorted(
            events,
            key=lambda event: str(event.get("occurred_at", "")),
            reverse=True,
        )

    def _list_r2_events(self) -> list[dict[str, Any]]:
        assert self.r2_storage is not None
        started = monotonic()


        with self._metadata_lock:
            keys = [
                key for key in self.r2_storage.list_keys(EVENT_PREFIX)
                if key.endswith(".json")
            ]
            current_keys = set(keys)
            for key in list(self._metadata_cache):
                if key not in current_keys:
                    del self._metadata_cache[key]

            events_by_key = {
                key: self._metadata_cache[key]
                for key in keys if key in self._metadata_cache
            }
            missing = [key for key in keys if key not in events_by_key]
            if missing:
                with ThreadPoolExecutor(max_workers=R2_READ_WORKERS) as executor:
                    fetched = executor.map(self.r2_storage.get_json, missing)
                    for key, event in zip(missing, fetched):
                        if event is not None:
                            events_by_key[key] = event
                            self._remember_event(key, event)


            events = [deepcopy(events_by_key[key]) for key in keys if key in events_by_key]
        logger.info(
            "DOOR_EVENT_R2_LIST keys=%d cache_hits=%d fetched=%d elapsed_ms=%.1f",
            len(keys), len(keys) - len(missing), len(missing),
            (monotonic() - started) * 1000,
        )
        return events

    def _remember_event(self, key: str, event: dict[str, Any]) -> None:
        with self._metadata_lock:
            self._metadata_cache[key] = deepcopy(event)
            self._metadata_cache.move_to_end(key)
            while len(self._metadata_cache) > METADATA_CACHE_SIZE:
                self._metadata_cache.popitem(last=False)

    def get_event(
        self, event_id: str, *, use_cache: bool = False,
    ) -> dict[str, Any] | None:
        if self.r2_storage is not None:
            key = self._event_key(event_id)
            if use_cache:
                with self._metadata_lock:
                    cached = self._metadata_cache.get(key)
                    if cached is not None:
                        self._metadata_cache.move_to_end(key)
                        return deepcopy(cached)

            event = self.r2_storage.get_json(key)
            if use_cache and event is not None:
                self._remember_event(key, event)
            return event

        path = self._local_event_dir(event_id) / "event.json"
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def create_event(
        self,
        event: dict[str, Any],
        image_bytes: bytes,
    ) -> tuple[dict[str, Any], bool]:
        event_id = str(event["id"])
        image_sha256 = hashlib.sha256(image_bytes).hexdigest()
        stored_event = {
            **event,
            "image_sha256": image_sha256,
            "image_content_type": "image/jpeg",
        }

        existing = self.get_event(event_id)
        if existing is not None:
            if self._same_event(existing, stored_event):
                if self.r2_storage is not None:
                    self._remember_event(self._event_key(event_id), existing)
                return existing, True
            raise DoorEventConflict(event_id)

        if self.r2_storage is not None:
            image_key = f"{IMAGE_PREFIX}{event_id}/{image_sha256}.jpg"
            stored_event["image_key"] = image_key
            stored_event["image_storage"] = "r2"
            self.r2_storage.put_bytes(
                image_key,
                image_bytes,
                content_type="image/jpeg",
            )
            created = self.r2_storage.put_json_if_absent(
                self._event_key(event_id),
                stored_event,
            )
            if created is None:
                existing = self.get_event(event_id)
                if existing is not None and self._same_event(existing, stored_event):
                    self._remember_event(self._event_key(event_id), existing)
                    return existing, True
                raise DoorEventConflict(event_id)
            self._remember_event(self._event_key(event_id), stored_event)
            return stored_event, False

        event_dir = self._local_event_dir(event_id)
        event_dir.mkdir(parents=True, exist_ok=False)
        stored_event["image_key"] = f"{event_id}/representative.jpg"
        stored_event["image_storage"] = "local"
        (event_dir / "representative.jpg").write_bytes(image_bytes)
        temporary_path = event_dir / "event.tmp"
        temporary_path.write_text(
            json.dumps(stored_event, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(event_dir / "event.json")
        return stored_event, False

    def get_image(self, event: dict[str, Any]) -> bytes | None:
        image_key = event.get("image_key")
        if not isinstance(image_key, str):
            return None

        if event.get("image_storage") == "r2":
            if self.r2_storage is None:
                return None
            return self.r2_storage.get_bytes(image_key)

        image_path = (self.local_dir / image_key).resolve()
        if self.local_dir.resolve() not in image_path.parents:
            return None
        if not image_path.is_file():
            return None
        return image_path.read_bytes()

    def _local_event_dir(self, event_id: str) -> Path:
        event_dir = (self.local_dir / event_id).resolve()
        if self.local_dir.resolve() not in event_dir.parents:
            raise ValueError("Invalid door event id")
        return event_dir

    @staticmethod
    def _event_key(event_id: str) -> str:
        return f"{EVENT_PREFIX}{event_id}.json"

    @staticmethod
    def _same_event(
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> bool:
        compared_fields = (
            "id",
            "device_id",
            "patient_id",
            "occurred_at",
            "decision",
            "motion_statistics",
            "image_sha256",
        )
        return all(left.get(field) == right.get(field) for field in compared_fields)
