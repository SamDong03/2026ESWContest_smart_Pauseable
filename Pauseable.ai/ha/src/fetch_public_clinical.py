
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from fetch_public_power import fetch


DATASETS = {
    'tihm': ('7622128', 'TIHM_Dataset.zip', 'ccf913f38a7808bc366bf0e799b409e4'),
    'casas': ('15713579', 'cognitive_assessment.zip', '7357205e9218523a8be966a74f3721cc'),
    'miratar': ('15553764', 'Database of sensors in smart homes.zip', 'daaec9c5b0fc28dc229dc006d3866175'),
}


def download(dataset, output):
    record_id, filename, expected_md5 = DATASETS[dataset]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with urlopen('https://zenodo.org/api/records/' + record_id, timeout=60) as response:
        record = json.load(response)
    info = next(item for item in record['files'] if item['key'] == filename)
    if info['checksum'] != 'md5:' + expected_md5:
        raise ValueError('Pinned release checksum changed; inspect before using')
    path = output / (dataset + '.zip')
    if path.exists():
        if hashlib.md5(path.read_bytes()).hexdigest() != expected_md5:
            raise ValueError('Existing archive checksum mismatch')
    else:
        fetch(info['links']['self'], path, max_bytes=100_000_000,
              citation=record['metadata']['doi'],
              license_name=('Research only; metadata CC-BY-4.0 conflicts with noncommercial note'
                            if dataset == 'tihm' else record['metadata']['license']['id']))
    if hashlib.md5(path.read_bytes()).hexdigest() != expected_md5:
        raise ValueError('Downloaded archive checksum mismatch; do not use')
    (output / (dataset + '.record.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
    with (output / 'downloads.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'time_utc': datetime.now(timezone.utc).isoformat(),
            'dataset': dataset, 'md5_verified': expected_md5,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'archive': str(path), 'production_eligible': False}) + '\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=[*DATASETS, 'all'], required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    for name in DATASETS if args.dataset == 'all' else [args.dataset]:
        print(download(name, args.output_dir), flush=True)
