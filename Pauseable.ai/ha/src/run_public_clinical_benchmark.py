
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score

from fetch_public_clinical import DATASETS
from ha_anomaly_models import sha256
from public_clinical_data import (read_tihm, read_casas, read_miratar, temporal_split, participant_split,
                                  TIHM_FEATURES, CASAS_FEATURES, MIRATAR_FEATURES)
from public_clinical_models import fit_score, event_overlap


def cohort_metrics(scores):
    report = {}
    for diagnosis, name in [(1, 'dementia'), (2, 'mci')]:
        group = scores.loc[scores.diagnosis.isin([4, 5, diagnosis])]
        positive = group.diagnosis.eq(diagnosis)
        entry = {'positive_subjects': int(positive.sum()), 'heldout_reference_subjects': int((~positive).sum())}
        for model in ['if', 'ae', 'either', 'both']:
            alerts = group[model + '_alert']
            entry[model] = {'positive_alerted': int((alerts & positive).sum()),
                            'reference_alerted': int((alerts & ~positive).sum()),
                            'sensitivity': float(alerts[positive].mean()) if positive.any() else None,
                            'reference_specificity': float((~alerts[~positive]).mean()) if (~positive).any() else None}
            if model in ['if', 'ae']:
                entry[model]['roc_auc'] = float(roc_auc_score(positive, group[model + '_score'])) if positive.nunique() == 2 else None
        report[name] = entry
    return report


def run(dataset, archive, output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new experiment directory')

    import hashlib
    if hashlib.md5(Path(archive).read_bytes()).hexdigest() != DATASETS[dataset][2]:
        raise ValueError('Archive does not match the pinned public release')
    output.mkdir(parents=True, exist_ok=True)
    labels = None
    if dataset == 'tihm':
        features, labels, inventory = read_tihm(archive)
        columns = TIHM_FEATURES
        labels.to_csv(output / 'event_labels.csv', index=False)
    elif dataset == 'casas':
        features, inventory = read_casas(archive)
        columns = CASAS_FEATURES
    else:
        features, inventory = read_miratar(archive)
        columns = MIRATAR_FEATURES
    features.to_csv(output / 'features.csv', index=False)
    scores, models, skipped = [], [], []
    if dataset == 'casas':
        groups = [('older_reference_cohort', participant_split(features))]
    else:
        groups = []
        for subject, group in features.groupby('subject_id', sort=True):
            try:
                groups.append((subject, temporal_split(group, labels)))
            except ValueError as error:
                skipped.append({'subject_id': subject, 'reason': str(error)})
    for subject, parts in groups:
        result, manifest = fit_score(*parts, columns, output / 'models' / subject,
            basis=('Reference diagnosis codes 4/5; participant-disjoint split, not a longitudinal household model'
                   if dataset == 'casas' else
                   'Unlabelled personal routine reference, not confirmed normal.' +
                   (' Recorded event days +/-1 excluded retrospectively.' if dataset == 'tihm' else '') ))
        scores.append(result)
        models.append({'subject_id': subject, 'splits': manifest['splits'], 'warnings': manifest['warnings']})
        print(dataset, subject, 'train/cal/test', [len(p) for p in parts], flush=True)
    if not scores:
        raise ValueError('No eligible research split; inspect source coverage')
    scored = pd.concat(scores, ignore_index=True)
    scored.to_csv(output / 'scores.csv', index=False)
    evaluation = (cohort_metrics(scored) if dataset == 'casas' else event_overlap(scored, labels)
                  if dataset == 'tihm' else {'accuracy': None, 'reason': 'No clinical or anomaly ground truth'})
    report = {'dataset': dataset, 'source_type': 'public', 'production_eligible': False, 'deployed_to_pi': False,
              'created_at_utc': datetime.now(timezone.utc).isoformat(), 'archive_sha256': sha256(archive),
              'source': 'https://zenodo.org/records/' + DATASETS[dataset][0], 'inventory': inventory,
              'feature_columns': columns, 'feature_rows': len(features), 'models_trained': len(models),
              'scored_rows': len(scored), 'scored_subjects': int(scored.subject_id.nunique()),
              'skipped_subjects': skipped, 'models': models, 'evaluation': evaluation,
              'holdout_alert_fraction_not_accuracy': {m: float(scored[m + '_alert'].mean()) for m in ['if', 'ae', 'either', 'both']},
              'limitations': ['Research only; no dementia diagnostic validation or production model promotion.',
                  'No threshold/hyperparameter tuning on these holdouts. Percentile chosen in advance: 95.',
                  'TIHM/MIRATAR: silent days are missing, not normal; sensor coverage unverified.',
                  'Day-level aggregation uses the released naive clock, not assumed UTC or Korea time.',
                  'CASAS: whole scripted sessions, completion/cue and cohort selection bias; not a paper reproduction.',
                  'Clinical labels and demographics never enter sensor feature vectors.',
                  'Small/nonrepresentative cohorts; this is not a prospective clinical evaluation.']}
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'dataset': dataset, 'models': len(models), 'scored_rows': len(scored),
                      'evaluation': evaluation}, indent=2), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=[*DATASETS, 'all'], required=True)
    parser.add_argument('--download-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    for name in DATASETS if args.dataset == 'all' else [args.dataset]:
        run(name, Path(args.download_dir) / (name + '.zip'), Path(args.output_dir) / name)
