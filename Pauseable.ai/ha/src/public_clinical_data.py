
from pathlib import PurePosixPath
import hashlib
import re
import zipfile

import numpy as np
import pandas as pd


TIHM_LOCATIONS = ['Kitchen', 'Hallway', 'Lounge', 'Bedroom', 'Fridge Door',
                  'Bathroom', 'Front Door', 'Back Door']
TIHM_FEATURES = ['events_' + s.lower().replace(' ', '_') for s in TIHM_LOCATIONS] + [
    'active_hours', 'night_event_fraction', 'event_span_hours']


def checked_archive(path):
    archive = zipfile.ZipFile(path)
    names = archive.namelist()
    if len(names) != len(set(names)) or len(names) > 10000:
        archive.close()
        raise ValueError('Duplicate or excessive archive members')
    for item in archive.infolist():
        name = PurePosixPath(item.filename)
        if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename:
            archive.close()
            raise ValueError('Unsafe archive member')
    if sum(i.file_size for i in archive.infolist()) > 1_500_000_000:
        archive.close()
        raise ValueError('Archive exceeds research size budget')
    return archive


def parse_times(values):

    times = pd.to_datetime(values, errors='raise', format='mixed')
    if times.isna().any():
        raise ValueError('Missing timestamp')
    return times


def tihm_day_features(activity, labels):
    for frame, columns in [(activity, ['patient_id', 'location_name', 'date']),
                           (labels, ['patient_id', 'date', 'type'])]:
        if not set(columns).issubset(frame.columns) or frame[columns].isna().any().any():
            raise ValueError('Missing TIHM fields')
    activity, labels = activity.copy(), labels.copy()
    activity['date'], labels['date'] = parse_times(activity.date), parse_times(labels.date)
    if not activity.location_name.isin(TIHM_LOCATIONS).all():
        raise ValueError('Unknown TIHM location; review schema')
    activity['day'], labels['day'] = activity.date.dt.floor('D'), labels.date.dt.floor('D')
    label_map = labels.groupby(['patient_id', 'day'])['type'].agg(lambda x: '|'.join(sorted(set(x))))
    rows = []
    for (subject, day), group in activity.groupby(['patient_id', 'day'], sort=True):
        counts = group.location_name.value_counts()
        row = {'dataset': 'tihm', 'source_type': 'public', 'subject_id': str(subject), 'day': day,
               'label_status': 'event_recorded' if (subject, day) in label_map.index else 'unknown',
               'label_types': label_map.get((subject, day), ''), 'coverage_verified': False,
               'active_hours': int(group.date.dt.hour.nunique()),
               'night_event_fraction': float(group.date.dt.hour.lt(6).mean()),
               'event_span_hours': float((group.date.max() - group.date.min()).total_seconds() / 3600)}
        row.update({feature: int(counts.get(location, 0)) for feature, location in zip(TIHM_FEATURES, TIHM_LOCATIONS)})
        rows.append(row)


    return pd.DataFrame(rows), labels


def read_tihm(path):
    with checked_archive(path) as archive:
        activity = pd.read_csv(archive.open('Dataset/Activity.csv'), dtype={'patient_id': str})
        labels = pd.read_csv(archive.open('Dataset/Labels.csv'), dtype={'patient_id': str})
        inventory = {}
        for name in ['Demographics', 'Physiology', 'Sleep']:
            frame = pd.read_csv(archive.open('Dataset/' + name + '.csv'))
            inventory[name] = {'rows': len(frame), 'columns': list(frame.columns),
                               'used_as_predictors': False}
    features, labels = tihm_day_features(activity, labels)
    return features, labels, {'activity_rows': len(activity), 'activity_duplicate_rows': int(activity.duplicated().sum()),
        'subjects': int(activity.patient_id.nunique()), 'observed_subject_days': len(features),
        'label_rows': len(labels), 'label_types': labels.type.value_counts().to_dict(), 'other_tables': inventory}


def temporal_split(frame, labels=None):
    pass
    if frame.subject_id.nunique() != 1:
        raise ValueError('Temporal split requires exactly one subject')
    frame = frame.sort_values('day').copy()
    if frame.day.duplicated().any():
        raise ValueError('Duplicate subject day')
    if len(frame) < 30:
        raise ValueError('At least 30 observed days required')
    a, b = frame.day.iloc[int(len(frame) * .6)], frame.day.iloc[int(len(frame) * .8)]
    train = frame.loc[(frame.day > frame.day.min()) & (frame.day < a - pd.Timedelta(days=1))]
    calibration = frame.loc[(frame.day >= a) & (frame.day < b - pd.Timedelta(days=1))]
    test = frame.loc[(frame.day >= b) & (frame.day < frame.day.max())]
    if labels is not None:
        subject_labels = labels.loc[labels.patient_id.eq(frame.subject_id.iloc[0]), 'day']
        excluded = set()
        for day in subject_labels:
            excluded.update(day + pd.Timedelta(days=offset) for offset in [-1, 0, 1])
        train = train.loc[~train.day.isin(excluded)]
        calibration = calibration.loc[~calibration.day.isin(excluded)]
    if len(train) < 15 or len(calibration) < 5 or len(test) < 5:
        raise ValueError('Insufficient reference/calibration/test days after purging and event exclusion')
    return train, calibration, test


CASAS_FEATURES = ['session_minutes', 'motion_on_count', 'door_open_count', 'item_absent_count',
                  'motion_sensor_count', 'door_sensor_count', 'item_sensor_count', 'gap_median_seconds',
                  'gap_p95_seconds']


def casas_session(text):
    if text.strip().upper() in ('NO TESTING', 'NO SENSOR DATA'):
        raise ValueError(text.strip())
    rows, malformed, ignored = [], 0, 0
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3 or not re.fullmatch(r'\d{2}:\d{2}:\d{2}(?:\.\d+)?', parts[0]):
            malformed += 1
            continue
        if not re.fullmatch(r'[MDI]\d+', parts[1]):
            ignored += 1
            continue
        hours, minutes, seconds = map(float, parts[0].split(':'))
        if hours >= 24 or minutes >= 60 or seconds >= 60:
            raise ValueError('Invalid session clock')
        rows.append((hours * 3600 + minutes * 60 + seconds, parts[1], parts[2].upper()))
    if malformed:
        raise ValueError('Unparsed session lines: ' + str(malformed))
    if len(rows) < 20:
        raise ValueError('Insufficient motion/door/item events')
    frame = pd.DataFrame(rows, columns=['seconds', 'sensor', 'state'])
    if (frame.seconds.diff() < -60).any():
        raise ValueError('Clock reset or multi-session file; requires explicit session boundaries')
    frame = frame.sort_values('seconds')
    span = float(frame.seconds.max() - frame.seconds.min())
    if not 60 <= span <= 6 * 3600:
        raise ValueError('Session span outside 1 minute to 6 hours')
    gaps = frame.seconds.diff().dropna()
    data = {'session_minutes': span / 60, 'gap_median_seconds': float(gaps.median()),
            'gap_p95_seconds': float(gaps.quantile(.95))}
    for prefix, name, state in [('M', 'motion', 'ON'), ('D', 'door', 'OPEN'), ('I', 'item', 'ABSENT')]:
        sensor = frame.sensor.str.startswith(prefix)
        data[name + '_sensor_count'] = int(frame.loc[sensor, 'sensor'].nunique())
        data[name + '_' + state.lower() + '_count'] = int((sensor & frame.state.eq(state)).sum())
    return data, {'sensor_rows': len(frame), 'ignored_non_MDI_rows': ignored}


def read_casas(path):
    rows, skipped = [], []
    with checked_archive(path) as archive:
        text = archive.read('cognitive_assessment/documents/diagnosis.txt').decode('utf-8')
        diagnoses = {}
        for line in text.splitlines():
            match = re.fullmatch(r'\s*(\d+)\s+(\d+)\s*', line)
            if match:
                subject, label = match.groups()
                if subject in diagnoses or not 1 <= int(label) <= 10:
                    raise ValueError('Conflicting/invalid diagnosis')
                diagnoses[subject] = int(label)
        if not diagnoses:
            raise ValueError('No diagnosis table')
        for name in sorted(archive.namelist()):
            if not re.fullmatch(r'cognitive_assessment/data/\d+\.txt', name):
                continue
            subject = str(int(PurePosixPath(name).stem))
            try:
                values, quality = casas_session(archive.read(name).decode('utf-8'))
            except ValueError as error:
                skipped.append({'subject_id': subject, 'diagnosis': diagnoses.get(subject, 10), 'reason': str(error)})
                continue
            rows.append({'dataset': 'casas', 'source_type': 'public', 'subject_id': subject,
                         'diagnosis': diagnoses.get(subject, 10), **values, **quality})
    return pd.DataFrame(rows), {'diagnosis_table_subjects': len(diagnoses),
        'diagnosis_table_counts': pd.Series(diagnoses).value_counts().to_dict(), 'usable_sessions': len(rows),
        'skipped_sessions': skipped, 'protocol': 'whole scripted session; cues and task completion can confound',
        'paper_cohort_reproduction': False}


def participant_split(frame, seed=42):
    if frame.subject_id.duplicated().any():
        raise ValueError('One row per participant is required')
    parts = {key: [] for key in ['train', 'calibration', 'test']}
    for diagnosis in [4, 5]:
        group = frame.loc[frame.diagnosis.eq(diagnosis)].copy()
        ordered = sorted(group.subject_id, key=lambda s: hashlib.sha256(f'{seed}:{s}'.encode()).hexdigest())
        a, b = int(len(ordered) * .6), int(len(ordered) * .8)
        for name, subjects in zip(parts, [ordered[:a], ordered[a:b], ordered[b:]]):
            parts[name].append(group.loc[group.subject_id.isin(subjects)])
    parts['test'].append(frame.loc[frame.diagnosis.isin([1, 2])])
    result = tuple(pd.concat(parts[name], ignore_index=True) for name in parts)
    if any(len(part) < minimum for part, minimum in zip(result, [15, 5, 5])):
        raise ValueError('Insufficient participants')
    return result


MIRATAR_SENSORS = ['front_door', 'bathroom', 'bedroom', 'kitchen', 'living_room']
MIRATAR_FEATURES = ['sensor_' + sensor + '_' + metric for sensor in MIRATAR_SENSORS
                    for metric in ['record_count', 'one_fraction', 'recorded_minutes', 'night_record_fraction']]


def miratar_sensor_days(frame, sensor):
    if sensor not in MIRATAR_SENSORS or not {'time', 'count'}.issubset(frame.columns):
        raise ValueError('Unknown MIRATAR sensor schema')
    frame = frame.copy()
    frame['time'] = parse_times(frame.time)
    frame['count'] = pd.to_numeric(frame['count'], errors='raise')
    if not frame['count'].isin([0, 1]).all():
        raise ValueError('Motion/door values must be binary; do not mix temperature')
    frame['day'] = frame.time.dt.floor('D')
    rows = []
    for day, group in frame.groupby('day'):
        prefix = 'sensor_' + sensor + '_'
        rows.append({'day': day, prefix + 'record_count': len(group),
                     prefix + 'one_fraction': float(group['count'].mean()),
                     prefix + 'recorded_minutes': int(group.time.nunique()),
                     prefix + 'night_record_fraction': float(group.time.dt.hour.lt(6).mean())})
    return pd.DataFrame(rows)


def read_miratar(path):
    homes, inventory = {}, []
    with checked_archive(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith('.csv'):
                continue
            match = re.fullmatch(r'Database of sensors in smart homes/(Door|Motion|Temperature)_Sensor/(.+)_(M\d+)\.csv', name)
            if not match:
                raise ValueError('Unknown MIRATAR CSV path')
            kind, sensor, subject = match.groups()
            frame = pd.read_csv(archive.open(name))
            raw_rows = len(frame)
            missing = frame[['time', 'count']].isna().any(axis=1)
            frame = frame.loc[~missing].copy()
            times = parse_times(frame.time)
            inventory.append({'file': name, 'raw_rows': raw_rows, 'rows': len(frame),
                              'excluded_missing_time_or_value': int(missing.sum()),
                              'duplicate_minute_rows': int(times.duplicated().sum()),
                              'start': str(times.min()), 'end': str(times.max()), 'used_as_predictors': kind != 'Temperature'})
            if kind == 'Temperature':
                continue
            days = miratar_sensor_days(frame, sensor.lower())
            homes.setdefault(subject, []).append(days)
    rows, missing = [], {}
    for subject, tables in sorted(homes.items()):
        combined = tables[0]
        for table in tables[1:]:
            combined = combined.merge(table, on='day', how='outer', validate='one_to_one')
        combined = combined.reindex(columns=['day', *MIRATAR_FEATURES])
        valid = combined[MIRATAR_FEATURES].notna().all(axis=1)
        missing[subject] = int((~valid).sum())
        combined = combined.loc[valid].copy()
        combined['dataset'], combined['source_type'], combined['subject_id'] = 'miratar', 'public', subject
        combined['coverage_verified'], combined['label_status'] = False, 'unknown'
        rows.append(combined)
    return pd.concat(rows, ignore_index=True), {'csv_inventory': inventory, 'households': len(homes),
        'days_excluded_missing_sensor_records': missing, 'downloaded_pretrained_models_executed': False,
        'clinical_labels_available': False, 'binary_polarity': 'Not interpreted as open/closed or appliance cycles',
        'duplicate_policy': 'Retained minute-resolution records; order/duration not reconstructed'}
