
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from entity_mapper import convert_rows
from make_ha_features import parse_time


def audit_events(frame, entity_id, expected_opens=None, start=None, end=None):
    if expected_opens is not None and expected_opens < 0:
        raise ValueError('expected-opens must not be negative')
    required = {'entity_id', 'state', 'event_time', 'recorded_at', 'record_type'}
    if not required.issubset(frame):
        raise ValueError('Use the raw collector CSV, including timestamps and record_type')
    raw = frame.loc[frame['entity_id'].eq(entity_id)].copy()
    events, delays = [], []
    snapshots = unavailable = duplicates = 0
    seen = set()
    for row in raw.to_dict('records'):
        if row['record_type'] == 'state_snapshot':
            snapshots += 1
            continue
        if row['record_type'] != 'state_changed_event':
            continue
        time = pd.Timestamp(parse_time(row['event_time']))
        if start is not None and time < pd.Timestamp(parse_time(start)):
            continue
        if end is not None and time > pd.Timestamp(parse_time(end)):
            continue
        if str(row['state']).lower() in ('unknown', 'unavailable', 'none', ''):
            unavailable += 1
            events.append((time, 'unavailable'))
            continue
        for normalized in convert_rows(row):
            if normalized['signal_type'] != 'door' or normalized['action'] not in ('open', 'close'):
                continue
            key = (time, normalized['action'])
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            received = pd.Timestamp(parse_time(row['recorded_at']))
            delays.append((received - time).total_seconds())
            events.append(key)
    opened = closed = unmatched_close = repeated_open = interrupted_open = 0
    durations, pending = [], None
    for time, action in sorted(events, key=lambda item: item[0]):
        if action == 'unavailable':
            interrupted_open += int(pending is not None)
            pending = None
        elif action == 'open':
            opened += 1
            if pending is not None:
                repeated_open += 1
            pending = time
        else:
            closed += 1
            if pending is None:
                unmatched_close += 1
            else:
                durations.append((time - pending).total_seconds())
                pending = None
    negative_delays = sum(delay < 0 for delay in delays)
    return {'entity_id': entity_id, 'selected_raw_rows': len(raw), 'snapshots_not_counted': snapshots,
            'open_events': opened, 'close_events': closed, 'completed_pairs': len(durations),
            'open_duration_seconds': durations, 'pairs_at_most_2_seconds': sum(0 <= d <= 2 for d in durations),
            'duplicate_rows_ignored': duplicates, 'unavailable_events': unavailable,
            'unmatched_close_events': unmatched_close, 'repeated_open_without_close': repeated_open,
            'open_interrupted_by_unavailable': interrupted_open, 'unfinished_open': pending is not None,
            'negative_timestamp_delays': negative_delays,
            'ha_event_to_csv_delay_seconds': {'max': max(delays) if delays else None,
                'p95': float(pd.Series(delays).quantile(.95)) if delays else None},
            'expected_opens_user_supplied': expected_opens,
            'count_check': 'not_measured' if expected_opens is None else ('matched' if opened == expected_opens else 'mismatch'),
            'physical_event_delivery_verified': False,
            'limitations': ['Durations are between HA event timestamps, not independent measurements of the door.',
                'HA-to-CSV delay excludes appliance/cloud delay before HA emits the event.',
                'Expected counts need a separately observed physical trial and matching time boundaries.',
                'Equal counts alone do not prove absence of missing, delayed, or duplicated physical events.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--entity-id', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--expected-opens', type=int)
    parser.add_argument('--from-time')
    parser.add_argument('--to-time')
    args = parser.parse_args()
    if args.from_time and args.to_time and parse_time(args.from_time) > parse_time(args.to_time):
        parser.error('from-time must precede to-time')
    target = Path(args.output)
    if target.exists():
        parser.error('Use a new audit output; existing reports are not overwritten')
    source = Path(args.input)
    data = source.read_bytes()
    import io
    report = audit_events(pd.read_csv(io.BytesIO(data)), args.entity_id, args.expected_opens, args.from_time, args.to_time)
    report['input_sha256'] = hashlib.sha256(data).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
