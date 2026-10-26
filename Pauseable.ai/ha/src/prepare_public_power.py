
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from power_features import PowerConfig, build_power_features


def read_power(path, format_name, *, power_column=None, issues_column='Issues'):
    if format_name == 'ukdale':
        raw = pd.read_csv(path, sep=r'\s+', header=None)
        if raw.shape[1] != 2:
            raise ValueError('Use a two-column UK-DALE active-power channel, not mains/button_press')
        timestamps = pd.to_datetime(pd.to_numeric(raw.iloc[:, 0], errors='raise'), unit='s', utc=True)
        values = raw.iloc[:, 1]
        notes = {'format': 'ukdale', 'issues_flag_present': False, 'unit': 'W',
                 'source_warning': 'Select an individual active-power channel; apparent VA mains is not accepted as W'}
    elif format_name == 'refit':
        raw = pd.read_csv(path)
        if not power_column or not power_column.startswith('Appliance'):
            raise ValueError('REFIT requires an explicit Appliance column from the household metadata')
        if not {'Unix', power_column}.issubset(raw.columns):
            raise ValueError('Missing REFIT Unix or selected appliance column')
        timestamps = pd.to_datetime(pd.to_numeric(raw['Unix'], errors='raise'), unit='s', utc=True)
        values = pd.to_numeric(raw[power_column], errors='coerce').copy()
        issue_count = 0
        if issues_column in raw:
            bad = pd.to_numeric(raw[issues_column], errors='coerce').ne(0)
            issue_count = int(bad.sum())
            values.loc[bad] = np.nan
        notes = {'format': 'refit_cleaned', 'power_column': power_column, 'unit': 'W',
                 'issues_flag_present': issues_column in raw, 'flagged_rows': issue_count,
                 'source_warning': 'Cleaned REFIT contains upstream forward-filled/zero-filled values; their full missingness cannot be recovered'}
    elif format_name == 'power_csv':
        raw = pd.read_csv(path)
        if not {'timestamp', 'power_w'}.issubset(raw.columns):
            raise ValueError('Power CSV requires timezone-aware timestamp and instantaneous active power_w, not cumulative Wh')
        if not raw.timestamp.astype(str).str.contains(r'(?:Z|[+-]\d{2}:?\d{2})$', regex=True).all():
            raise ValueError('Power CSV timestamps must include UTC or a timezone offset')
        timestamps, values = pd.to_datetime(raw.timestamp, utc=True), raw.power_w
        notes = {'format': 'power_csv', 'unit': 'W', 'source_warning': 'User must verify sensor units and missingness before use'}
    else:
        raise ValueError('Unsupported power format')
    return pd.DataFrame({'timestamp': timestamps, 'power_w': values}), notes


def prepare(input_path, output_dir, format_name, config, *, household_id, appliance,
            citation, license_name, parameter_basis, power_column=None, source_type='public'):
    if source_type not in {'public', 'local', 'synthetic'}:
        raise ValueError('Explicit data source required')
    if not all(str(x).strip() for x in (household_id, appliance, citation, license_name, parameter_basis)):
        raise ValueError('Provenance and parameter basis are required')
    if format_name in {'ukdale', 'refit'} and source_type != 'public':
        raise ValueError('Public records cannot be relabelled as local or synthetic')
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new preparation directory')
    data, notes = read_power(input_path, format_name, power_column=power_column)
    features, sessions, quality = build_power_features(data, config)
    features['source_type'] = source_type
    features['household_id'] = household_id
    features['review_status'] = 'unreviewed'
    quality.update(notes)
    quality.update({'source_type': source_type, 'household_id': household_id, 'appliance': appliance,
                    'citation': citation, 'license': license_name, 'parameter_basis': parameter_basis,
                    'input_sha256': hashlib.sha256(Path(input_path).read_bytes()).hexdigest()})
    sidecar = Path(str(input_path) + '.source.json')
    if sidecar.exists():
        origin = json.loads(sidecar.read_text(encoding='utf-8'))
        if origin['sha256'] != quality['input_sha256']:
            raise ValueError('Downloaded input no longer matches its source manifest')
        quality['download'] = origin
    output.mkdir(parents=True, exist_ok=True)
    features.to_csv(output / 'features.csv', index=False)
    sessions.to_csv(output / 'sessions.csv', index=False)
    (output / 'quality.json').write_text(json.dumps(quality, indent=2), encoding='utf-8')
    print(json.dumps(quality, indent=2))
    return features, quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--profile', required=True, help='JSON profile with format, config and provenance')
    args = parser.parse_args()
    profile = json.loads(Path(args.profile).read_text(encoding='utf-8'))
    config = PowerConfig(**profile.pop('config'))
    prepare(args.input, args.output_dir, config=config, **profile)


if __name__ == '__main__':
    main()
