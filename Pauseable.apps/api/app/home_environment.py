

import json
import os
import uuid
from functools import lru_cache
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from app.r2_storage import R2Storage

CATALOG_PATH = Path(__file__).resolve().parent / 'data/kma_regions.json'
HOME_SETTINGS_DIR = Path(os.getenv(
    'PAUSEABLE_HOME_SETTINGS_DIR',
    str(Path(__file__).resolve().parent / 'data/home_settings'),
))
_settings_lock = Lock()


@lru_cache(maxsize=1)
def region_catalog() -> dict[str, dict]:
    data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    return {region['code']: region for region in data['regions']}


def _settings_path(patient_id: str) -> Path:

    if not patient_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in patient_id):
        raise HTTPException(404, 'Patient not found')
    return HOME_SETTINGS_DIR / f'{patient_id}.json'


def lighting_context(region: dict | None, enabled: bool) -> dict:
    pass


    return {
        'status': 'region_required' if region is None else 'awaiting_integration' if enabled else 'disabled',
        'indoor_lux': None,
        'brightness_percent': None,
        'weather_connected': False,
        'sensor_connected': False,
        'light_connected': False,
    }


def _serialize(
    patient_id: str, region: dict | None, enabled: bool, storage_backend: str,
) -> dict:
    return {
        'patient_id': patient_id,
        'region': region,
        'auto_lighting_enabled': enabled,
        'lighting': lighting_context(region, enabled),
        'storage_backend': storage_backend,
        'is_persistent': storage_backend == 'r2',
    }


def load_home_environment(patient_id: str, storage_backend: str = 'local') -> dict:
    path = _settings_path(patient_id)
    if storage_backend == 'r2':
        storage = R2Storage.from_environment()
        key = f'patients/{patient_id}/home-environment.json'
        saved = storage.get_json(key)
        if saved is None and path.is_file():


            legacy = json.loads(path.read_text(encoding='utf-8'))
            storage.put_json_if_absent(key, legacy)
            saved = storage.get_json(key)
    else:
        saved = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
    if saved is None:
        return _serialize(patient_id, None, False, storage_backend)
    region = region_catalog().get(saved['region_code'])

    return _serialize(
        patient_id, region,
        bool(saved.get('auto_lighting_enabled', False)) if region else False,
        storage_backend,
    )


def save_home_environment(
    patient_id: str, region_code: str, enabled: bool, storage_backend: str = 'local',
) -> dict:
    region = region_catalog().get(region_code)
    if region is None:
        raise HTTPException(422, 'Unknown region code')
    path = _settings_path(patient_id)
    saved = {'region_code': region_code, 'auto_lighting_enabled': enabled}
    if storage_backend == 'r2':
        R2Storage.from_environment().put_json(
            f'patients/{patient_id}/home-environment.json', saved,
        )
        return _serialize(patient_id, region, enabled, storage_backend)
    with _settings_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
        try:
            temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return _serialize(patient_id, region, enabled, storage_backend)
