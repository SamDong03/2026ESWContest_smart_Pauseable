
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from ha_model_lifecycle import Lifecycle
from verify_ha_month_cycle import HOUSE


def export(month_dir, destination):
    root, destination = Path(month_dir), Path(destination)
    for phase in ('train', 'verify', 'refresh'):
        report = json.loads((root / f'{phase}_report.json').read_text())
        if not report.get('passed') or report.get('source_type') != 'synthetic':
            raise ValueError('All isolated synthetic lifecycle checks must have passed')
    life = Lifecycle(root / 'synthetic_models', 'synthetic', HOUSE)
    model = life.active_dir()
    if model is None:
        raise ValueError('No validated synthetic model')
    baseline = root / 'synthetic_baseline.json'
    if json.loads(baseline.read_text()).get('source_type') != 'synthetic':
        raise ValueError('Only a synthetic baseline can be exported')
    files = {'synthetic_baseline.json': baseline,
             'synthetic_models/identity.json': life.root / 'identity.json',
             'synthetic_models/active.json': life.root / 'active.json'}
    for name in ('manifest.json', 'validation.json', 'isolation_forest.joblib'):
        files['synthetic_models/' + (model / name).relative_to(life.root).as_posix()] = model / name
    metadata = {'source_type': 'synthetic', 'household_id': HOUSE,
                'clinical_validation': False, 'production_eligible': False,
                'model_id': json.loads((model / 'manifest.json').read_text())['model_id'],
                'warning': 'Generated demo fixture only. Never install into a local household lifecycle store.',
                'files': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, path in files.items():
            archive.write(path, name)
        archive.writestr('ASSET_MANIFEST.json', json.dumps(metadata, indent=2))
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.month_dir, args.output), indent=2))
