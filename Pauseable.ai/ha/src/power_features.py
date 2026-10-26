
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


SCHEMA = 'appliance_power_windows_v1'
POWER_FEATURES = ['energy_wh_2h', 'mean_power_w_2h', 'above_threshold_minutes_2h',
                  'confirmed_starts_2h', 'completed_sessions_2h', 'mean_completed_duration_minutes_2h',
                  'night_confirmed_starts_2h', 'hour_sin', 'hour_cos', 'weekday_sin', 'weekday_cos']
SESSION_COLUMNS = ['start_time', 'start_detected_at', 'end_time', 'end_detected_at',
                   'duration_seconds', 'status']


@dataclass(frozen=True)
class PowerConfig:
    on_power_threshold: float
    min_on_seconds: float
    min_off_seconds: float
    max_power_w: float
    sample_seconds: float = 6
    max_gap_seconds: float = 30
    timezone: str = 'Europe/London'
    window_minutes: int = 120
    step_minutes: int = 10
    min_coverage: float = 0.95
    max_session_seconds: float = 21600

    def validate(self):
        numeric = [v for k, v in asdict(self).items() if k != 'timezone']
        if not all(np.isfinite(v) for v in numeric):
            raise ValueError('Configuration must be finite')
        if not 0 < self.on_power_threshold < self.max_power_w:
            raise ValueError('Require 0 < on threshold < maximum power')
        if min(self.min_on_seconds, self.min_off_seconds) < 0:
            raise ValueError('Debounce durations cannot be negative')
        if self.max_session_seconds <= max(self.min_on_seconds, self.min_off_seconds):
            raise ValueError('Maximum session must exceed debounce durations')
        if not 0 < self.sample_seconds <= self.max_gap_seconds:
            raise ValueError('Invalid sampling/gap limits')
        if self.window_minutes != 120 or self.step_minutes <= 0:
            raise ValueError('This schema uses a 120-minute window and positive step')
        if not 0 < self.min_coverage <= 1:
            raise ValueError('Coverage must be in (0, 1]')
        pd.Timestamp('2020-01-01', tz='UTC').tz_convert(self.timezone)


def normalize_power(frame, config):
    config.validate()
    if not {'timestamp', 'power_w'}.issubset(frame):
        raise ValueError('Require timestamp and power_w')
    data = frame[['timestamp', 'power_w']].copy()
    data['timestamp'] = pd.to_datetime(data['timestamp'], utc=True, errors='raise')
    if data['timestamp'].isna().any():
        raise ValueError('Missing timestamp')
    data['power_w'] = pd.to_numeric(data['power_w'], errors='coerce')
    bad = ~np.isfinite(data['power_w']) | ~data['power_w'].between(0, config.max_power_w)
    data.loc[bad, 'power_w'] = np.nan
    duplicates = int(data['timestamp'].duplicated().sum())
    if duplicates:

        conflicts = data.groupby('timestamp')['power_w'].nunique(dropna=False).gt(1)
        data.loc[data.timestamp.isin(conflicts.index[conflicts]), 'power_w'] = np.nan
        data = data.drop_duplicates('timestamp')
    data = data.sort_values('timestamp').reset_index(drop=True)
    if len(data) < 2:
        raise ValueError('Need at least two timestamped observations')
    seconds = np.array([item.timestamp() for item in data.timestamp], dtype=np.float64)
    gap = np.diff(seconds)
    if np.any(gap <= 0):
        raise ValueError('Timestamps must increase')
    return data, seconds, {'input_rows': len(frame), 'unique_rows': len(data),
                           'duplicate_rows': duplicates, 'invalid_power_rows': int(data.power_w.isna().sum()),
                           'long_gap_count': int((gap > config.max_gap_seconds).sum()),
                           'max_gap_seconds_observed': float(gap.max())}


def detect_sessions(seconds, power, config):
    pass
    rows = []
    start = detected = low_since = None
    seen_off = False

    def finish(end, confirmed, status):
        if detected is not None:
            rows.append([start, detected, end, confirmed,
                         end - start if status == 'complete' else np.nan, status])

    for i, (now, watts) in enumerate(zip(seconds, power)):
        interrupted = i > 0 and now - seconds[i - 1] > config.max_gap_seconds
        if interrupted or not np.isfinite(watts):
            finish(np.nan, np.nan, 'censored_gap')
            start = detected = low_since = None
            seen_off = False
        if not np.isfinite(watts):
            continue
        if start is not None and now - start >= config.max_session_seconds:
            finish(np.nan, np.nan, 'censored_max_duration')
            start = detected = low_since = None
            seen_off = False
        on = watts >= config.on_power_threshold
        if not on:
            if start is None:
                seen_off = True
                continue
            if low_since is None:
                low_since = now
            if now - low_since >= config.min_off_seconds:
                finish(low_since, now, 'complete')
                start = detected = low_since = None
                seen_off = True
                continue
        else:
            if start is None:

                if not seen_off:
                    continue
                start = now
            low_since = None
        if on and start is not None and detected is None and now - start >= config.min_on_seconds:
            detected = now
    finish(np.nan, np.nan, 'censored_end')
    return pd.DataFrame(rows, columns=SESSION_COLUMNS)


def integral_at(query, seconds, durations, rates):
    area = np.asarray(rates) * durations
    cumulative = np.r_[0.0, np.cumsum(area)]
    indices = np.searchsorted(seconds, query, side='right') - 1
    valid = indices >= 0
    i = np.maximum(indices, 0)
    elapsed = np.clip(query - seconds[i], 0, durations[i])
    return np.where(valid, cumulative[i] + elapsed * rates[i], 0.0)


def sample_support(seconds, good, config):

    delta = np.r_[np.diff(seconds), config.sample_seconds]
    return np.where(good, np.minimum(delta, config.sample_seconds), 0.0)


def window_event_sum(times, values, starts, ends):
    if not len(times):
        return np.zeros(len(ends))
    order = np.argsort(times, kind='stable')
    times, values = np.asarray(times)[order], np.asarray(values)[order]
    prefix = np.r_[0, np.cumsum(values)]
    return prefix[np.searchsorted(times, ends, side='right')] - prefix[np.searchsorted(times, starts, side='right')]


def build_power_features(frame, config):
    data, seconds, quality = normalize_power(frame, config)
    power = data.power_w.to_numpy(dtype=float)
    good = np.isfinite(power)
    durations = sample_support(seconds, good, config)
    ends_index = pd.date_range(data.timestamp.iloc[0].ceil(f'{config.step_minutes}min'),
                               data.timestamp.iloc[-1].floor(f'{config.step_minutes}min'),
                               freq=f'{config.step_minutes}min')
    ends = np.array([item.timestamp() for item in ends_index])
    starts = ends - config.window_minutes * 60
    observed = integral_at(ends, seconds, durations, good.astype(float)) - integral_at(starts, seconds, durations, good.astype(float))
    power_rate = np.nan_to_num(power, nan=0.0)
    energy = (integral_at(ends, seconds, durations, power_rate) - integral_at(starts, seconds, durations, power_rate)) / 3600
    active_rate = (power >= config.on_power_threshold).astype(float)
    active = (integral_at(ends, seconds, durations, active_rate) - integral_at(starts, seconds, durations, active_rate)) / 60
    sessions = detect_sessions(seconds, power, config)
    start_times = sessions.start_detected_at.to_numpy(dtype=float)
    complete = sessions.loc[sessions.status.eq('complete')]
    complete_times = complete.end_detected_at.to_numpy(dtype=float)
    start_counts = window_event_sum(start_times, np.ones(len(sessions)), starts, ends)
    complete_counts = window_event_sum(complete_times, np.ones(len(complete)), starts, ends)
    sum_duration = window_event_sum(complete_times, complete.duration_seconds.to_numpy(dtype=float), starts, ends)
    start_hours = pd.to_datetime(start_times, unit='s', utc=True).tz_convert(config.timezone).hour
    night_counts = window_event_sum(start_times, ((start_hours >= 21) | (start_hours < 6)).astype(int), starts, ends)
    local = ends_index.tz_convert(config.timezone)
    hour = local.hour + local.minute / 60
    coverage = np.clip(observed / (config.window_minutes * 60), 0, 1)
    features = pd.DataFrame({'window_end': ends_index.astype(str),
        'energy_wh_2h': energy, 'mean_power_w_2h': np.divide(energy * 3600, observed, out=np.full(len(ends), np.nan), where=observed > 0),
        'above_threshold_minutes_2h': active, 'confirmed_starts_2h': start_counts,
        'completed_sessions_2h': complete_counts,
        'mean_completed_duration_minutes_2h': np.divide(sum_duration, complete_counts * 60, out=np.zeros(len(ends)), where=complete_counts > 0),
        'night_confirmed_starts_2h': night_counts,
        'hour_sin': np.sin(2 * np.pi * hour / 24), 'hour_cos': np.cos(2 * np.pi * hour / 24),
        'weekday_sin': np.sin(2 * np.pi * local.dayofweek / 7), 'weekday_cos': np.cos(2 * np.pi * local.dayofweek / 7),
        'coverage_fraction_2h': coverage,
        'history_complete': ((coverage >= config.min_coverage) & (starts >= seconds[0])).astype(int),
        'schema_version': SCHEMA})

    features.loc[features.history_complete.ne(1), POWER_FEATURES] = np.nan
    quality.update({'config': asdict(config), 'schema_version': SCHEMA,
                    'start_utc': data.timestamp.iloc[0].isoformat(), 'end_utc': data.timestamp.iloc[-1].isoformat(),
                    'feature_rows': len(features), 'usable_feature_rows': int(features.history_complete.sum()),
                    'confirmed_sessions': len(sessions), 'complete_sessions': len(complete),
                    'censored_sessions': int(sessions.status.ne('complete').sum()),
                    'coverage_definition': 'Each valid sample supports at most one nominal sampling interval; not proof of sensor availability or absence of upstream imputation',
                    'activation_definition': 'Power-derived estimate, not a button press or HA device operation state',
                    'causal_timing': 'Counts use confirmation times; duration appears only after off confirmation'})
    for col in ('start_time', 'start_detected_at', 'end_time', 'end_detected_at'):
        sessions[col] = pd.to_datetime(sessions[col], unit='s', utc=True)
    return features, sessions, quality
