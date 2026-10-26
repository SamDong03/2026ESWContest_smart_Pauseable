

import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-dir', default='data/features')
    parser.add_argument('--pattern', default='ha_pi_all_*_features.csv')
    parser.add_argument('--output', required=True)
    parser.add_argument('--household-id', required=True)
    args = parser.parse_args()
    files = sorted(Path(args.feature_dir).glob(args.pattern))
    frames, skipped = [], []
    for path in files:
        frame = pd.read_csv(path)
        required = {'source_type', 'history_complete', 'window_end'}
        if not required.issubset(frame.columns) or frame.empty:
            skipped.append(str(path))
            continue
        frame = frame.loc[frame['source_type'].eq('local') & frame['history_complete'].eq(1)].copy()
        frames.append(frame)
    output = Path(args.output)
    if output.exists():
        raise ValueError('Use a new candidate output path')
    if not frames or all(f.empty for f in frames):
        raise ValueError('No local, complete-history windows yet. Keep collecting; no model was trained.')
    common_schema = set(frames[0].columns)
    if any(set(f.columns) != common_schema for f in frames):
        raise ValueError('Mixed feature schemas; regenerate consistent features before training')
    candidate = pd.concat(frames, ignore_index=True).sort_values('window_end')
    duplicate = candidate['window_end'].duplicated(keep=False)
    if duplicate.any():
        raise ValueError('Overlapping candidate timestamps; select one collection stream')
    candidate['household_id'] = args.household_id
    candidate['review_status'] = 'unreviewed'
    output.parent.mkdir(parents=True, exist_ok=True)
    candidate.to_csv(output, index=False)
    summary = {'candidate_rows': len(candidate), 'observed_days': int(pd.to_datetime(candidate['window_end']).dt.date.nunique()),
               'skipped_files': skipped, 'status': 'needs_normal_period_review',
               'note': 'Exclude outages, tests and known unusual days before training. A rule-normal label is not ground truth.'}
    output.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
