

import json
import os
import re
import uuid
from pathlib import Path
from threading import Lock

from app.r2_storage import R2Storage


PROFILE_DIR = Path(os.getenv(
    "PAUSEABLE_CARE_PROFILE_DIR",
    str(Path(__file__).resolve().parent / "data" / "care_profiles"),
))
_lock = Lock()
_empty_profile = {
    "name": "", "patient_name": "", "relationship": "", "phone_number": "",
    "patient_call_name": "",
}


def _key(patient_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patient_id):
        raise ValueError("Invalid patient ID")
    return f"patients/{patient_id}/care-profile.json"


def load_profile(patient_id: str, storage_backend: str) -> dict[str, str]:
    key = _key(patient_id)
    if storage_backend == "r2":
        saved = R2Storage.from_environment().get_json(key)
    else:
        path = PROFILE_DIR / f"{patient_id}.json"
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return {**_empty_profile, **(saved or {})}


def save_profile(
    patient_id: str, profile: dict[str, str], storage_backend: str,
) -> dict[str, str]:
    key = _key(patient_id)


    with _lock:
        previous = load_profile(patient_id, storage_backend)
        saved = {
            field: profile.get(field, previous[field]).strip()
            for field in _empty_profile
        }
        if storage_backend == "r2":
            R2Storage.from_environment().put_json(key, saved)
        else:
            path = PROFILE_DIR / f"{patient_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
    return saved
