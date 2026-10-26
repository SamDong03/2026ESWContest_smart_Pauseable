
import argparse
import json
import math
from pathlib import Path

import pandas as pd

from ha_anomaly_models import score_frame
from power_features import POWER_FEATURES, PowerConfig
from prepare_public_power import prepare
from train_ha_anomaly_models import train_models


def run(input_path, output_dir, profile_path):
    profile = json.loads(Path(profile_path).read_text(encoding='utf-8'))
    if profile.get('source_type') != 'public':
        raise ValueError('This command is for public benchmarks, not local personalized activation')
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new experiment directory')
    config = PowerConfig(**profile.pop('config'))
    features, quality = prepare(input_path, output / 'prepared', config=config, **profile)
    eligible = features.loc[features.history_complete.eq(1)].copy()
    training_path = output / 'eligible_features.csv'
    eligible.to_csv(training_path, index=False)

    gap = config.window_minutes + math.ceil(config.max_session_seconds / 60) + math.ceil(config.max_gap_seconds / 60)
    manifest, validation = train_models(training_path, output / 'model', 'public', profile['household_id'],
        'Unlabelled public appliance power assumed routine for a development benchmark; '
        'NOT verified normal behavior. ' + profile['appliance'] + '. ' + profile['parameter_basis'],
        gap_minutes=gap, min_days=7, feature_columns=POWER_FEATURES)
    after = pd.to_datetime(manifest['splits']['test']['start'], utc=True)
    heldout = eligible.loc[pd.to_datetime(eligible.window_end, utc=True) >= after].reset_index(drop=True)
    comparison = score_frame(heldout, output / 'model')
    if not comparison.model_status.eq('shadow').all():
        raise ValueError('Model scoring failed: ' + str(comparison.model_status.value_counts().to_dict()))
    comparison.to_csv(output / 'comparison.csv', index=False)
    warnings = []
    if quality['complete_sessions'] == 0:
        warnings.append('No complete power-derived sessions: duration/complete-count features are not validated for this selection.')
    if quality['censored_sessions'] > quality['complete_sessions']:
        warnings.append('More censored than complete sessions: do not use extracted session counts as behavior ground truth.')
    report = {'dataset_profile': str(profile_path), 'household_id': profile['household_id'],
              'appliance': profile['appliance'], 'quality': quality, 'validation': validation,
              'time_gap_minutes': gap, 'features': POWER_FEATURES,
              'training_days': manifest['observed_days'], 'splits': manifest['splits'],
              'model_status': 'public_benchmark_only', 'deployed': False, 'quality_warnings': warnings,
              'limitations': ['No anomaly or clinical labels: alert fraction is not accuracy or measured false-positive rate.',
                  'Power-derived sessions are estimates; no fridge door, lock, illness or button ground truth.',
                  'Public power schema is distinct from the current HA state-event schema.',
                  'One household per dataset and byte-limited prefix; not a multi-house generalization evaluation.',
                  'REFIT cleaned data can contain undetectable imputation. See quality.source_warning.',
                  'Do not select models/thresholds on this holdout without a fresh independent evaluation period.']}
    (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output / 'experiment.json'), 'eligible_rows': len(eligible),
                      'test_rows': len(heldout), 'alert_fraction': validation['normal_holdout_alert_fraction'],
                      'deployed': False}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    run(args.input, args.output_dir, args.profile)


if __name__ == '__main__':
    main()
