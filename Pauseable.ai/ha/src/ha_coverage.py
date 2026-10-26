
import pandas as pd
from make_ha_features import parse_time


def complete_windows(times, intervals, lookback_minutes=120):
    spans = sorted((pd.Timestamp(parse_time(a)), pd.Timestamp(parse_time(b))) for a, b in intervals)
    merged = []
    for a, b in spans:
        if b < a:
            raise ValueError('Invalid coverage interval')
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])

    return [int(any(a <= pd.Timestamp(parse_time(t)) - pd.Timedelta(minutes=lookback_minutes)
                    and b >= pd.Timestamp(parse_time(t)) for a, b in merged)) for t in times]


def usable_windows(times, raw, intervals, required_entities=()):
    complete = complete_windows(times, intervals)
    if raw.empty or 'state' not in raw or 'entity_id' not in raw:
        return [0] * len(times)
    raw = raw.copy()
    raw['_observed'] = raw['recorded_at'].map(lambda value: pd.Timestamp(parse_time(value)))
    raw = raw.sort_values('_observed', kind='stable')
    unavailable = raw['state'].fillna('unknown').astype(str).str.strip().str.lower().isin(['unavailable', 'unknown', 'none', ''])

    bad_times = [pd.Timestamp(parse_time(t)) for t in raw.loc[unavailable, 'recorded_at']]
    observed = raw['_observed']
    for i, t in enumerate(times):
        end = pd.Timestamp(parse_time(t))
        if any(end - pd.Timedelta(hours=2) <= b <= end for b in bad_times):
            complete[i] = 0
        seen = raw.loc[observed <= end]
        latest = seen.groupby('entity_id', sort=False).tail(1)
        if latest.empty or latest['state'].fillna('unknown').astype(str).str.strip().str.lower().isin(['unavailable', 'unknown', 'none', '']).any():
            complete[i] = 0
        known_at_start = raw.loc[observed <= end - pd.Timedelta(hours=2), 'entity_id']
        if not set(required_entities).issubset(set(known_at_start)):
            complete[i] = 0
    return complete


def observation_report(raw, required_entities=()):
    pass
    if raw.empty:
        latest = raw
    else:
        latest = raw.assign(_observed=pd.to_datetime(raw['recorded_at'], utc=True, errors='raise')).sort_values(
            '_observed', kind='stable').groupby('entity_id', sort=False).tail(1)
    seen = set(latest['entity_id']) if 'entity_id' in latest else set()
    unavailable = [] if latest.empty else latest.loc[
        latest['state'].fillna('unknown').astype(str).str.strip().str.lower().isin(['unknown', 'unavailable', '', 'none']),
        'entity_id'].tolist()
    return {'selected_entity_count': len(seen), 'required_entities': sorted(set(required_entities)),
            'missing_required_entities': sorted(set(required_entities) - seen),
            'unavailable_entities': sorted(unavailable), 'physical_event_delivery_verified': False,
            'coverage_meaning': 'HA connection and selected state availability, not appliance/cloud completeness'}
