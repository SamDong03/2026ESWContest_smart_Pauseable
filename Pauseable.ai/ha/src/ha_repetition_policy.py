

import math

import pandas as pd


PATTERNS = {
    'fridge_repeated_check': ('fridge_', ['fridge_door_open_count_10m', 'fridge_door_open_count_30m', 'fridge_door_open_count_1h']),
    'door_lock_repeated_unlock': ('door_lock_', ['door_lock_unlock_count_10m', 'door_lock_unlock_count_30m', 'door_lock_unlock_count_1h']),
    'microwave_repeated_use': ('microwave_', ['microwave_start_count_10m', 'microwave_start_count_30m', 'microwave_start_count_1h']),
    **{f'{device}_repeated_operation': (device + '_', [f'{device}_start_count_2h'])
       for device in ('washer', 'dryer', 'dishwasher')},
    'air_purifier_repeated_control': ('air_purifier_', ['air_purifier_mode_change_count_30m', 'air_purifier_mode_change_count_1h',
        'air_purifier_speed_change_count_30m', 'air_purifier_speed_change_count_1h']),
    'air_conditioner_repeated_control': ('air_conditioner_', ['air_conditioner_mode_change_count_30m', 'air_conditioner_mode_change_count_1h',
        'air_conditioner_temperature_change_count_30m', 'air_conditioner_temperature_change_count_1h']),
}


def count(row, name):
    try:
        value = float(row.get(name, 0))
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            return 0
        return int(value)
    except (ValueError, TypeError):
        return 0


def family(pattern):
    for device in ('washer', 'dryer', 'dishwasher'):
        if pattern in {f'{device}_restart_after_done', f'{device}_power_repetition'}:
            return f'{device}_repeated_operation'
    return pattern


def observed_patterns(row):
    observed = []
    for pattern, (prefix, starts) in PATTERNS.items():
        repeated = max((count(row, name) for name in starts), default=0) >= 2
        device = prefix.rstrip('_')
        if device in ('washer', 'dryer', 'dishwasher'):
            repeated |= count(row, f'{device}_done_to_restart_count_2h') >= 1
        if device in ('air_purifier', 'air_conditioner'):

            repeated |= count(row, f'{device}_power_toggle_count_30m') >= 3
        if repeated:
            observed.append(pattern)
    return observed


def protected_rule(row):
    patterns = observed_patterns(row)
    if any(name in patterns for name in ('door_lock_repeated_unlock', 'microwave_repeated_use')):
        return 'protected_lock_or_heating_pattern'
    for device in ('washer', 'dryer', 'dishwasher'):
        if count(row, f'{device}_done_to_restart_count_2h') >= 2:
            return 'multiple_completed_cycle_restarts'

    for name in ('fridge_door_open_count_10m', 'air_purifier_mode_change_count_30m',
                 'air_purifier_speed_change_count_30m', 'air_conditioner_mode_change_count_30m',
                 'air_conditioner_temperature_change_count_30m'):
        if count(row, name) >= 12:
            return 'high_density_control_guard'
    return ''


def evidence_frame(features):
    rows = []
    for row in features.to_dict('records'):
        patterns = observed_patterns(row)
        rows.append({'window_end': row['window_end'], 'repetition_observed': bool(patterns),
                     'repetition_patterns': '|'.join(patterns),
                     'repetition_pattern': patterns[0] if patterns else '',
                     'protected_rule': protected_rule(row)})
    return pd.DataFrame(rows, columns=['window_end', 'repetition_observed', 'repetition_patterns',
                                       'repetition_pattern', 'protected_rule'])
