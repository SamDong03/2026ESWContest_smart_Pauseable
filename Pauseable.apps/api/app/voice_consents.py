

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

from app.r2_storage import R2Storage

VOICE_CONSENT_POLICY_VERSION = "2026-10-24"
CONSENT_ID_PATTERN = r"^voice-consent-[0-9a-f]{32}$"


class VoiceConsentStore:
    def __init__(self, *, local_dir: Path, r2_storage: R2Storage | None = None):
        self.local_dir = local_dir
        self.r2_storage = r2_storage

    @staticmethod
    def _key(patient_id: str, consent_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patient_id):
            raise ValueError("Invalid patient ID")
        if not re.fullmatch(CONSENT_ID_PATTERN, consent_id):
            raise ValueError("Invalid consent ID")
        return f"patients/{patient_id}/voice-consents/{consent_id}.json"

    def load(self, patient_id: str, consent_id: str) -> dict | None:
        key = self._key(patient_id, consent_id)
        if self.r2_storage is not None:
            saved = self.r2_storage.get_json(key)
        else:
            path = self.local_dir / patient_id / f"{consent_id}.json"
            saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        if saved is None:
            return None
        if (
            not isinstance(saved, dict) or saved.get("patient_id") != patient_id
            or saved.get("consent_id") != consent_id or saved.get("accepted") is not True
            or saved.get("policy_version") != VOICE_CONSENT_POLICY_VERSION
            or saved.get("scope") != "guardian_voice_training"
        ):
            raise ValueError("Invalid stored consent receipt")
        timestamp = datetime.fromisoformat(saved["accepted_at"])
        if timestamp.tzinfo is None:
            raise ValueError("Consent timestamp requires a timezone")
        return saved

    def accept(self, patient_id: str, request_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise ValueError("Invalid consent request ID")
        consent_id = f"voice-consent-{request_id}"
        key = self._key(patient_id, consent_id)
        saved = {
            "schema_version": 1, "consent_id": consent_id,
            "patient_id": patient_id, "policy_version": VOICE_CONSENT_POLICY_VERSION,
            "scope": "guardian_voice_training", "accepted": True,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
            "actor_verification": "shared_app_credential_not_individual_identity",
        }
        if self.r2_storage is not None:

            self.r2_storage.put_json_if_absent(key, saved)
        else:
            path = self.local_dir / patient_id / f"{consent_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(saved), encoding="utf-8")
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        confirmed = self.load(patient_id, consent_id)
        if confirmed is None:
            raise OSError("Consent receipt could not be confirmed")
        return confirmed
