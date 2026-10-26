
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'Pauseable.ai/ha/src'))
from entity_mapper import detect_device

DEVICES = ('fridge', 'door_lock', 'microwave', 'washer', 'dryer',
           'air_purifier', 'air_conditioner', 'dishwasher')
LEVELS = ('normal', 'attention', 'risk', 'unavailable')
KST = timezone(timedelta(hours=9))


def local_time(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (result.astimezone(KST).replace(tzinfo=None)
            if result.tzinfo else result)


def hourly_event_counts(rows, endpoints):
    pass
    times = [local_time(t) for t in endpoints]
    if not times or any(b - a != timedelta(hours=1) for a, b in zip(times, times[1:])):
        raise ValueError('Supply consecutive, increasing hourly endpoints')
    result = [[0] * len(times) for _ in DEVICES]
    first = times[0] - timedelta(hours=1)
    for row in rows:
        if row.get('record_type') != 'state_changed_event':
            continue
        when = local_time(row['event_time'])
        if not first < when <= times[-1]:
            continue
        device = detect_device(str(row['entity_id']))
        if device not in DEVICES:
            raise ValueError('Unknown appliance in the displayed interval')
        result[DEVICES.index(device)][bisect_left(times, when)] += 1
    return result


def standardized_matrix(rows, columns, mean, scale):
    if len(columns) != len(mean) or len(columns) != len(scale):
        raise ValueError('Scaler and feature dimensions disagree')
    if any(not math.isfinite(float(s)) or float(s) <= 0 for s in scale):
        raise ValueError('Scaler scale must be finite and positive')
    result = [[(float(row[c]) - float(mean[i])) / float(scale[i])
               for i, c in enumerate(columns)] for row in rows]
    if any(not math.isfinite(value) for row in result for value in row):
        raise ValueError('Non-finite feature value')
    return result


def scenario_counts(rows):
    totals = Counter()
    families = {}
    for row in rows:
        level = row['guarded_max_level']
        if level not in LEVELS:
            raise ValueError('Unknown scenario decision level')
        totals[level] += 1
        families.setdefault(row['family'], Counter())[level] += 1
    return {'total': sum(totals.values()),
            'levels': {level: totals[level] for level in LEVELS},
            'families': {family: {level: counts[level] for level in LEVELS}
                         for family, counts in sorted(families.items())}}
