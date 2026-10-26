

import json
from pathlib import Path

import pandas as pd

from make_ha_features import parse_time, prepare_events


def update_history(current, history_path, window_start, window_end, source_type):
    path = Path(history_path)
    meta_path = path.with_suffix('.json')
    start, end = parse_time(window_start), parse_time(window_end)
    if end < start:
        raise ValueError('Collection end precedes start')
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    if meta and meta.get('source_type') != source_type:
        raise ValueError('Do not mix public, synthetic and local observation histories')
    continuous = bool(meta) and 0 <= (start - parse_time(meta['last_end'])).total_seconds() <= 60
    old = pd.read_csv(path) if path.exists() and continuous else pd.DataFrame()
    since = parse_time(meta['observed_since']) if continuous else start
    combined = pd.concat([old, current], ignore_index=True)
    if not combined.empty:
        combined = prepare_events(combined)
        keys = ['time', 'entity_id', 'device_type', 'signal_type', 'action', 'record_type']
        combined = combined.drop_duplicates(keys).sort_values('time', kind='stable')
        cutoff = end - pd.Timedelta(minutes=130)

        carry = combined.loc[combined['time'] < cutoff].groupby('_stream', sort=False).tail(1).copy()
        carry['record_type'] = 'state_snapshot'
        carry['recorded_at'] = cutoff.isoformat()
        combined = pd.concat([carry, combined.loc[combined['time'] >= cutoff]], ignore_index=True)
        combined = combined.drop(columns=[c for c in combined if c.startswith('_') or c == 'time'])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp.csv')
    combined.to_csv(temp, index=False)
    temp.replace(path)
    meta = {'source_type': source_type, 'observed_since': since.isoformat(), 'last_end': end.isoformat(),
            'continuity_tolerance_seconds': 60, 'note': 'Collection-session continuity; not proof that every cloud device reported reliably'}
    temp = meta_path.with_suffix('.tmp.json')
    temp.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    temp.replace(meta_path)
    return combined, since
