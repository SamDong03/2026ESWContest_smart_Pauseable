
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


def load_baseline(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Baseline file is missing; detection cannot start')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('features'), dict) or not data['features']:
        raise ValueError('Baseline must contain nonempty feature statistics')
    for stats in data['features'].values():
        if not isinstance(stats, dict) or not stats:
            raise ValueError('Baseline feature statistics are missing')
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in stats.values()):
            raise ValueError('Baseline feature statistics must be finite numbers')
    return data


def selection_identity(household, baseline_path, entity_ids=(), excluded_ids=(), keywords=()):
    return {'household_id': household,
            'baseline_sha256': hashlib.sha256(Path(baseline_path).read_bytes()).hexdigest(),
            'required_entities': sorted(set(entity_ids)), 'excluded_entities': sorted(set(excluded_ids)),
            'entity_keywords': sorted(set(keywords)), 'contract_version': 1}


def validate_selection(entity_ids=(), excluded_ids=()):
    import re
    for entity in [*entity_ids, *excluded_ids]:
        if not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', entity):
            raise ValueError('Use exact Home Assistant entity IDs')
    if set(entity_ids) & set(excluded_ids):
        raise ValueError('Required and excluded entities overlap')


def check_runtime_identity(root, expected):
    from ha_model_lifecycle import atomic_json
    root = Path(root)
    path = root / 'runtime_identity.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != expected:
            raise ValueError('Baseline or entity selection changed; use a new state directory')
    elif any((root / name).exists() for name in ('cursor.json', 'models/history.sqlite3', 'decisions.sqlite3')):
        raise ValueError('Legacy state has no selection identity; retain it and use a new state directory')
    else:
        atomic_json(path, expected)


def validate_cycle(output_dir, prefix, run_id):
    pass
    output_dir = Path(output_dir)
    quality = json.loads((output_dir / f'{prefix}_data_quality.json').read_text(encoding='utf-8'))
    if quality.get('run_id') != run_id or quality.get('detection_completed') is not True:
        raise ValueError('Cycle result is stale or detection did not complete')
    result = pd.read_csv(output_dir / f'{prefix}_result.csv')
    required = {'window_end', 'level', 'risk_score', 'model_status', 'history_complete', 'run_id'}
    if not required.issubset(result) or len(result) != quality['feature_rows']:
        raise ValueError('Cycle result schema or row count mismatch')
    if not result['run_id'].eq(run_id).all() or result['window_end'].duplicated().any():
        raise ValueError('Cycle result has stale or duplicate rows')
    return quality, result


def age_seconds(value, now=None):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        return age if math.isfinite(age) and age >= 0 else None
    except (ValueError, TypeError):
        return None


def read_status(root, free_bytes, now=None):
    pass
    root = Path(root)
    issues, data = [], {}
    for name, relative in [('service', 'service_status.json'), ('coverage', 'live_events.coverage.json'),
                           ('learning', 'models/status.json'), ('identity', 'runtime_identity.json')]:
        try:
            data[name] = json.loads((root / relative).read_text(encoding='utf-8'))
        except FileNotFoundError:
            data[name] = {}
            if name in ('service', 'coverage', 'identity'):
                issues.append(name + '_missing')
        except (ValueError, OSError):
            data[name] = {}
            issues.append(name + '_unreadable')
    service, coverage = data['service'], data['coverage']
    service_age = age_seconds(service.get('utc'), now)
    heartbeat_age = age_seconds(coverage.get('confirmed_at'), now)
    if heartbeat_age is None or heartbeat_age > 40:
        issues.append('websocket_unconfirmed')
    if service_age is None or service_age > 120:
        issues.append('supervisor_status_stale')
    if service.get('status') not in ('ok', 'analyzing', 'waiting_for_ha'):
        issues.append('service_not_healthy')
    if service.get('collector_running') is False:
        issues.append('collector_stopped')
    if service.get('mqtt_delivery_exit_code') not in (None, 0):
        issues.append('mqtt_delivery_failed')
    if service.get('feedback_receiver_enabled') and not service.get('feedback_receiver_running'):
        issues.append('feedback_receiver_stopped')
    if service.get('data_quality') not in ('ok', None):
        issues.append('incomplete_observation')
    if free_bytes < 64 * 1024**2:
        issues.append('critical_disk')
    elif free_bytes < 512 * 1024**2:
        issues.append('low_disk')
    learning = data['learning'].get('status')
    if learning in ('rejected', 'training_failed', 'fallback', 'retry_deferred'):
        issues.append('model_' + learning)
    return {'checked_at': (now or datetime.now(timezone.utc)).isoformat(),
            'health': 'attention' if issues else 'ok', 'issues': sorted(set(issues)),
            'websocket_age_seconds': heartbeat_age, 'supervisor_age_seconds': service_age,
            'free_mib': round(free_bytes / 1024**2, 1), 'service': service, 'learning': data['learning'],
            'entity_selection': data['identity'], 'physical_event_delivery_verified': False,
            'note': 'WebSocket health cannot prove that the appliance/cloud delivered every physical action.'}
